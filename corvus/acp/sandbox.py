"""ACP sandbox layer — environment stripping (Layer 1) and process isolation (Layer 7).

Two environment contexts:
- **Spawn env** (build_acp_spawn_env): for the ACP agent binary itself (npx, codex-acp).
  Keeps a functional PATH and agent-specific auth tokens but strips Corvus secrets.
- **Child command env** (build_acp_child_env): for commands the agent requests via
  terminal/create. Locked down: restricted PATH, no auth tokens, no secrets.

Process sandbox (build_sandbox_command) wraps the spawn command in platform-specific
network isolation (sandbox-exec on macOS, unshare on Linux).
"""

import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Env keys that are ALWAYS stripped from the spawn env (Corvus secrets, cloud creds).
_STRIPPED_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^CORVUS_", re.IGNORECASE),
    re.compile(r"^SOPS_", re.IGNORECASE),
    re.compile(r"^AWS_", re.IGNORECASE),
    re.compile(r"^ANTHROPIC_API_KEY$", re.IGNORECASE),
    re.compile(r"^ANTHROPIC_AUTH_TOKEN$", re.IGNORECASE),
    re.compile(r"^DATABASE_URL$", re.IGNORECASE),
    re.compile(r"^FIREFLY_", re.IGNORECASE),
    re.compile(r"^PAPERLESS_", re.IGNORECASE),
    re.compile(r"^HA_TOKEN$", re.IGNORECASE),
    re.compile(r"^GMAIL_", re.IGNORECASE),
    re.compile(r".*_SECRET$", re.IGNORECASE),
    re.compile(r".*_PASSWORD$", re.IGNORECASE),
)

# Env keys explicitly allowed through to the spawn env (agent binary needs these).
_SPAWN_PASSTHROUGH_KEYS: frozenset[str] = frozenset({
    "PATH", "HOME", "TMPDIR", "TERM", "LANG", "LC_ALL", "USER", "SHELL",
    # Node/npm needs these to resolve packages
    "NODE_PATH", "NPM_CONFIG_CACHE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
    "XDG_DATA_HOME", "XDG_STATE_HOME",
    # ACP agent auth (Codex uses OPENAI_API_KEY or CODEX_API_KEY)
    "OPENAI_API_KEY", "CODEX_API_KEY",
    # fnm/nvm/volta node version managers
    "FNM_DIR", "FNM_MULTISHELL_PATH", "NVM_DIR", "VOLTA_HOME",
})

# For child commands (terminal/create), only these survive.
_CHILD_ALLOWED_KEYS: frozenset[str] = frozenset({
    "PATH", "TERM", "LANG", "LC_ALL", "TMPDIR", "USER",
})

_CHILD_SAFE_PATH: str = "/usr/bin:/bin"

_DARWIN_SANDBOX_PROFILE: str = "(version 1)\n(allow default)\n(deny network*)"


def _is_stripped(key: str) -> bool:
    """Check if an env key matches any stripped pattern."""
    return any(pat.match(key) for pat in _STRIPPED_KEY_PATTERNS)


def build_acp_spawn_env(
    *,
    workspace: Path,
    host_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build environment for spawning the ACP agent binary.

    Keeps a functional PATH (so npx/node work), passes through agent auth
    tokens, but strips all Corvus-internal secrets and cloud credentials.

    Args:
        workspace: The agent workspace directory. Used as HOME and TMPDIR base.
        host_env: Optional host environment to filter. Defaults to os.environ.

    Returns:
        A sanitized environment dict for the agent process.
    """
    source = host_env if host_env is not None else dict(os.environ)

    env: dict[str, str] = {}
    for key, value in source.items():
        if _is_stripped(key):
            continue
        if key in _SPAWN_PASSTHROUGH_KEYS:
            env[key] = value

    # Override HOME and TMPDIR to workspace
    env["HOME"] = str(workspace)
    env["TMPDIR"] = str(workspace / "tmp")

    return env


def build_acp_child_env(
    *,
    workspace: Path,
    host_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build locked-down environment for commands the agent runs via terminal/create.

    Restricted PATH, no auth tokens, no secrets.

    Args:
        workspace: The agent workspace directory.
        host_env: Optional host environment to filter. Defaults to os.environ.

    Returns:
        A minimal environment dict for sandboxed command execution.
    """
    source = host_env if host_env is not None else dict(os.environ)

    env: dict[str, str] = {
        key: value for key, value in source.items() if key in _CHILD_ALLOWED_KEYS
    }

    env["PATH"] = _CHILD_SAFE_PATH
    env["HOME"] = str(workspace)
    env["TMPDIR"] = str(workspace / "tmp")

    return env



def build_sandbox_command(
    cmd: list[str],
    *,
    platform: str | None = None,
) -> list[str]:
    """Wrap a command in a platform-specific sandbox for network isolation.

    Args:
        cmd: The command and arguments to sandbox.
        platform: Override for sys.platform (useful for testing).

    Returns:
        The command wrapped with sandbox tooling, or unchanged on unsupported platforms.
    """
    plat = platform if platform is not None else sys.platform

    if plat == "darwin":
        return ["sandbox-exec", "-p", _DARWIN_SANDBOX_PROFILE, *cmd]

    if plat == "linux":
        return ["unshare", "--net", "--map-root-user", *cmd]

    logger.warning(
        "No sandbox available for platform %r; running command unsandboxed",
        plat,
    )
    return cmd
