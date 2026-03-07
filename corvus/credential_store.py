"""CredentialStore — load, get, set, delete credentials via SOPS+age.

Credentials are stored as a SOPS-encrypted JSON file on disk.
All encrypt/decrypt operations use real ``sops`` and ``age`` CLI tools
— no in-process crypto, no mocks.

Typical usage::

    store = CredentialStore()          # defaults: ~/.corvus/credentials.json
    store.load()                       # decrypt + parse
    token = store.get("paperless", "token")
    store.set("firefly", "token", "new_tok")
    store.delete("old_service")
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from corvus.auth.openai_oauth import refresh_access_token
from corvus.auth.profile_resolver import resolve_profile
from corvus.auth.profiles import (
    ApiKeyCredential,
    AuthProfileStore,
    OAuthCredential,
    TokenCredential,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service environment variable map — single source of truth for the mapping
# between credential store field names and the env vars that TOOL_MODULE_DEFS
# (corvus/capabilities/modules.py) reads at resolve time.
#
# Used by:
#   - inject() → _inject_service_env_vars(): set env vars from SOPS credentials
#   - from_env(): populate credential store from env vars (Docker/CI)
#
# To add a new service, add an entry here AND a ToolModuleEntry in modules.py.
# modules.py derives requires_env from this map — no duplication needed.
# ---------------------------------------------------------------------------
SERVICE_ENV_MAP: dict[str, dict[str, str]] = {
    "ha": {"url": "HA_URL", "token": "HA_TOKEN"},
    "paperless": {"url": "PAPERLESS_URL", "token": "PAPERLESS_API_TOKEN"},
    "firefly": {"url": "FIREFLY_URL", "token": "FIREFLY_API_TOKEN"},
    "obsidian": {"url": "OBSIDIAN_URL", "token": "OBSIDIAN_API_KEY"},
    "google": {"creds_path": "GOOGLE_CREDS_PATH"},
}


def mask_value(value: str | None, visible_chars: int = 8) -> str:
    """Mask a credential value for safe display.

    Shows the first *visible_chars* characters followed by '...'.
    Values shorter than *visible_chars* are fully masked.
    URLs are masked after the scheme (https://...).
    """
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        scheme_end = value.index("://") + 3
        return value[:scheme_end] + "..."
    if len(value) <= visible_chars:
        return "..."
    return value[:visible_chars] + "..."


class CredentialStore:
    """Manage service credentials in a SOPS+age encrypted JSON file.

    Parameters
    ----------
    path
        Path to the SOPS-encrypted JSON credentials file.
        Defaults to ``~/.corvus/credentials.json``.
    age_key_file
        Path to the age private key file used for decryption.
        Defaults to ``~/.corvus/age-key.txt``.
    """

    def __init__(
        self,
        path: Path | None = None,
        age_key_file: str | None = None,
    ) -> None:
        self._path = Path(path) if path else Path.home() / ".corvus" / "credentials.json"
        self._age_key_file = age_key_file or str(Path.home() / ".corvus" / "age-key.txt")
        self._data: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Decrypt the SOPS file and parse its JSON into memory.

        Raises
        ------
        FileNotFoundError
            If the credentials file does not exist on disk.
        RuntimeError
            If ``sops --decrypt`` fails (wrong key, corrupt file, etc.).
        """
        if not self._path.exists():
            raise FileNotFoundError(f"Credentials file not found: {self._path}")

        result = subprocess.run(
            ["sops", "--decrypt", str(self._path)],
            capture_output=True,
            text=True,
            env=self._sops_env(),
        )

        if result.returncode != 0:
            raise RuntimeError(f"sops decrypt failed: {result.stderr.strip()}")

        self._data = json.loads(result.stdout)

    def get(self, service: str, key: str) -> str:
        """Return a single credential value.

        Raises
        ------
        KeyError
            If *service* is not in the store, or *key* is not in that service.
        """
        if service not in self._data:
            raise KeyError(f"Unknown service: {service!r}")
        svc = self._data[service]
        if key not in svc:
            raise KeyError(f"Unknown key {key!r} in service {service!r}")
        return svc[key]

    def set(self, service: str, key: str, value: str) -> None:
        """Set a credential value and re-encrypt the file to disk."""
        if service not in self._data:
            self._data[service] = {}
        self._data[service][key] = value
        self._save()

    def set_bulk(self, service: str, data: dict[str, str]) -> None:
        """Set multiple keys for a service with a single encrypt cycle."""
        if service not in self._data:
            self._data[service] = {}
        self._data[service].update(data)
        if self._path is not None:
            self._save()

    def delete(self, service: str) -> None:
        """Remove an entire service from the store.  No-op if missing."""
        if service not in self._data:
            return
        del self._data[service]
        self._save()

    def services(self) -> list[str]:
        """Return a sorted list of all service names."""
        return sorted(self._data.keys())

    def credential_values(self) -> list[str]:
        """Return every leaf string value across all services."""
        values: list[str] = []
        for svc in self._data.values():
            for v in svc.values():
                if isinstance(v, str) and v:
                    values.append(v)
        return values

    def get_auth_profiles(self) -> AuthProfileStore:
        """Return the auth profile store from credential data."""
        raw = self._data.get("_auth_profiles", {})
        return AuthProfileStore.from_dict(raw)

    def set_auth_profiles(self, profiles: AuthProfileStore) -> None:
        """Save auth profiles to credential data and re-encrypt if backed by file."""
        self._data["_auth_profiles"] = profiles.to_dict()
        if self._path is not None:
            self._save()

    def inject(self) -> None:
        """Inject credentials into environment and configure tool modules.

        Checks auth profiles first. Falls back to legacy flat credentials
        if no profiles exist.
        """
        auth_profiles = self.get_auth_profiles()
        if auth_profiles.profiles:
            self._inject_from_profiles(auth_profiles)
        else:
            self._inject_flat_credentials()
        self._inject_service_env_vars()

    def _inject_from_profiles(self, auth_profiles: AuthProfileStore) -> None:
        """Inject credentials from auth profiles into environment."""
        provider_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "ollama": "OLLAMA_BASE_URL",
            "kimi": "KIMI_BOT_TOKEN",
            "codex": "CODEX_API_KEY",
        }

        for provider, env_var in provider_env_map.items():
            profile_id = resolve_profile(auth_profiles, provider=provider)
            if profile_id is None:
                continue
            cred = auth_profiles.profiles[profile_id]
            if isinstance(cred, ApiKeyCredential) and cred.key:
                os.environ[env_var] = cred.key
            elif isinstance(cred, TokenCredential) and cred.token:
                os.environ[env_var] = cred.token
            elif isinstance(cred, OAuthCredential) and cred.access_token:
                os.environ[env_var] = cred.access_token

        # OpenAI-compat needs special handling (base_url in metadata)
        compat_id = resolve_profile(auth_profiles, provider="openai_compat")
        if compat_id:
            cred = auth_profiles.profiles[compat_id]
            if isinstance(cred, ApiKeyCredential):
                if cred.metadata.get("base_url"):
                    os.environ["OPENAI_COMPAT_BASE_URL"] = cred.metadata["base_url"]
                if cred.key:
                    os.environ["OPENAI_COMPAT_API_KEY"] = cred.key

    def _inject_flat_credentials(self) -> None:
        """Inject credentials from legacy flat credential data."""
        if "anthropic" in self._data:
            api_key = self._data["anthropic"].get("api_key")
            if api_key:
                os.environ["ANTHROPIC_API_KEY"] = api_key

        if "openai" in self._data:
            api_key = self._data["openai"].get("api_key")
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key

        if "ollama" in self._data:
            base_url = self._data["ollama"].get("base_url")
            if base_url:
                os.environ["OLLAMA_BASE_URL"] = base_url

        if "kimi" in self._data:
            api_key = self._data["kimi"].get("api_key")
            if api_key:
                os.environ["KIMI_BOT_TOKEN"] = api_key

        if "codex" in self._data:
            codex = self._data["codex"]
            access = codex.get("access_token", "")
            try:
                expires = int(codex.get("expires", "0"))
            except (ValueError, TypeError):
                expires = 0
            if access and expires > int(time.time()):
                os.environ["CODEX_API_KEY"] = access
            elif codex.get("refresh_token"):
                try:
                    tokens = refresh_access_token(refresh_token=codex["refresh_token"])
                    self._data["codex"]["access_token"] = tokens.access_token
                    self._data["codex"]["refresh_token"] = tokens.refresh_token
                    self._data["codex"]["expires"] = str(tokens.expires)
                    self._data["codex"]["account_id"] = tokens.account_id
                    os.environ["CODEX_API_KEY"] = tokens.access_token
                    if self._path is not None:
                        self._save()
                except Exception as exc:
                    logger.warning("Failed to refresh Codex OAuth token: %s", exc)

        if "openai_compat" in self._data:
            compat = self._data["openai_compat"]
            if compat.get("base_url"):
                os.environ["OPENAI_COMPAT_BASE_URL"] = compat["base_url"]
            if compat.get("api_key"):
                os.environ["OPENAI_COMPAT_API_KEY"] = compat["api_key"]

    def _inject_service_env_vars(self) -> None:
        """Set service env vars so TOOL_MODULE_DEFS can read them at resolve time."""
        for svc_key, field_map in SERVICE_ENV_MAP.items():
            if svc_key not in self._data:
                continue
            svc_data = self._data[svc_key]
            for field, env_var in field_map.items():
                val = svc_data.get(field)
                if val:
                    os.environ[env_var] = val

    @classmethod
    def from_env(cls) -> CredentialStore:
        """Build a CredentialStore from environment variables (fallback path).

        When no SOPS-encrypted credentials file exists (e.g. running in a
        Docker container that receives secrets via env vars), this classmethod
        constructs a store populated from well-known environment variable
        names.

        The resulting store supports ``get()`` and ``inject()`` but cannot
        ``set()``/``delete()`` (there is no backing file).
        """
        store = cls.__new__(cls)
        store._path = None  # type: ignore[assignment]  # from_env stores have no backing file
        store._age_key_file = ""
        store._data = {}

        env_map: dict[str, dict[str, str]] = {
            **SERVICE_ENV_MAP,
            "anthropic": {"api_key": "ANTHROPIC_API_KEY"},
            "openai": {"api_key": "OPENAI_API_KEY"},
            "ollama": {"base_url": "OLLAMA_BASE_URL"},
            "kimi": {"api_key": "KIMI_BOT_TOKEN"},
            "openai_compat": {
                "base_url": "OPENAI_COMPAT_BASE_URL",
                "api_key": "OPENAI_COMPAT_API_KEY",
            },
            "webhook_secret": {"value": "WEBHOOK_SECRET"},
            "codex": {"access_token": "CODEX_API_KEY"},
        }
        for service, keys in env_map.items():
            svc_data: dict[str, str] = {}
            for key, env_var in keys.items():
                val = os.environ.get(env_var, "")
                if val:
                    svc_data[key] = val
            if svc_data:
                store._data[service] = svc_data
        return store

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Write to a temp file, SOPS-encrypt it, then atomically rename.

        This eliminates the plaintext-on-disk window — if SOPS fails or the
        process crashes, the temp file is cleaned up and the original
        encrypted file remains untouched.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2))
            pub_key = self._get_age_public_key()
            result = subprocess.run(
                [
                    "sops",
                    "--encrypt",
                    "--in-place",
                    "--input-type",
                    "json",
                    "--output-type",
                    "json",
                    "--age",
                    pub_key,
                    str(tmp),
                ],
                capture_output=True,
                text=True,
                env=self._sops_env(),
            )
            if result.returncode != 0:
                raise RuntimeError(f"sops encrypt failed: {result.stderr.strip()}")
            tmp.rename(self._path)  # atomic on same filesystem
        finally:
            if tmp.exists():
                tmp.unlink()

    def _get_age_public_key(self) -> str:
        """Extract the public key from the age key file.

        The key file contains a comment line like::

            # public key: age1abc123...

        Returns
        -------
        str
            The age public key string.
        """
        key_path = Path(self._age_key_file)
        if not key_path.exists():
            raise FileNotFoundError(f"Age key file not found: {self._age_key_file}")
        for line in key_path.read_text().splitlines():
            if line.startswith("# public key:"):
                return line.split(":", 1)[1].strip()
        raise RuntimeError(f"Could not find '# public key:' line in {self._age_key_file}")

    def _sops_env(self) -> dict[str, str]:
        """Build an environment dict that tells SOPS which age key to use.

        Sets ``SOPS_AGE_KEY_FILE`` for decryption and ``SOPS_CONFIG``
        to ``/dev/null`` so SOPS doesn't walk up the directory tree
        looking for a ``.sops.yaml`` (the repo has one that only matches
        ``*.env.enc`` files).
        """
        env = os.environ.copy()
        env["SOPS_AGE_KEY_FILE"] = self._age_key_file
        env["SOPS_CONFIG"] = "/dev/null"
        return env


def get_credential_store(
    creds_path: Path | None = None,
    age_key_file: str | None = None,
) -> CredentialStore:
    """Load credential store from SOPS file, falling back to env vars.

    This is the main entry point used by server.py at startup.

    Args:
        creds_path: Override path for testing. Defaults to ~/.corvus/credentials.json.
        age_key_file: Override key file for testing. Defaults to ~/.corvus/age-key.txt.

    Returns:
        A loaded CredentialStore (either from SOPS file or env vars).
    """
    path = creds_path or Path.home() / ".corvus" / "credentials.json"
    key = age_key_file or str(Path.home() / ".corvus" / "age-key.txt")

    if path.exists():
        store = CredentialStore(path=path, age_key_file=key)
        store.load()
        return store

    return CredentialStore.from_env()
