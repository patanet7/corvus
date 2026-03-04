"""Behavioral tests for register_credential_patterns dynamic sanitization.

NO mocks — uses importlib.reload to reset module state between tests so
registered patterns don't leak across test boundaries.
"""

import importlib

import pytest

import corvus.sanitize


@pytest.fixture(autouse=True)
def _reset_sanitize_module():
    """Reload corvus.sanitize before each test to reset _CREDENTIAL_PATTERNS."""
    importlib.reload(corvus.sanitize)
    yield
    # Reload again after each test for a clean slate.
    importlib.reload(corvus.sanitize)


# ---------------------------------------------------------------------------
# 1. Registered value is redacted
# ---------------------------------------------------------------------------


def test_registered_value_is_redacted():
    """A registered credential value must be replaced with [REDACTED]."""
    secret = "super-secret-api-key-12345"
    corvus.sanitize.register_credential_patterns([secret])

    result = corvus.sanitize.sanitize(f"The key is {secret} in config")
    assert secret not in result
    assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# 2. Multiple values all redacted
# ---------------------------------------------------------------------------


def test_multiple_values_all_redacted():
    """When 3 values are registered, all 3 must be redacted in one pass."""
    secrets = [
        "password-alpha-9999",
        "token-bravo-8888",
        "apikey-charlie-7777",
    ]
    corvus.sanitize.register_credential_patterns(secrets)

    text = f"creds: {secrets[0]}, {secrets[1]}, {secrets[2]}"
    result = corvus.sanitize.sanitize(text)

    for secret in secrets:
        assert secret not in result, f"Secret {secret!r} was NOT redacted"
    assert result.count("[REDACTED]") == 3


# ---------------------------------------------------------------------------
# 3. Short values are skipped (< 8 chars)
# ---------------------------------------------------------------------------


def test_short_values_skipped():
    """Values shorter than 8 characters must NOT be registered for redaction."""
    short = "abc1234"  # 7 chars — below the threshold
    long_enough = "abcdefgh"  # 8 chars — should be registered

    corvus.sanitize.register_credential_patterns([short, long_enough])

    text_with_short = f"has {short} inside"
    text_with_long = f"has {long_enough} inside"

    # Short value must survive (not redacted).
    assert short in corvus.sanitize.sanitize(text_with_short)
    # Long-enough value must be redacted.
    assert long_enough not in corvus.sanitize.sanitize(text_with_long)


# ---------------------------------------------------------------------------
# 4. Empty list is a no-op
# ---------------------------------------------------------------------------


def test_empty_list_is_noop():
    """Passing an empty list must not raise or add patterns."""
    corvus.sanitize.register_credential_patterns([])

    # Module-level patterns should still be just the original set.
    original_count = len(corvus.sanitize._CREDENTIAL_PATTERNS)
    # The original module ships 6 patterns; confirm nothing was added.
    assert original_count == 6

    # sanitize still works normally.
    assert corvus.sanitize.sanitize("hello world") == "hello world"


# ---------------------------------------------------------------------------
# 5. Regex special characters are properly escaped
# ---------------------------------------------------------------------------


def test_regex_special_chars_escaped():
    """Values containing regex metacharacters must be escaped and matched literally."""
    tricky = "my+secret[0].value{1}"  # contains +, [, ], ., {, }
    corvus.sanitize.register_credential_patterns([tricky])

    result = corvus.sanitize.sanitize(f"config={tricky} done")
    assert tricky not in result
    assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# 6. Existing generic patterns still work after registration
# ---------------------------------------------------------------------------


def test_existing_patterns_still_work():
    """Built-in Bearer/Authorization patterns must survive dynamic registration."""
    corvus.sanitize.register_credential_patterns(["extra-secret-value-999"])

    bearer_text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    result = corvus.sanitize.sanitize(bearer_text)

    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    assert "[REDACTED]" in result
