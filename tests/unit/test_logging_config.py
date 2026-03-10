"""Behavioral tests for corvus.logging configuration module.

NO mocks, NO monkeypatch for mocking, NO @patch, NO unittest.mock.
All tests exercise real structlog configuration and verify observable output.
"""

from __future__ import annotations

import io
import os
import sys

import pytest
import structlog

from corvus.logging import COMPONENT_LEVEL_MAP
from corvus.logging import configure_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_structlog_json(logger_name: str, level: str, **kw: str) -> str:
    """Configure structlog in JSON mode, emit one event, return captured text."""
    buf = io.StringIO()
    # Temporarily replace stderr to capture output.
    old_stderr = sys.stderr
    sys.stderr = buf
    try:
        # Force reconfiguration.
        structlog.reset_defaults()
        configure_logging(log_format="json")
        log = structlog.get_logger(logger_name)
        getattr(log, level)("test_event", **kw)
    finally:
        sys.stderr = old_stderr
    return buf.getvalue()


class _EnvOverride:
    """Context manager that sets env vars and restores originals on exit."""

    def __init__(self, **overrides: str) -> None:
        self._overrides = overrides
        self._originals: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self._overrides.items():
            self._originals[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *exc: object) -> None:
        for key in self._overrides:
            original = self._originals[key]
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Verify that configure_logging() sets up a usable structlog pipeline."""

    def test_configure_logging_sets_up_structlog(self) -> None:
        """Calling configure_logging() allows structlog.get_logger().info() without error."""
        structlog.reset_defaults()
        # Redirect stderr so the test doesn't pollute output.
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            configure_logging(log_format="console")
            log = structlog.get_logger("corvus.test")
            # Must not raise.
            log.info("hello", key="value")
        finally:
            sys.stderr = old_stderr


class TestComponentLevelMap:
    """Verify the COMPONENT_LEVEL_MAP covers all expected domains."""

    EXPECTED_KEYS = {
        "LOG_LEVEL_ROUTER",
        "LOG_LEVEL_STREAM",
        "LOG_LEVEL_GATEWAY",
        "LOG_LEVEL_TUI",
        "LOG_LEVEL_CLI",
        "LOG_LEVEL_MEMORY",
        "LOG_LEVEL_SECURITY",
        "LOG_LEVEL_ACP",
    }

    def test_component_level_map_has_expected_keys(self) -> None:
        assert set(COMPONENT_LEVEL_MAP.keys()) == self.EXPECTED_KEYS

    def test_component_level_map_values_are_corvus_prefixes(self) -> None:
        for env_var, prefix in COMPONENT_LEVEL_MAP.items():
            assert prefix.startswith("corvus."), (
                f"{env_var} maps to '{prefix}' which does not start with 'corvus.'"
            )


class TestSecretScrubbing:
    """Verify that _scrub_secrets redacts credentials in log output."""

    def test_secret_scrubbing_redacts_api_keys(self) -> None:
        """An sk-ant-... prefixed key must be replaced with [REDACTED_API_KEY]."""
        api_key = "sk-ant-abc123456789012345678901234567890"
        output = _capture_structlog_json("corvus.test", "info", token=api_key)
        assert api_key not in output
        assert "[REDACTED_API_KEY]" in output

    def test_secret_scrubbing_redacts_jwt(self) -> None:
        """A JWT token must be replaced with [REDACTED_JWT]."""
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        output = _capture_structlog_json("corvus.test", "warning", bearer=jwt)
        assert jwt not in output
        assert "[REDACTED_JWT]" in output

    def test_secret_scrubbing_redacts_aws_key(self) -> None:
        """An AKIA... AWS key must be replaced with [REDACTED_AWS_KEY]."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        output = _capture_structlog_json("corvus.test", "info", aws=aws_key)
        assert aws_key not in output
        assert "[REDACTED_AWS_KEY]" in output

    def test_secret_scrubbing_redacts_connection_string_password(self) -> None:
        """Password in a connection string must be redacted."""
        conn = "postgresql://admin:s3cretP4ss@db.example.com:5432/mydb"
        output = _capture_structlog_json("corvus.test", "info", dsn=conn)
        assert "s3cretP4ss" not in output
        assert "[REDACTED]" in output

    def test_secret_scrubbing_walks_all_values(self) -> None:
        """Scrubbing must apply to all string values, not just the event message."""
        api_key = "sk-ant-abc123456789012345678901234567890"
        output = _capture_structlog_json(
            "corvus.test", "info", custom_field=api_key
        )
        assert api_key not in output
        assert "[REDACTED_API_KEY]" in output


class TestPerComponentLevelFiltering:
    """Verify per-component log level overrides suppress or pass events."""

    def test_per_component_level_filtering(self) -> None:
        """With LOG_LEVEL=DEBUG and LOG_LEVEL_ROUTER=ERROR, router INFO is
        suppressed but gateway INFO passes through."""
        with _EnvOverride(LOG_LEVEL="DEBUG", LOG_LEVEL_ROUTER="ERROR"):
            buf = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = buf
            try:
                structlog.reset_defaults()
                configure_logging(log_format="json")

                router_log = structlog.get_logger("corvus.router")
                gateway_log = structlog.get_logger("corvus.gateway")

                router_log.info("router_should_be_suppressed")
                gateway_log.info("gateway_should_appear")
            finally:
                sys.stderr = old_stderr

            output = buf.getvalue()
            assert "router_should_be_suppressed" not in output
            assert "gateway_should_appear" in output

    def test_global_level_suppresses_debug_by_default(self) -> None:
        """With default LOG_LEVEL=INFO, debug events are suppressed."""
        # Ensure LOG_LEVEL is not set (defaults to INFO).
        old = os.environ.pop("LOG_LEVEL", None)
        try:
            buf = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = buf
            try:
                structlog.reset_defaults()
                configure_logging(log_format="json")
                log = structlog.get_logger("corvus.gateway")
                log.debug("should_not_appear")
                log.info("should_appear")
            finally:
                sys.stderr = old_stderr

            output = buf.getvalue()
            assert "should_not_appear" not in output
            assert "should_appear" in output
        finally:
            if old is not None:
                os.environ["LOG_LEVEL"] = old

    def test_component_override_allows_debug(self) -> None:
        """A component override to DEBUG passes debug events even when global is INFO."""
        with _EnvOverride(LOG_LEVEL="INFO", LOG_LEVEL_SECURITY="DEBUG"):
            buf = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = buf
            try:
                structlog.reset_defaults()
                configure_logging(log_format="json")
                log = structlog.get_logger("corvus.security")
                log.debug("security_debug_event")
            finally:
                sys.stderr = old_stderr

            output = buf.getvalue()
            assert "security_debug_event" in output
