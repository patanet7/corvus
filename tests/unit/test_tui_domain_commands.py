"""Behavioral tests for AgentCommandHandler (agent-tier slash commands).

NO MOCKS — uses real AgentStack, real ChatRenderer with StringIO Console capture.
"""

import asyncio
from io import StringIO

import pytest
from rich.console import Console

from corvus.tui.commands.domain import AgentCommandHandler
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.input.parser import ParsedInput
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.theme import TuiTheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_renderer() -> tuple[ChatRenderer, StringIO]:
    """Create a ChatRenderer backed by a StringIO buffer for capture."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console, theme)
    return renderer, buf


def _make_parsed(command: str, command_args: str | None = None) -> ParsedInput:
    """Build a minimal ParsedInput for a slash command."""
    raw = f"/{command}" + (f" {command_args}" if command_args else "")
    return ParsedInput(
        raw=raw,
        kind="command",
        text=raw,
        command=command,
        command_args=command_args,
    )


def _captured(buf: StringIO) -> str:
    """Return all text written to the StringIO buffer."""
    return buf.getvalue()


# ---------------------------------------------------------------------------
# /back
# ---------------------------------------------------------------------------


class TestBack:
    """Tests for /back command."""

    def test_back_pops_to_parent(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.push("work", session_id="s2")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("back")))

        assert result is True
        assert stack.depth == 1
        assert stack.current.agent_name == "huginn"
        output = _captured(buf)
        assert "Left @work" in output

    def test_back_at_root_shows_error(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("back")))

        assert result is True
        assert stack.depth == 1  # unchanged
        output = _captured(buf)
        assert "Already at root agent" in output

    def test_back_empty_stack_shows_error(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("back")))

        assert result is True
        output = _captured(buf)
        assert "Already at root agent" in output


# ---------------------------------------------------------------------------
# /top
# ---------------------------------------------------------------------------


class TestTop:
    """Tests for /top command."""

    def test_top_returns_to_root(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.push("work", session_id="s2")
        stack.push("codex", session_id="s3")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("top")))

        assert result is True
        assert stack.depth == 1
        assert stack.current.agent_name == "huginn"
        output = _captured(buf)
        assert "Returned to @huginn" in output

    def test_top_already_at_root(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("top")))

        assert result is True
        assert stack.depth == 1
        output = _captured(buf)
        assert "Returned to @huginn" in output

    def test_top_empty_stack_shows_error(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("top")))

        assert result is True
        output = _captured(buf)
        assert "Agent stack is empty" in output


# ---------------------------------------------------------------------------
# /enter
# ---------------------------------------------------------------------------


class TestEnter:
    """Tests for /enter command."""

    def test_enter_existing_child(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.spawn("work", session_id="s2")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("enter", "work")))

        assert result is True
        assert stack.depth == 2
        assert stack.current.agent_name == "work"
        output = _captured(buf)
        assert "Entered @work" in output

    def test_enter_no_args_shows_usage(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("enter")))

        assert result is True
        output = _captured(buf)
        assert "Usage: /enter <agent>" in output

    def test_enter_unknown_child_shows_error(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("enter", "nonexistent")))

        assert result is True
        output = _captured(buf)
        assert "No child agent named 'nonexistent'" in output

    def test_enter_strips_whitespace(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.spawn("work", session_id="s2")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("enter", "  work  ")))

        assert result is True
        assert stack.current.agent_name == "work"


# ---------------------------------------------------------------------------
# /spawn
# ---------------------------------------------------------------------------


class TestSpawn:
    """Tests for /spawn command."""

    def test_spawn_adds_background_child(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("spawn", "research")))

        assert result is True
        # Stack depth unchanged — spawn does not push
        assert stack.depth == 1
        assert stack.current.agent_name == "huginn"
        # Child was added
        children = stack.current.children
        assert len(children) == 1
        assert children[0].agent_name == "research"
        output = _captured(buf)
        assert "Spawned @research" in output
        assert "@huginn" in output

    def test_spawn_no_args_shows_usage(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("spawn")))

        assert result is True
        output = _captured(buf)
        assert "Usage: /spawn <agent>" in output


# ---------------------------------------------------------------------------
# /summon
# ---------------------------------------------------------------------------


class TestSummon:
    """Tests for /summon command."""

    def test_summon_spawns_coworker(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("summon", "finance")))

        assert result is True
        # Summon spawns a child but does not enter it
        assert stack.depth == 1
        children = stack.current.children
        assert len(children) == 1
        assert children[0].agent_name == "finance"
        output = _captured(buf)
        assert "Summoned @finance" in output
        assert "coworker" in output
        assert "@huginn" in output

    def test_summon_no_args_shows_usage(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("summon")))

        assert result is True
        output = _captured(buf)
        assert "Usage: /summon <agent>" in output

    def test_summon_strips_whitespace(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("summon", "  finance  ")))

        assert result is True
        assert stack.current.children[0].agent_name == "finance"


# ---------------------------------------------------------------------------
# /kill
# ---------------------------------------------------------------------------


class TestKill:
    """Tests for /kill command."""

    def test_kill_removes_child(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.spawn("worker", session_id="s2")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        assert len(stack.current.children) == 1

        result = asyncio.run(handler.handle(_make_parsed("kill", "worker")))

        assert result is True
        assert len(stack.current.children) == 0
        output = _captured(buf)
        assert "Killed @worker" in output

    def test_kill_no_args_shows_usage(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("kill")))

        assert result is True
        output = _captured(buf)
        assert "Usage: /kill <agent>" in output

    def test_kill_unknown_child_shows_error(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("kill", "ghost")))

        assert result is True
        output = _captured(buf)
        assert "No child agent named 'ghost'" in output

    def test_kill_strips_whitespace(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        stack.spawn("worker", session_id="s2")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("kill", "  worker  ")))

        assert result is True
        assert len(stack.current.children) == 0


# ---------------------------------------------------------------------------
# Unrecognized commands return False
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    """Verify handler returns False for commands it does not own."""

    def test_unknown_command_returns_false(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        result = asyncio.run(handler.handle(_make_parsed("help")))
        assert result is False

    def test_none_command_returns_false(self) -> None:
        renderer, buf = _make_renderer()
        stack = AgentStack()
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        parsed = ParsedInput(raw="hello", kind="chat", text="hello", command=None)
        result = asyncio.run(handler.handle(parsed))
        assert result is False


# ---------------------------------------------------------------------------
# Integration: multi-step navigation
# ---------------------------------------------------------------------------


class TestNavigation:
    """Integration-style tests exercising multiple commands in sequence."""

    def test_spawn_enter_back_kill(self) -> None:
        """Spawn a child, enter it, go back, then kill it."""
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        # Spawn
        asyncio.run(handler.handle(_make_parsed("spawn", "work")))
        assert stack.depth == 1
        assert len(stack.current.children) == 1

        # Enter
        asyncio.run(handler.handle(_make_parsed("enter", "work")))
        assert stack.depth == 2
        assert stack.current.agent_name == "work"

        # Back
        asyncio.run(handler.handle(_make_parsed("back")))
        assert stack.depth == 1
        assert stack.current.agent_name == "huginn"

        # Kill
        asyncio.run(handler.handle(_make_parsed("kill", "work")))
        assert len(stack.current.children) == 0

    def test_deep_navigation_with_top(self) -> None:
        """Push several levels deep, then /top to root."""
        renderer, buf = _make_renderer()
        stack = AgentStack()
        stack.push("huginn", session_id="s1")
        handler = AgentCommandHandler(renderer=renderer, agent_stack=stack)

        # Build a chain: huginn -> work -> codex
        asyncio.run(handler.handle(_make_parsed("spawn", "work")))
        asyncio.run(handler.handle(_make_parsed("enter", "work")))
        asyncio.run(handler.handle(_make_parsed("spawn", "codex")))
        asyncio.run(handler.handle(_make_parsed("enter", "codex")))

        assert stack.depth == 3
        assert stack.current.agent_name == "codex"

        # /top returns to huginn
        asyncio.run(handler.handle(_make_parsed("top")))
        assert stack.depth == 1
        assert stack.current.agent_name == "huginn"
