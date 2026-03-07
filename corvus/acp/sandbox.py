"""ACP sandbox layer — environment stripping (Layer 1) and process isolation (Layer 7).

Provides two public functions:
- build_acp_env: strips secrets from the host environment, restricts PATH,
  and sets HOME/TMPDIR to the agent workspace.
- build_sandbox_command: wraps a command list in a platform-specific sandbox
  (sandbox-exec on macOS, unshare on Linux).
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_ENV_KEYS: frozenset[str] = frozenset(
    {"PATH", "TERM", "LANG", "LC_ALL", "TMPDIR", "USER"}
)

_SAFE_PATH: str = "/usr/bin:/bin"

_DARWIN_SANDBOX_PROFILE: str = "(version 1)\n(allow default)\n(deny network*)"


def build_acp_env(
    *,
    workspace: Path,
    host_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized environment dict for an ACP agent process.

    Args:
        workspace: The agent workspace directory. Used as HOME and base for TMPDIR.
        host_env: Optional host environment to filter. Defaults to os.environ.

    Returns:
        A dict containing only allowed environment variables with safe overrides.
    """
    source = host_env if host_env is not None else dict(os.environ)

    env: dict[str, str] = {
        key: value for key, value in source.items() if key in _ALLOWED_ENV_KEYS
    }

    # Apply mandatory overrides
    env["PATH"] = _SAFE_PATH
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
