"""Behavioral tests for CredentialStore with real SOPS+age encrypt/decrypt.

NO mocks — every test generates a real age key, encrypts real JSON with SOPS,
and verifies the CredentialStore can load/get/set/delete through real crypto.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from corvus.credential_store import CredentialStore


def _sops_env() -> dict[str, str]:
    """Build a clean env that prevents sops from using the repo .sops.yaml."""
    env = os.environ.copy()
    env["SOPS_CONFIG"] = "/dev/null"
    return env


# ---------------------------------------------------------------------------
# Helpers — real age-keygen + real sops encrypt
# ---------------------------------------------------------------------------


def _generate_age_key(tmp_path: Path) -> tuple[Path, str]:
    """Run real age-keygen, return (key_file_path, public_key)."""
    key_file = tmp_path / "age-key.txt"
    result = subprocess.run(
        ["age-keygen", "-o", str(key_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"age-keygen failed: {result.stderr}"

    # Extract public key from the comment line in stderr:
    # "Public key: age1..."
    for line in result.stderr.splitlines():
        if line.startswith("Public key:"):
            pub_key = line.split(":", 1)[1].strip()
            return key_file, pub_key

    # Fallback: read from the key file itself (comment line "# public key: age1...")
    for line in key_file.read_text().splitlines():
        if line.startswith("# public key:"):
            pub_key = line.split(":", 1)[1].strip()
            return key_file, pub_key

    raise RuntimeError("Could not extract public key from age-keygen output")


def _sops_encrypt(json_path: Path, age_pub_key: str) -> None:
    """Run real sops --encrypt --in-place --age on a JSON file."""
    result = subprocess.run(
        [
            "sops",
            "--encrypt",
            "--in-place",
            "--age",
            age_pub_key,
            str(json_path),
        ],
        capture_output=True,
        text=True,
        env=_sops_env(),
    )
    assert result.returncode == 0, f"sops encrypt failed: {result.stderr}"


def _write_and_encrypt(
    tmp_path: Path,
    data: dict,
) -> tuple[Path, Path]:
    """Write data as JSON, generate an age key, encrypt the file.

    Returns (json_path, key_file_path).
    """
    json_path = tmp_path / "credentials.json"
    json_path.write_text(json.dumps(data))

    key_file, pub_key = _generate_age_key(tmp_path)
    _sops_encrypt(json_path, pub_key)

    return json_path, key_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DATA = {
    "paperless": {"url": "https://paperless.example.com", "token": "pk_abc123"},
    "firefly": {"url": "https://firefly.example.com", "token": "ff_xyz789"},
    "obsidian": {"url": "https://obsidian.example.com", "api_key": "obs_key_42"},
}


@pytest.fixture
def encrypted_store(tmp_path):
    """Create a SOPS-encrypted credentials file and return (CredentialStore, json_path, key_file)."""
    json_path, key_file = _write_and_encrypt(tmp_path, SAMPLE_DATA)
    store = CredentialStore(path=json_path, age_key_file=str(key_file))
    store.load()
    return store, json_path, key_file


# ---------------------------------------------------------------------------
# TestCredentialStoreLoad
# ---------------------------------------------------------------------------


class TestCredentialStoreLoad:
    """Test loading SOPS-encrypted credential files."""

    def test_load_decrypts_valid_sops_file(self, tmp_path):
        """Write data dict, encrypt, load, verify all values via get()."""
        json_path, key_file = _write_and_encrypt(tmp_path, SAMPLE_DATA)
        store = CredentialStore(path=json_path, age_key_file=str(key_file))
        store.load()

        assert store.get("paperless", "url") == "https://paperless.example.com"
        assert store.get("paperless", "token") == "pk_abc123"
        assert store.get("firefly", "url") == "https://firefly.example.com"
        assert store.get("firefly", "token") == "ff_xyz789"
        assert store.get("obsidian", "url") == "https://obsidian.example.com"
        assert store.get("obsidian", "api_key") == "obs_key_42"

    def test_load_raises_on_missing_file(self, tmp_path):
        """FileNotFoundError for nonexistent path."""
        bogus_path = tmp_path / "does_not_exist.json"
        key_file, _ = _generate_age_key(tmp_path)
        store = CredentialStore(path=bogus_path, age_key_file=str(key_file))

        with pytest.raises(FileNotFoundError):
            store.load()

    def test_load_raises_on_wrong_key(self, tmp_path):
        """RuntimeError when age key doesn't match the one used to encrypt."""
        # Encrypt with one key
        json_path, _correct_key = _write_and_encrypt(tmp_path, SAMPLE_DATA)

        # Generate a different key
        wrong_key_dir = tmp_path / "wrong"
        wrong_key_dir.mkdir()
        wrong_key_file, _ = _generate_age_key(wrong_key_dir)

        store = CredentialStore(path=json_path, age_key_file=str(wrong_key_file))

        with pytest.raises(RuntimeError):
            store.load()


# ---------------------------------------------------------------------------
# TestCredentialStoreGetSet
# ---------------------------------------------------------------------------


class TestCredentialStoreGetSet:
    """Test get() and set() operations."""

    def test_get_raises_keyerror_for_missing_service(self, encrypted_store):
        """KeyError for unknown service."""
        store, _, _ = encrypted_store
        with pytest.raises(KeyError):
            store.get("nonexistent_service", "token")

    def test_get_raises_keyerror_for_missing_key(self, encrypted_store):
        """KeyError for unknown key within an existing service."""
        store, _, _ = encrypted_store
        with pytest.raises(KeyError):
            store.get("paperless", "nonexistent_key")

    def test_set_persists_and_reencrypts(self, encrypted_store):
        """set() updates in memory, re-encrypts file, and a fresh store reads it back."""
        store, json_path, key_file = encrypted_store

        # Set a new value
        store.set("paperless", "new_field", "new_value_123")

        # Verify in memory
        assert store.get("paperless", "new_field") == "new_value_123"

        # Verify file on disk is encrypted (not plaintext JSON)
        raw = json_path.read_text()
        assert "new_value_123" not in raw, "Plaintext value found in encrypted file"
        assert "sops" in raw, "File does not appear to be SOPS-encrypted"

        # Verify a fresh store can load and read the value back
        fresh = CredentialStore(path=json_path, age_key_file=str(key_file))
        fresh.load()
        assert fresh.get("paperless", "new_field") == "new_value_123"

    def test_set_adds_new_service(self, encrypted_store):
        """set() creates a service entry that didn't exist before."""
        store, json_path, key_file = encrypted_store

        store.set("new_service", "api_key", "ns_key_999")
        assert store.get("new_service", "api_key") == "ns_key_999"

        # Verify persistence
        fresh = CredentialStore(path=json_path, age_key_file=str(key_file))
        fresh.load()
        assert fresh.get("new_service", "api_key") == "ns_key_999"


# ---------------------------------------------------------------------------
# TestCredentialStoreDelete
# ---------------------------------------------------------------------------


class TestCredentialStoreDelete:
    """Test delete() operations."""

    def test_delete_removes_service(self, encrypted_store):
        """delete() removes a service; get() raises KeyError after deletion."""
        store, json_path, key_file = encrypted_store

        store.delete("paperless")

        with pytest.raises(KeyError):
            store.get("paperless", "token")

        # Other services still work
        assert store.get("firefly", "token") == "ff_xyz789"

        # Verify persistence
        fresh = CredentialStore(path=json_path, age_key_file=str(key_file))
        fresh.load()
        with pytest.raises(KeyError):
            fresh.get("paperless", "token")
        assert fresh.get("firefly", "token") == "ff_xyz789"

    def test_delete_nonexistent_is_noop(self, encrypted_store):
        """delete() on unknown service doesn't raise."""
        store, _, _ = encrypted_store
        store.delete("totally_unknown")  # Should not raise


# ---------------------------------------------------------------------------
# TestCredentialStoreServices
# ---------------------------------------------------------------------------


class TestCredentialStoreServices:
    """Test services() listing."""

    def test_services_returns_all_names(self, encrypted_store):
        """services() returns sorted list of top-level service keys."""
        store, _, _ = encrypted_store
        assert store.services() == sorted(SAMPLE_DATA.keys())


# ---------------------------------------------------------------------------
# TestCredentialStoreValues
# ---------------------------------------------------------------------------


class TestCredentialStoreValues:
    """Test credential_values() listing."""

    def test_credential_values_returns_all_values(self, encrypted_store):
        """Every leaf string value in the store is returned."""
        store, _, _ = encrypted_store
        values = store.credential_values()

        expected_values = set()
        for service_data in SAMPLE_DATA.values():
            for v in service_data.values():
                expected_values.add(v)

        assert set(values) == expected_values
        assert len(values) == len(expected_values)


# ---------------------------------------------------------------------------
# TestCredentialStoreInject
# ---------------------------------------------------------------------------


class TestCredentialStoreInject:
    """inject() calls configure() on tool modules with stored credentials."""

    def test_inject_configures_ha(self, tmp_path):
        """inject() sets HA module-level config from store values."""
        import corvus.tools.ha as ha_mod

        # Save originals
        orig_url, orig_token = ha_mod._ha_url, ha_mod._ha_token
        try:
            data = {
                "ha": {"url": "http://ha.test:8123", "token": "ha_test_tok_42"},
            }
            json_path, key_file = _write_and_encrypt(tmp_path, data)
            store = CredentialStore(path=json_path, age_key_file=str(key_file))
            store.load()
            store.inject()

            assert ha_mod._ha_url == "http://ha.test:8123"
            assert ha_mod._ha_token == "ha_test_tok_42"
        finally:
            ha_mod._ha_url = orig_url
            ha_mod._ha_token = orig_token

    def test_inject_configures_paperless(self, tmp_path):
        """inject() sets Paperless module-level config from store values."""
        import corvus.tools.paperless as paperless_mod

        orig_url = paperless_mod._paperless_url
        orig_token = paperless_mod._paperless_token
        try:
            data = {
                "paperless": {
                    "url": "http://paperless.test:8010",
                    "token": "pk_test_abc",
                },
            }
            json_path, key_file = _write_and_encrypt(tmp_path, data)
            store = CredentialStore(path=json_path, age_key_file=str(key_file))
            store.load()
            store.inject()

            assert paperless_mod._paperless_url == "http://paperless.test:8010"
            assert paperless_mod._paperless_token == "pk_test_abc"
        finally:
            paperless_mod._paperless_url = orig_url
            paperless_mod._paperless_token = orig_token

    def test_inject_configures_firefly(self, tmp_path):
        """inject() sets Firefly module-level config from store values."""
        import corvus.tools.firefly as firefly_mod

        orig_url = firefly_mod._firefly_url
        orig_token = firefly_mod._firefly_token
        try:
            data = {
                "firefly": {
                    "url": "http://firefly.test:8081",
                    "token": "ff_test_xyz",
                },
            }
            json_path, key_file = _write_and_encrypt(tmp_path, data)
            store = CredentialStore(path=json_path, age_key_file=str(key_file))
            store.load()
            store.inject()

            assert firefly_mod._firefly_url == "http://firefly.test:8081"
            assert firefly_mod._firefly_token == "ff_test_xyz"
        finally:
            firefly_mod._firefly_url = orig_url
            firefly_mod._firefly_token = orig_token

    def test_inject_skips_unconfigured_services(self, tmp_path):
        """Store with only HA — should not crash even though paperless/firefly missing."""
        import corvus.tools.firefly as firefly_mod
        import corvus.tools.ha as ha_mod
        import corvus.tools.paperless as paperless_mod

        orig_ha_url, orig_ha_token = ha_mod._ha_url, ha_mod._ha_token
        orig_p_url, orig_p_token = paperless_mod._paperless_url, paperless_mod._paperless_token
        orig_f_url, orig_f_token = firefly_mod._firefly_url, firefly_mod._firefly_token
        try:
            # Reset all modules to None before test
            ha_mod._ha_url = None
            ha_mod._ha_token = None
            paperless_mod._paperless_url = None
            paperless_mod._paperless_token = None
            firefly_mod._firefly_url = None
            firefly_mod._firefly_token = None

            data = {
                "ha": {"url": "http://ha.only:8123", "token": "ha_only_tok"},
            }
            json_path, key_file = _write_and_encrypt(tmp_path, data)
            store = CredentialStore(path=json_path, age_key_file=str(key_file))
            store.load()
            store.inject()  # Should not raise

            # HA should be configured
            assert ha_mod._ha_url == "http://ha.only:8123"
            assert ha_mod._ha_token == "ha_only_tok"

            # Others should remain None (not touched)
            assert paperless_mod._paperless_url is None
            assert firefly_mod._firefly_url is None
        finally:
            ha_mod._ha_url = orig_ha_url
            ha_mod._ha_token = orig_ha_token
            paperless_mod._paperless_url = orig_p_url
            paperless_mod._paperless_token = orig_p_token
            firefly_mod._firefly_url = orig_f_url
            firefly_mod._firefly_token = orig_f_token

    def test_inject_sets_anthropic_env_var(self, tmp_path):
        """inject() sets ANTHROPIC_API_KEY env var."""
        orig_val = os.environ.get("ANTHROPIC_API_KEY")
        try:
            # Remove env var if it exists
            os.environ.pop("ANTHROPIC_API_KEY", None)

            data = {
                "anthropic": {"api_key": "sk-ant-test-inject-42"},
            }
            json_path, key_file = _write_and_encrypt(tmp_path, data)
            store = CredentialStore(path=json_path, age_key_file=str(key_file))
            store.load()
            store.inject()

            assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test-inject-42"
        finally:
            if orig_val is not None:
                os.environ["ANTHROPIC_API_KEY"] = orig_val
            else:
                os.environ.pop("ANTHROPIC_API_KEY", None)


# ---------------------------------------------------------------------------
# TestCredentialStoreEnvFallback
# ---------------------------------------------------------------------------


class TestCredentialStoreEnvFallback:
    """When no credential file exists, fall back to env vars."""

    def test_from_env_loads_ha_from_env_vars(self, tmp_path):
        """from_env() class method builds a store from environment variables."""
        orig_url = os.environ.get("HA_URL")
        orig_token = os.environ.get("HA_TOKEN")
        try:
            os.environ["HA_URL"] = "http://ha.env-fallback:8123"
            os.environ["HA_TOKEN"] = "ha_env_tok_99"

            store = CredentialStore.from_env()

            assert store.get("ha", "url") == "http://ha.env-fallback:8123"
            assert store.get("ha", "token") == "ha_env_tok_99"
        finally:
            if orig_url is not None:
                os.environ["HA_URL"] = orig_url
            else:
                os.environ.pop("HA_URL", None)
            if orig_token is not None:
                os.environ["HA_TOKEN"] = orig_token
            else:
                os.environ.pop("HA_TOKEN", None)


# ---------------------------------------------------------------------------
# TestServerIntegration
# ---------------------------------------------------------------------------


class TestServerIntegration:
    """CredentialStore integrates with server startup flow."""

    def test_store_loads_or_falls_back_to_env(self, tmp_path):
        """get_credential_store() returns env fallback when no file exists."""
        from corvus.credential_store import get_credential_store

        store = get_credential_store(creds_path=tmp_path / "nope.json")
        assert isinstance(store, CredentialStore)
        assert store.services() is not None

    def test_store_loads_sops_file_when_present(self, tmp_path):
        """get_credential_store() decrypts SOPS file when it exists."""
        from corvus.credential_store import get_credential_store

        data = {"ha": {"url": "http://ha.local", "token": "test-tok-12345678"}}
        json_path, key_file = _write_and_encrypt(tmp_path, data)

        store = get_credential_store(creds_path=json_path, age_key_file=str(key_file))
        assert store.get("ha", "url") == "http://ha.local"
