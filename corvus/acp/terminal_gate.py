"""ACP terminal gate — Layer 4 security for terminal/create requests.

Validates every terminal command from ACP agents against a compiled
blocklist of dangerous patterns and enforces parent agent policy.
All terminal commands from ACP agents are confirm-gated.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Network tools
    (re.compile(r"\bcurl\b"), "curl"),
    (re.compile(r"\bwget\b"), "wget"),
    (re.compile(r"\bnc\b"), "nc"),
    (re.compile(r"\bncat\b"), "ncat"),
    (re.compile(r"\bnetcat\b"), "netcat"),
    (re.compile(r"\bssh\b"), "ssh"),
    (re.compile(r"\bscp\b"), "scp"),
    (re.compile(r"\bsftp\b"), "sftp"),
    # Secret reads
    (re.compile(r"\bcat\s+\.env\b"), "cat .env"),
    (re.compile(r"\bprintenv\b"), "printenv"),
    (re.compile(r"\b(echo|printf)\s+\$\w*"), "echo/printf $VAR"),
    (re.compile(r"\benv\b(?!\s*\w+=)"), "bare env"),
    # Container / privilege escalation
    (re.compile(r"\bdocker\b"), "docker"),
    (re.compile(r"\bpodman\b"), "podman"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"\bsu\b(?:\s|$)"), "su"),
    # Destructive
    (re.compile(r"\brm\s+-rf\s+/"), "rm -rf /"),
    (re.compile(r"\bchmod\s+777\b"), "chmod 777"),
]


@dataclass(frozen=True)
class TerminalGateResult:
    """Result of a terminal command gate check.

    Attributes:
        allowed: Whether the command is permitted to execute.
        reason: Human-readable explanation of the decision.
        requires_confirm: Whether the command requires user confirmation.
            Always True for ACP terminal commands.
    """

    allowed: bool
    reason: str
    requires_confirm: bool = True


def check_terminal_command(
    *,
    command: str,
    parent_allows_bash: bool,
) -> TerminalGateResult:
    """Validate a terminal command against security policies.

    Args:
        command: The shell command string to validate.
        parent_allows_bash: Whether the parent agent's policy allows bash execution.

    Returns:
        A TerminalGateResult indicating whether the command is allowed.
    """
    if not parent_allows_bash:
        logger.warning("Terminal command denied by parent agent policy: %r", command)
        return TerminalGateResult(
            allowed=False,
            reason="Denied by parent agent policy",
            requires_confirm=True,
        )

    for pattern, label in _BLOCKED_PATTERNS:
        if pattern.search(command):
            logger.warning(
                "Terminal command blocked by pattern %r: %r", label, command
            )
            return TerminalGateResult(
                allowed=False,
                reason=f"Blocked by terminal gate: matched {label!r} pattern",
                requires_confirm=True,
            )

    logger.info("Terminal command allowed (requires confirmation): %r", command)
    return TerminalGateResult(
        allowed=True,
        reason="Allowed by terminal gate",
        requires_confirm=True,
    )
