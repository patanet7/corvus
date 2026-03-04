"""Shared sanitization layer — credential redaction + path traversal protection.

All tool outputs and user-supplied paths pass through these functions
before reaching the LLM context or filesystem.
"""

import os
import re

# Compiled regex patterns for credential redaction (case-insensitive).
_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer\s+[A-Za-z0-9+/=._~-]{8,}", re.IGNORECASE),
    re.compile(r"Authorization:\s*[^\n\r]+", re.IGNORECASE),
    re.compile(r"api[_-]?key[\"'\s:=]+[A-Za-z0-9+/=._~-]{20,}", re.IGNORECASE),
    re.compile(r"token[\"'\s:=]+[A-Za-z0-9+/=._~-]{20,}", re.IGNORECASE),
    re.compile(r"Set-Cookie:\s*[^\n\r]+", re.IGNORECASE),
    re.compile(r"Cookie:\s*[^\n\r]+", re.IGNORECASE),
]

_MIN_CREDENTIAL_LENGTH = 8  # Skip values shorter than this (too generic).


def register_credential_patterns(values: list[str]) -> None:
    """Build regex patterns from actual credential values.

    Called at startup after CredentialStore.load() to ensure value-specific
    redaction. Values shorter than _MIN_CREDENTIAL_LENGTH are skipped to
    avoid false positives on generic strings like URLs or short words.

    Args:
        values: List of credential values to register for redaction.
    """
    for value in values:
        if len(value) < _MIN_CREDENTIAL_LENGTH:
            continue
        # Escape regex special characters so literal values match
        pattern = re.compile(re.escape(value))
        _CREDENTIAL_PATTERNS.append(pattern)


_REDACTED = "[REDACTED]"


def sanitize(text: str) -> str:
    """Redact credentials from text using regex pattern matching.

    Strips bearer tokens, authorization headers, API keys, token values,
    and cookie headers, replacing matches with ``[REDACTED]``.

    Args:
        text: Raw text that may contain credentials.

    Returns:
        Text with credential patterns replaced by ``[REDACTED]``.
    """
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def sanitize_path(raw_path: str) -> str:
    """Validate and normalize a relative path, blocking traversal attacks.

    Args:
        raw_path: A user-supplied relative path (e.g. ``notes/daily.md``).

    Returns:
        Normalized relative path safe for filesystem access.

    Raises:
        ValueError: If the path is empty, absolute, or contains traversal.
    """
    if not raw_path or not raw_path.strip():
        raise ValueError("empty")

    if raw_path.startswith("/"):
        raise ValueError("absolute")

    normalized = os.path.normpath(raw_path)

    if ".." in normalized.split(os.sep):
        raise ValueError("traversal")

    return normalized
