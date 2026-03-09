"""Behavioral tests for corvus.security.sanitizer.

Verifies that credential patterns are redacted from tool results while
non-sensitive text passes through unchanged.
"""

from __future__ import annotations

import time

from corvus.security.sanitizer import SANITIZER_PATTERNS, sanitize_tool_result


# ── helpers ──────────────────────────────────────────────────────────────────


def _assert_redacted(raw: str, *, must_not_contain: str | None = None) -> str:
    """Sanitize *raw*, assert something was redacted, return result."""
    result = sanitize_tool_result(raw)
    assert result != raw, f"Expected redaction but got unchanged output: {result!r}"
    if must_not_contain:
        assert must_not_contain not in result, (
            f"Sensitive value still present: {must_not_contain!r}"
        )
    return result


# ── 1. API key patterns ─────────────────────────────────────────────────────


class TestAPIKeyRedaction:
    def test_sk_prefix_key(self) -> None:
        raw = "Using key sk-abc123def456ghi789jklmnopqrstuv for auth"
        result = _assert_redacted(raw, must_not_contain="sk-abc123")
        assert "[REDACTED" in result

    def test_pk_prefix_key(self) -> None:
        raw = "pk_live_abcdefghij1234567890 is active"
        result = _assert_redacted(raw, must_not_contain="pk_live_abcdefghij")
        assert "[REDACTED" in result

    def test_rk_prefix_key(self) -> None:
        raw = "rk_test_ABCDEFGHIJKLMNOPQRSTU"
        result = _assert_redacted(raw, must_not_contain="rk_test_ABCDEFG")
        assert "[REDACTED" in result

    def test_key_dash_prefix(self) -> None:
        raw = "key-abcdefghijklmnopqrstuvwxyz"
        result = _assert_redacted(raw, must_not_contain="key-abcdefgh")
        assert "[REDACTED" in result

    def test_aws_access_key(self) -> None:
        raw = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = _assert_redacted(raw, must_not_contain="AKIAIOSFODNN7EXAMPLE")
        assert "[REDACTED" in result


# ── 2. Bearer tokens ────────────────────────────────────────────────────────


class TestBearerTokenRedaction:
    def test_bearer_token_in_header(self) -> None:
        raw = "Authorization: Bearer eytoken1234abcdef"
        result = _assert_redacted(raw, must_not_contain="eytoken1234")
        assert "[REDACTED]" in result

    def test_standalone_bearer(self) -> None:
        raw = "Token is Bearer mySuperSecretTokenValue1234"
        result = _assert_redacted(raw, must_not_contain="mySuperSecret")
        assert "[REDACTED]" in result

    def test_authorization_basic(self) -> None:
        raw = "Authorization: Basic dXNlcjpwYXNz"
        result = _assert_redacted(raw, must_not_contain="dXNlcjpwYXNz")
        assert "[REDACTED]" in result


# ── 3. Connection strings ───────────────────────────────────────────────────


class TestConnectionStringRedaction:
    def test_postgres_dsn(self) -> None:
        raw = "postgresql://admin:s3cretP4ss@db.example.com:5432/mydb"
        result = _assert_redacted(raw, must_not_contain="s3cretP4ss")
        assert "://admin:[REDACTED]@" in result

    def test_redis_url(self) -> None:
        raw = "redis://default:hunter2@redis.internal:6379"
        result = _assert_redacted(raw, must_not_contain="hunter2")
        assert "://default:[REDACTED]@" in result

    def test_mongodb_url(self) -> None:
        raw = "mongodb://root:MyP%40ssw0rd@mongo:27017/admin"
        result = _assert_redacted(raw, must_not_contain="MyP%40ssw0rd")
        assert "[REDACTED]@" in result


# ── 4. Key=value credential pairs ───────────────────────────────────────────


class TestKeyValueRedaction:
    def test_api_key_equals(self) -> None:
        raw = "api_key=abcdef123456"
        result = _assert_redacted(raw, must_not_contain="abcdef123456")
        assert "api_key=[REDACTED]" in result

    def test_token_colon(self) -> None:
        raw = "token: my-secret-token-value"
        result = _assert_redacted(raw, must_not_contain="my-secret-token-value")
        assert "token: [REDACTED]" in result

    def test_password_equals(self) -> None:
        raw = 'password="hunter2hunter2"'
        result = _assert_redacted(raw, must_not_contain="hunter2hunter2")
        assert "password=" in result
        assert "[REDACTED]" in result

    def test_secret_key(self) -> None:
        raw = "secret_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = _assert_redacted(raw, must_not_contain="wJalrXUtnFEMI")
        assert "[REDACTED]" in result

    def test_client_secret(self) -> None:
        raw = "client_secret=a1b2c3d4e5f6g7h8"
        result = _assert_redacted(raw, must_not_contain="a1b2c3d4e5f6g7h8")
        assert "[REDACTED]" in result

    def test_case_insensitive(self) -> None:
        raw = "API_KEY=SomeSecretValue1234"
        result = _assert_redacted(raw, must_not_contain="SomeSecretValue1234")
        assert "[REDACTED]" in result


# ── 5. JWT tokens ────────────────────────────────────────────────────────────


class TestJWTRedaction:
    def test_standard_jwt(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        raw = f"Token: {jwt}"
        result = _assert_redacted(raw, must_not_contain="eyJhbGciOiJIUzI1NiI")
        assert "[REDACTED_JWT]" in result

    def test_jwt_in_context(self) -> None:
        jwt = (
            "eyJhbGciOiJSUzI1NiJ9."
            "eyJpc3MiOiJjb3J2dXMifQ."
            "abc123def456ghi789"
        )
        raw = f"The access token is {jwt} and it expires soon."
        result = _assert_redacted(raw, must_not_contain=jwt)
        assert "The access token is" in result
        assert "expires soon" in result


# ── 6. Non-sensitive text passes through ─────────────────────────────────────


class TestNonSensitivePassthrough:
    def test_plain_text(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        assert sanitize_tool_result(text) == text

    def test_code_snippet(self) -> None:
        text = "def hello():\n    return 'world'\n"
        assert sanitize_tool_result(text) == text

    def test_json_without_secrets(self) -> None:
        text = '{"name": "corvus", "version": "1.0", "count": 42}'
        assert sanitize_tool_result(text) == text

    def test_git_sha_40_chars_passthrough(self) -> None:
        # 40-char hex = git SHA, should NOT be redacted
        sha = "a" * 40
        text = f"commit {sha}"
        assert sanitize_tool_result(text) == text

    def test_url_without_credentials(self) -> None:
        text = "https://example.com/api/v1/resource?page=1"
        assert sanitize_tool_result(text) == text

    def test_short_hex_passthrough(self) -> None:
        text = "Error code: 0xDEADBEEF"
        assert sanitize_tool_result(text) == text

    def test_numeric_ids_passthrough(self) -> None:
        text = "User ID: 1234567890, Session: 9876543210"
        assert sanitize_tool_result(text) == text


# ── 7. Mixed content ────────────────────────────────────────────────────────


class TestMixedContent:
    def test_sensitive_and_safe_parts(self) -> None:
        raw = (
            "Connected to database. "
            "DSN: postgresql://app:SuperSecret@db:5432/prod. "
            "Fetched 42 rows in 12ms."
        )
        result = sanitize_tool_result(raw)
        assert "SuperSecret" not in result
        assert "Connected to database" in result
        assert "Fetched 42 rows in 12ms" in result

    def test_multiple_credentials_in_one_string(self) -> None:
        raw = (
            "api_key=secret123456 "
            "token=anothersecretvalue "
            "password=hunter2abc"
        )
        result = sanitize_tool_result(raw)
        assert "secret123456" not in result
        assert "anothersecretvalue" not in result
        assert "hunter2abc" not in result

    def test_aws_key_with_surrounding_config(self) -> None:
        raw = (
            "[default]\n"
            "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"
            "region = us-east-1\n"
        )
        result = sanitize_tool_result(raw)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "region = us-east-1" in result


# ── 8. Idempotency ──────────────────────────────────────────────────────────


class TestIdempotency:
    def test_double_sanitize_api_key(self) -> None:
        raw = "sk-abcdefghijklmnopqrstuvwxyz1234"
        once = sanitize_tool_result(raw)
        twice = sanitize_tool_result(once)
        assert once == twice

    def test_double_sanitize_connection_string(self) -> None:
        raw = "postgresql://admin:s3cret@db:5432/app"
        once = sanitize_tool_result(raw)
        twice = sanitize_tool_result(once)
        assert once == twice

    def test_double_sanitize_bearer(self) -> None:
        raw = "Authorization: Bearer abc123longtoken"
        once = sanitize_tool_result(raw)
        twice = sanitize_tool_result(once)
        assert once == twice

    def test_double_sanitize_jwt(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        once = sanitize_tool_result(jwt)
        twice = sanitize_tool_result(once)
        assert once == twice

    def test_double_sanitize_mixed(self) -> None:
        raw = "api_key=mysecret Bearer tokenvalue123456789012"
        once = sanitize_tool_result(raw)
        twice = sanitize_tool_result(once)
        assert once == twice


# ── 9. Empty / edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert sanitize_tool_result("") == ""

    def test_whitespace_only(self) -> None:
        assert sanitize_tool_result("   \n\t  ") == "   \n\t  "

    def test_single_word(self) -> None:
        assert sanitize_tool_result("hello") == "hello"

    def test_patterns_list_is_populated(self) -> None:
        assert len(SANITIZER_PATTERNS) > 0
        for pat, repl in SANITIZER_PATTERNS:
            assert isinstance(pat, type(re.compile("")))
            assert isinstance(repl, str)


# ── 10. Performance — no catastrophic backtracking ───────────────────────────


class TestPerformance:
    def test_long_string_no_credentials(self) -> None:
        text = "A" * 100_000
        start = time.monotonic()
        result = sanitize_tool_result(text)
        elapsed = time.monotonic() - start
        assert result == text
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — possible catastrophic backtracking"

    def test_long_string_with_many_credentials(self) -> None:
        lines = [f"api_key=secret{i:06d}" for i in range(1000)]
        text = "\n".join(lines)
        start = time.monotonic()
        result = sanitize_tool_result(text)
        elapsed = time.monotonic() - start
        assert "secret000000" not in result
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — possible catastrophic backtracking"

    def test_adversarial_hex_string(self) -> None:
        # Long hex that could cause backtracking in naive patterns
        text = "ab" * 5000
        start = time.monotonic()
        sanitize_tool_result(text)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — possible catastrophic backtracking"

    def test_repeated_key_value_pattern(self) -> None:
        text = "&".join(f"param{i}=value{i}" for i in range(5000))
        start = time.monotonic()
        sanitize_tool_result(text)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Took {elapsed:.2f}s — possible catastrophic backtracking"


# ── Long hex tokens ──────────────────────────────────────────────────────────


class TestHexTokenRedaction:
    def test_64_char_hex_redacted(self) -> None:
        token = "a1b2c3d4" * 8  # 64 chars
        raw = f"ghp_{token}"
        result = sanitize_tool_result(raw)
        assert token not in result

    def test_40_char_hex_not_redacted(self) -> None:
        sha = "a1b2c3d4e5" * 4  # 40 chars
        raw = f"commit {sha}"
        assert sanitize_tool_result(raw) == raw
