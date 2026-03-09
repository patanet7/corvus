"""Behavioral tests for StreamHandler.

NO MOCKS. Real Rich Console with StringIO capture.
"""

from io import StringIO

from rich.console import Console

from corvus.tui.output.stream import StreamHandler
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler() -> tuple[StreamHandler, Console, StringIO]:
    """Build a StreamHandler wired to a real Console writing to StringIO."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80)
    theme = TuiTheme()
    handler = StreamHandler(console, theme)
    return handler, console, buf


def _output(buf: StringIO) -> str:
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


# ---------------------------------------------------------------------------
# Thinking spinner
# ---------------------------------------------------------------------------

class TestThinkingSpinner:
    """StreamHandler thinking spinner lifecycle."""

    def test_render_thinking_start(self) -> None:
        """Starting thinking creates an active Live spinner."""
        handler, console, buf = _make_handler()
        handler.render_thinking_start("homelab")
        assert handler._thinking_live is not None
        # Clean up
        handler.stop_thinking()

    def test_stop_thinking_idempotent(self) -> None:
        """Stopping thinking when not active should not raise."""
        handler, console, buf = _make_handler()
        # Should not error — no thinking active
        handler.stop_thinking()
        assert handler._thinking_live is None

        # Start and stop, then stop again
        handler.render_thinking_start("work")
        handler.stop_thinking()
        handler.stop_thinking()
        assert handler._thinking_live is None


# ---------------------------------------------------------------------------
# Streaming lifecycle
# ---------------------------------------------------------------------------

class TestStreamStart:
    """StreamHandler stream initialization."""

    def test_render_stream_start(self) -> None:
        """Starting a stream creates a Live display and sets agent name."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("finance")
        assert handler._live is not None
        assert handler._stream_agent == "finance"
        assert handler._stream_buffer == []
        # Clean up
        handler._live.stop()
        handler._live = None


class TestStreamChunk:
    """StreamHandler chunk accumulation."""

    def test_render_stream_chunk(self) -> None:
        """Chunks append to the buffer."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("work")
        handler.render_stream_chunk("Hello ")
        handler.render_stream_chunk("world!")
        assert handler._stream_buffer == ["Hello ", "world!"]
        # Clean up
        handler._live.stop()
        handler._live = None


class TestStreamEnd:
    """StreamHandler stream finalization."""

    def test_render_stream_end(self) -> None:
        """Ending a stream renders the final content to console."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("homelab")
        handler.render_stream_chunk("Server is running fine.")
        handler.render_stream_end()
        output = _output(buf)

        assert handler._live is None
        assert "@homelab" in output
        assert "Server is running fine" in output

    def test_render_stream_end_empty_buffer(self) -> None:
        """Ending a stream with empty buffer skips the final agent print."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("docs")
        # No chunks added — buffer is empty
        # Clear the Live panel output from the buffer before calling end
        _output(buf)
        handler.render_stream_end()
        output = _output(buf)

        assert handler._live is None
        # The final console.print (agent header + markdown) should be skipped
        # because the buffer was empty — only Live cleanup sequences remain
        assert "@docs:" not in output

    def test_stream_end_with_token_count(self) -> None:
        """Token count is shown when tokens > 0."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("finance")
        handler.render_stream_chunk("Budget looks good.")
        handler.render_stream_end(tokens=1500)
        output = _output(buf)

        assert "1,500 tokens" in output

    def test_stream_end_no_token_count_when_zero(self) -> None:
        """Token count is not shown when tokens = 0."""
        handler, console, buf = _make_handler()
        handler.render_stream_start("work")
        handler.render_stream_chunk("Some output.")
        handler.render_stream_end(tokens=0)
        output = _output(buf)

        assert "tokens" not in output


class TestFullStreamCycle:
    """End-to-end streaming lifecycle."""

    def test_full_stream_cycle(self) -> None:
        """start -> chunks -> end produces coherent output with agent name and content."""
        handler, console, buf = _make_handler()

        handler.render_stream_start("homelab")
        handler.render_stream_chunk("Docker containers ")
        handler.render_stream_chunk("are healthy. ")
        handler.render_stream_chunk("No alerts.")
        handler.render_stream_end(tokens=250)

        output = _output(buf)

        assert "@homelab" in output
        assert "Docker containers" in output
        assert "healthy" in output
        assert "No alerts" in output
        assert "250 tokens" in output
        assert handler._live is None
        assert handler._stream_buffer == []
        assert handler._stream_agent == ""
