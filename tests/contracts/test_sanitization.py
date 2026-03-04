"""Contract tests for the shared sanitization layer.

NO mocks. Pure function tests exercising real sanitize() and sanitize_path()
against known inputs and expected outputs.
"""

import pytest

from corvus.sanitize import sanitize, sanitize_path


class TestSanitize:
    """Tests for credential redaction via sanitize()."""

    def test_strips_bearer_token(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        result = sanitize(text)
        assert "eyJhbGciOiJ" not in result
        assert "[REDACTED]" in result

    def test_strips_api_key(self) -> None:
        text = 'api_key="sk-abc123def456ghi789jkl012mno"'
        result = sanitize(text)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_strips_token_value(self) -> None:
        text = 'token = "ghp_xyzABCDEFGHIJKLMNOP1234567890ab"'
        result = sanitize(text)
        assert "ghp_xyz" not in result
        assert "[REDACTED]" in result

    def test_strips_cookie_header(self) -> None:
        text = "Cookie: session=abc123; user=admin"
        result = sanitize(text)
        assert "session=abc123" not in result
        assert "[REDACTED]" in result

    def test_strips_set_cookie_header(self) -> None:
        text = "Set-Cookie: token=secret_value; HttpOnly; Secure"
        result = sanitize(text)
        assert "secret_value" not in result
        assert "[REDACTED]" in result

    def test_strips_authorization_header(self) -> None:
        text = "Authorization: Basic dXNlcjpwYXNz"
        result = sanitize(text)
        assert "dXNlcjpwYXNz" not in result
        assert "[REDACTED]" in result

    def test_strips_api_key_with_hyphen(self) -> None:
        text = "api-key: AKIAIOSFODNN7EXAMPLE12345"
        result = sanitize(text)
        assert "AKIAIOSFODNN7" not in result
        assert "[REDACTED]" in result

    def test_preserves_clean_text(self) -> None:
        text = "This is a normal log message with no secrets."
        assert sanitize(text) == text

    def test_preserves_natural_language_with_keyword(self) -> None:
        text = "The user's token was revoked."
        assert sanitize(text) == text

    def test_preserves_short_api_key_value(self) -> None:
        text = 'api_key="short"'
        assert sanitize(text) == text

    def test_handles_empty_string(self) -> None:
        assert sanitize("") == ""

    def test_handles_long_multiline_text(self) -> None:
        lines = ["Normal line"] * 100
        lines[50] = "Bearer eyJhbGciOiJIUzI1NiJ9.longpayload.signature"
        text = "\n".join(lines)
        result = sanitize(text)
        assert "eyJhbGciOiJ" not in result
        assert result.count("[REDACTED]") >= 1
        # The bearer line is replaced entirely, so 99 "Normal line" remain.
        assert result.count("Normal line") == 99

    def test_preserves_unicode(self) -> None:
        text = "Nachricht: Alles gut, keine Geheimnisse hier."
        assert sanitize(text) == text

    def test_multiple_credentials_in_one_string(self) -> None:
        text = 'Authorization: Bearer abc12345678\napi_key="AAAABBBBCCCCDDDDEEEEFFFFGGGG"\nCookie: sid=xyz123'
        result = sanitize(text)
        assert "abc12345678" not in result
        assert "AAAABBBBCCCC" not in result
        assert "sid=xyz123" not in result
        assert result.count("[REDACTED]") >= 3

    def test_case_insensitive_bearer(self) -> None:
        text = "BEARER eyJhbGciOiJIUzI1NiJ9.payload.sig"
        result = sanitize(text)
        assert "eyJhbGciOiJ" not in result
        assert "[REDACTED]" in result

    def test_case_insensitive_api_key(self) -> None:
        text = 'API_KEY="sk-abc123def456ghi789jkl012mno"'
        result = sanitize(text)
        assert "sk-abc123" not in result


class TestSanitizePath:
    """Tests for path traversal protection via sanitize_path()."""

    def test_allows_simple_path(self) -> None:
        assert sanitize_path("notes/daily.md") == "notes/daily.md"

    def test_allows_nested_path(self) -> None:
        assert sanitize_path("vault/notes/2024/jan.md") == "vault/notes/2024/jan.md"

    def test_rejects_parent_traversal(self) -> None:
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("../etc/passwd")

    def test_rejects_sneaky_traversal(self) -> None:
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("notes/../../etc/passwd")

    def test_rejects_absolute_path(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            sanitize_path("/etc/passwd")

    def test_normalizes_dot_segments(self) -> None:
        assert sanitize_path("notes/./daily.md") == "notes/daily.md"

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            sanitize_path("")

    def test_rejects_whitespace_only_path(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            sanitize_path("   ")

    def test_allows_path_with_dots_in_filename(self) -> None:
        assert sanitize_path("notes/my.note.v2.md") == "notes/my.note.v2.md"

    def test_rejects_double_dot_mid_path(self) -> None:
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("a/b/../../../etc/shadow")

    def test_normalizes_trailing_slash(self) -> None:
        result = sanitize_path("notes/daily/")
        assert not result.endswith("/")

    def test_rejects_mid_traversal_via_extra_parents(self) -> None:
        """Traversal via multiple parent references in the middle."""
        with pytest.raises(ValueError, match="traversal"):
            sanitize_path("notes/sub/../../..")
