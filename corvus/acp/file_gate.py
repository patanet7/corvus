"""ACP file gate — workspace boundary enforcement and secret pattern filtering (Layer 3).

Validates every file read/write from ACP agents against:
- Workspace boundary (resolved path must remain inside workspace_root)
- Secret file patterns (dotenv, PEM, SSH keys, credentials)
- Parent agent policy (read/write permissions)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)\.env(\..+)?$"),         # .env, .env.local, .env.production
    re.compile(r"\.pem$"),                       # *.pem
    re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)$"), # SSH private keys
    re.compile(r"\.key$"),                        # *.key
    re.compile(r"\.secrets?$"),                   # *.secret, *.secrets
    re.compile(r"(^|/)\.ssh(/|$)"),              # .ssh/ directory
    re.compile(r"(^|/)credentials$"),            # bare credentials file
]


@dataclass(frozen=True)
class FileGateResult:
    """Result of a file access check.

    Attributes:
        allowed: Whether the access is permitted.
        reason: Human-readable explanation of the decision.
        resolved_path: The fully resolved path if allowed, None if blocked.
    """

    allowed: bool
    reason: str
    resolved_path: Path | None = None


def _matches_secret_pattern(relative_path: str) -> bool:
    """Check if a relative path matches any secret file pattern."""
    # Normalize to forward slashes for consistent matching
    normalized = relative_path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in _SECRET_PATTERNS)


def check_file_access(
    *,
    path: str,
    workspace_root: Path,
    operation: str,
    parent_allows_read: bool = True,
    parent_allows_write: bool = True,
    allow_secret_access: bool = False,
) -> FileGateResult:
    """Check whether an ACP agent may access a file path.

    Checks are applied in order:
    1. Path resolution (absolute or relative to workspace_root)
    2. Workspace boundary enforcement (resolved path must be inside workspace_root)
    3. Secret pattern matching (blocks dotenv, PEM, SSH keys, credentials)
       — skipped if allow_secret_access is True (break-glass mode)
    4. Parent agent policy (read/write permission flags)

    Args:
        path: The file path requested by the agent (absolute or relative).
        workspace_root: The agent's workspace root directory.
        operation: Either "read" or "write".
        parent_allows_read: Whether the parent agent permits read operations.
        parent_allows_write: Whether the parent agent permits write operations.
        allow_secret_access: If True, skip secret pattern checks (break-glass).

    Returns:
        A FileGateResult indicating whether access is allowed.
    """
    workspace_resolved = workspace_root.resolve()

    # Step 1: Resolve path
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve()

    # Step 2: Boundary check
    try:
        relative = resolved.relative_to(workspace_resolved)
    except ValueError:
        logger.warning(
            "File gate blocked %s of %r: escapes workspace boundary",
            operation,
            path,
        )
        return FileGateResult(
            allowed=False,
            reason=f"Blocked: path escapes workspace boundary (resolved to {resolved})",
        )

    # Step 3: Secret pattern check (skipped in break-glass mode)
    relative_str = str(relative)
    if not allow_secret_access and _matches_secret_pattern(relative_str):
        logger.warning(
            "File gate blocked %s of %r: matches secret pattern",
            operation,
            path,
        )
        return FileGateResult(
            allowed=False,
            reason=f"Blocked: path matches secret file pattern ({relative_str})",
        )

    # Step 4: Parent policy check
    if operation == "read" and not parent_allows_read:
        return FileGateResult(
            allowed=False,
            reason="Blocked: parent agent policy denies read access",
        )
    if operation == "write" and not parent_allows_write:
        return FileGateResult(
            allowed=False,
            reason="Blocked: parent agent policy denies write access",
        )

    # All checks passed
    return FileGateResult(
        allowed=True,
        reason="Allowed",
        resolved_path=resolved,
    )
