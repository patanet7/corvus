"""Behavioral tests for _build_subprocess_env() allowlist (F-001).

Verifies that the CLI subprocess environment builder only passes
explicitly allowlisted vars and never leaks credentials.
"""

import os

from corvus.cli.chat import _ALLOWED_ENV, _build_subprocess_env

# Credentials that must NEVER appear in subprocess environment.
_SENSITIVE_TEST_VARS = [
    "HA_TOKEN",
    "PAPERLESS_API_TOKEN",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "SMTP_PASSWORD",
]


class TestBuildSubprocessEnv:
    """Exercise _build_subprocess_env with real os.environ mutations."""

    def setup_method(self) -> None:
        """Inject known sensitive vars into os.environ for each test."""
        self._originals: dict[str, str | None] = {}
        for var in _SENSITIVE_TEST_VARS:
            self._originals[var] = os.environ.get(var)
            os.environ[var] = f"test-secret-{var}"

    def teardown_method(self) -> None:
        """Restore original os.environ state."""
        for var, original in self._originals.items():
            if original is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = original

    def test_sensitive_vars_excluded(self) -> None:
        """No credential var should appear in the subprocess env."""
        env = _build_subprocess_env()
        for var in _SENSITIVE_TEST_VARS:
            assert var not in env, f"{var} leaked into subprocess env"

    def test_allowed_vars_present(self) -> None:
        """PATH, HOME, SHELL should be forwarded when set."""
        env = _build_subprocess_env()
        for var in ("PATH", "HOME", "SHELL"):
            if os.environ.get(var) is not None:
                assert var in env
                assert env[var] == os.environ[var]

    def test_tmpdir_included_when_set(self) -> None:
        """TMPDIR should be forwarded when present in os.environ."""
        original = os.environ.get("TMPDIR")
        try:
            os.environ["TMPDIR"] = "/tmp/corvus-test"
            env = _build_subprocess_env()
            assert env.get("TMPDIR") == "/tmp/corvus-test"
        finally:
            if original is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = original

    def test_tmpdir_absent_when_unset(self) -> None:
        """TMPDIR should not appear if not set in os.environ."""
        original = os.environ.get("TMPDIR")
        try:
            os.environ.pop("TMPDIR", None)
            env = _build_subprocess_env()
            assert "TMPDIR" not in env
        finally:
            if original is not None:
                os.environ["TMPDIR"] = original

    def test_extra_vars_included(self) -> None:
        """Extra vars passed explicitly should appear in the result."""
        env = _build_subprocess_env(extra={
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
            "CLAUDE_CONFIG_DIR": "/tmp/isolated/.claude",
        })
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000"
        assert env["CLAUDE_CONFIG_DIR"] == "/tmp/isolated/.claude"

    def test_extra_overrides_allowed(self) -> None:
        """Extra vars should override allowlisted values (e.g. HOME)."""
        env = _build_subprocess_env(extra={"HOME": "/tmp/agent-home"})
        assert env["HOME"] == "/tmp/agent-home"

    def test_only_allowlisted_keys_from_parent(self) -> None:
        """Every key sourced from os.environ must be in _ALLOWED_ENV."""
        env = _build_subprocess_env()
        for key in env:
            assert key in _ALLOWED_ENV, (
                f"{key} was sourced from os.environ but is not in _ALLOWED_ENV"
            )

    def test_no_extra_means_no_bonus_keys(self) -> None:
        """Without extra, result keys are a subset of _ALLOWED_ENV."""
        env = _build_subprocess_env()
        assert set(env.keys()).issubset(_ALLOWED_ENV)

    def test_allowed_env_is_frozen(self) -> None:
        """_ALLOWED_ENV should be a frozenset (immutable)."""
        assert isinstance(_ALLOWED_ENV, frozenset)
