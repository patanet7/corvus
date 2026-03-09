"""Sanitize credential patterns from tool results.

Redacts API keys, tokens, passwords, connection strings, JWTs, and other
credential patterns before they enter the agent context window.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled regex patterns for credential detection.
# Each tuple: (compiled_pattern, replacement_template)
# Order matters — more specific patterns should come first.
# ---------------------------------------------------------------------------

SANITIZER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ----- Authorization headers -----
    # "Authorization: Bearer <token>" or "Authorization: Basic <token>"
    (
        re.compile(
            r"(Authorization\s*[:=]\s*)(Bearer\s+|Basic\s+|Token\s+)?\S+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # Standalone "Bearer <token>" (not preceded by Authorization)
    (
        re.compile(r"(?<!Authorization[\s:=])(Bearer\s+)[A-Za-z0-9_\-/.=+]{8,}", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # ----- JWT tokens (three base64url segments separated by dots) -----
    (
        re.compile(
            r"eyJ[A-Za-z0-9_-]{4,}\.eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_\-+/=]{4,}"
        ),
        "[REDACTED_JWT]",
    ),
    # ----- AWS access key IDs (AKIA..., 20 chars) -----
    (
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        "[REDACTED_AWS_KEY]",
    ),
    # ----- Prefixed API keys: sk-, pk_, rk_, key- -----
    (
        re.compile(r"\b(sk-|pk_|rk_|key-)[A-Za-z0-9_\-]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    # ----- Connection strings: ://user:password@ -----
    (
        re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)"),
        r"\1[REDACTED]\3",
    ),
    # ----- Key=value credential pairs -----
    # Matches: api_key=..., token=..., password=..., secret=..., passwd=...,
    #          access_key=..., secret_key=..., client_secret=..., etc.
    (
        re.compile(
            r"(?i)((?:api[_-]?key|token|password|passwd|secret|access[_-]?key|"
            r"secret[_-]?key|client[_-]?secret|auth[_-]?token|private[_-]?key)"
            r"\s*[=:]\s*)[\"']?([^\s\"',;}{)]{4,})[\"']?"
        ),
        r"\1[REDACTED]",
    ),
    # ----- Long hex strings (64+ chars — likely tokens, not git SHAs) -----
    # Require at least one digit AND one a-f letter to avoid false positives
    # on repeated single characters.
    (
        re.compile(r"\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{64,}\b"),
        "[REDACTED_HEX]",
    ),
]


def sanitize_tool_result(text: str) -> str:
    """Redact credential patterns from *text* and return the sanitized version.

    The function is idempotent: applying it to already-sanitized text produces
    the same output.  Non-sensitive content passes through unchanged.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in SANITIZER_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
