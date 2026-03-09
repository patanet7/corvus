"""Behavioral tests for TUI tool result sanitization.

Verifies that tool results pass through the real sanitize_tool_result()
before display, scrubbing API keys, Bearer tokens, AWS keys, connection
strings, JWTs, and hex secrets.  Uses a real Rich Console writing to
io.StringIO -- no mocks.
"""

import io

import pytest
from rich.console import Console

from corvus.security.sanitizer import sanitize_tool_result
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.output.token_counter import TokenCounter
from corvus.tui.protocol.events import parse_event
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_renderer() -> tuple[ChatRenderer, io.StringIO]:
    """Build a ChatRenderer backed by a string buffer for assertions."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    return renderer, buf


def _make_handler() -> tuple[EventHandler, AgentStack, io.StringIO, TokenCounter]:
    """Build an EventHandler wired to a real renderer writing to a StringIO buffer."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    stack = AgentStack()
    counter = TokenCounter()
    handler = EventHandler(renderer, stack, counter)
    return handler, stack, buf, counter


def _output(buf: io.StringIO) -> str:
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# ===========================================================================
# 1. Renderer sanitizes tool results directly
# ===========================================================================

class TestRendererSanitizesToolResult:
    """render_tool_result must scrub credential patterns before display."""

    def test_api_key_redacted(self) -> None:
        """Prefixed API keys (sk-...) must be redacted."""
        renderer, buf = _make_renderer()
        secret = "sk-abcdefghij1234567890longapikey"
        renderer.render_tool_result("my_tool", f"key is {secret}", agent="work")
        output = _output(buf)

        assert secret not in output
        assert "REDACTED" in output

    def test_bearer_token_redacted(self) -> None:
        """Bearer tokens must be redacted."""
        renderer, buf = _make_renderer()
        token = "Bearer eyJhbGciOiJIUzI1NiJ9.longtoken.signature"
        renderer.render_tool_result("auth_tool", f"Authorization: {token}", agent="work")
        output = _output(buf)

        assert "eyJhbGciOiJIUzI1NiJ9" not in output
        assert "REDACTED" in output

    def test_aws_key_redacted(self) -> None:
        """AWS access key IDs (AKIA...) must be redacted."""
        renderer, buf = _make_renderer()
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        renderer.render_tool_result("aws_tool", f"AWS key: {aws_key}", agent="work")
        output = _output(buf)

        assert aws_key not in output
        assert "REDACTED" in output

    def test_connection_string_password_redacted(self) -> None:
        """Connection string passwords (://user:pass@host) must be redacted."""
        renderer, buf = _make_renderer()
        conn = "postgres://admin:supersecretpassword@db.example.com:5432/mydb"
        renderer.render_tool_result("db_tool", f"DSN: {conn}", agent="finance")
        output = _output(buf)

        assert "supersecretpassword" not in output
        assert "REDACTED" in output

    def test_jwt_token_redacted(self) -> None:
        """JWT tokens (eyJ...eyJ...sig) must be redacted."""
        renderer, buf = _make_renderer()
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        renderer.render_tool_result("jwt_tool", f"token={jwt}", agent="work")
        output = _output(buf)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in output
        assert "REDACTED" in output

    def test_hex_secret_redacted(self) -> None:
        """Long hex strings (64+ chars with mixed digits/letters) must be redacted."""
        renderer, buf = _make_renderer()
        hex_secret = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        renderer.render_tool_result("hex_tool", f"hash: {hex_secret}", agent="work")
        output = _output(buf)

        assert hex_secret not in output
        assert "REDACTED" in output

    def test_safe_content_preserved(self) -> None:
        """Non-sensitive content passes through unchanged."""
        renderer, buf = _make_renderer()
        safe = "Found 3 files matching *.py in /home/user/project"
        renderer.render_tool_result("search_tool", safe, agent="work")
        output = _output(buf)

        assert "Found 3 files" in output
        assert "*.py" in output

    def test_mixed_content_redacts_only_secrets(self) -> None:
        """In mixed content, only the secret parts are redacted."""
        renderer, buf = _make_renderer()
        text = "Status: OK, key=sk-abcdefghij1234567890longapikey, count=42"
        renderer.render_tool_result("mixed_tool", text, agent="work")
        output = _output(buf)

        assert "Status: OK" in output
        assert "count=42" in output
        assert "sk-abcdefghij1234567890longapikey" not in output


# ===========================================================================
# 2. EventHandler sanitizes ToolResult events
# ===========================================================================

class TestEventHandlerSanitizesToolResult:
    """EventHandler must sanitize ToolResult.output before passing to renderer."""

    @pytest.mark.asyncio
    async def test_api_key_sanitized_through_event_handler(self) -> None:
        """An API key in a ToolResult event must be redacted in rendered output."""
        handler, stack, buf, _ = _make_handler()

        await handler.handle(parse_event({
            "type": "tool_start",
            "tool": "config_reader",
            "call_id": "call-san-1",
            "params": {},
        }))
        _output(buf)  # clear tool_start output

        secret = "sk-abcdefghij1234567890longapikey"
        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "call-san-1",
            "output": f"api_key={secret}",
            "status": "success",
        }))
        result_output = _output(buf)

        assert secret not in result_output
        assert "REDACTED" in result_output

    @pytest.mark.asyncio
    async def test_bearer_token_sanitized_through_event_handler(self) -> None:
        """A Bearer token in a ToolResult event must be redacted."""
        handler, stack, buf, _ = _make_handler()

        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "call-san-2",
            "output": "Authorization: Bearer supersecrettoken12345678",
            "status": "success",
        }))
        result_output = _output(buf)

        assert "supersecrettoken12345678" not in result_output
        assert "REDACTED" in result_output

    @pytest.mark.asyncio
    async def test_connection_string_sanitized_through_event_handler(self) -> None:
        """Connection string passwords in ToolResult events must be redacted."""
        handler, stack, buf, _ = _make_handler()

        conn = "mysql://root:p4ssw0rd@localhost:3306/app"
        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "call-san-3",
            "output": f"Connected to {conn}",
            "status": "success",
        }))
        result_output = _output(buf)

        assert "p4ssw0rd" not in result_output
        assert "REDACTED" in result_output

    @pytest.mark.asyncio
    async def test_safe_output_preserved_through_event_handler(self) -> None:
        """Non-sensitive ToolResult output passes through unchanged."""
        handler, stack, buf, _ = _make_handler()

        await handler.handle(parse_event({
            "type": "tool_result",
            "call_id": "call-san-4",
            "output": "Deployed 3 containers successfully",
            "status": "success",
        }))
        result_output = _output(buf)

        assert "Deployed 3 containers successfully" in result_output


# ===========================================================================
# 3. Sanitizer is the REAL one (not reimplemented)
# ===========================================================================

class TestSanitizerIntegration:
    """Verify the sanitizer function works as expected for our test cases."""

    def test_sanitizer_redacts_api_key(self) -> None:
        result = sanitize_tool_result("key=sk-abcdefghij1234567890longapikey")
        assert "sk-abcdefghij1234567890longapikey" not in result
        assert "REDACTED" in result

    def test_sanitizer_redacts_aws_key(self) -> None:
        result = sanitize_tool_result("AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_sanitizer_preserves_safe_text(self) -> None:
        safe = "Hello world, 42 results found"
        assert sanitize_tool_result(safe) == safe

    def test_sanitizer_idempotent(self) -> None:
        text = "key=sk-abcdefghij1234567890longapikey"
        once = sanitize_tool_result(text)
        twice = sanitize_tool_result(once)
        assert once == twice
