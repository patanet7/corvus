"""Integration smoke tests wiring ALL TUI components together.

Verifies that TuiApp correctly composes parser, command router, agent stack,
event handler, renderer, and protocol events into a working system.
"""

import asyncio
import io

from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import InputTier
from corvus.tui.core.agent_stack import AgentStatus
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.protocol.events import RunOutputChunk, RunStart, parse_event
from corvus.tui.theme import TuiTheme


class TestFullWiring:
    """Wire ALL components through TuiApp and verify end-to-end data flow."""

    def test_parse_help_command(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/help")

        assert parsed.kind == "command"
        assert parsed.command == "help"

    def test_classify_help_as_system(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/help")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SYSTEM

    def test_push_agent_and_verify_current(self) -> None:
        app = TuiApp()
        app.agent_stack.push("work", session_id="sess-001")

        assert app.agent_stack.current.agent_name == "work"
        assert app.agent_stack.depth == 1

    def test_parse_run_output_chunk_event(self) -> None:
        raw = {
            "type": "run_output_chunk",
            "run_id": "r-42",
            "agent": "homelab",
            "content": "nginx is up",
            "final": False,
            "dispatch_id": "d-1",
            "session_id": "s-1",
            "turn_id": "t-1",
        }
        event = parse_event(raw)

        assert isinstance(event, RunOutputChunk)
        assert event.run_id == "r-42"
        assert event.agent == "homelab"
        assert event.content == "nginx is up"
        assert event.final is False

    def test_full_pipeline(self) -> None:
        """End-to-end: parse, classify, push agent, parse event in one flow."""
        app = TuiApp()

        # Parse and classify a command
        parsed = app.parser.parse("/help")
        tier = app.command_router.classify(parsed)
        assert tier is InputTier.SYSTEM

        # Push an agent
        app.agent_stack.push("work", session_id="sess-001")
        assert app.agent_stack.current.agent_name == "work"

        # Parse a protocol event
        event = parse_event({
            "type": "run_output_chunk",
            "run_id": "r-99",
            "agent": "work",
            "content": "done",
            "final": True,
        })
        assert isinstance(event, RunOutputChunk)
        assert event.content == "done"
        assert event.final is True


class TestParserWithAgentsFromRegistry:
    """Verify parser recognizes dynamically-added agent names for @mentions."""

    def test_known_agent_mention(self) -> None:
        app = TuiApp()
        app.parser.update_agents(["homelab", "finance", "work"])

        parsed = app.parser.parse("@homelab check nginx")

        assert parsed.kind == "mention"
        assert "homelab" in parsed.mentions
        assert "check nginx" in parsed.text

    def test_unknown_agent_falls_through_to_chat(self) -> None:
        app = TuiApp()
        app.parser.update_agents(["homelab", "finance", "work"])

        parsed = app.parser.parse("@nonexistent hello")

        assert parsed.kind == "chat"

    def test_multiple_known_agents(self) -> None:
        app = TuiApp()
        app.parser.update_agents(["homelab", "finance", "work"])

        parsed = app.parser.parse("@homelab @finance compare budgets")

        assert parsed.kind == "mention"
        assert "homelab" in parsed.mentions
        assert "finance" in parsed.mentions


class TestEventHandlerUpdatesAgentStatus:
    """Verify that handling a RunStart event updates agent status to THINKING."""

    def test_run_start_sets_thinking(self) -> None:
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=120)
        theme = TuiTheme()
        renderer = ChatRenderer(console, theme)

        app = TuiApp()
        # Replace renderer and event handler to capture output
        app.renderer = renderer
        app.event_handler = EventHandler(renderer, app.agent_stack)

        # Push an agent so find() can locate it
        app.agent_stack.push("homelab", session_id="sess-h1")
        assert app.agent_stack.current.status is AgentStatus.IDLE

        # Create and handle a RunStart event
        event = parse_event({
            "type": "run_start",
            "run_id": "r-10",
            "agent": "homelab",
            "dispatch_id": "d-1",
            "session_id": "s-1",
            "turn_id": "t-1",
            "task_id": "task-1",
        })
        assert isinstance(event, RunStart)

        asyncio.run(app.event_handler.handle(event))

        assert app.agent_stack.current.status is AgentStatus.THINKING

        # Verify renderer produced output
        output = buf.getvalue()
        assert "homelab" in output
        assert "thinking" in output


class TestCommandRouterEndToEnd:
    """Classify various inputs through parser then router, verify tiers."""

    def test_help_routes_to_system(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/help")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SYSTEM

    def test_memory_routes_to_service(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/memory search corvus")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SERVICE

    def test_plain_text_routes_to_agent(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("what is the weather?")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.AGENT

    def test_mention_routes_to_agent(self) -> None:
        app = TuiApp()
        app.parser.update_agents(["homelab"])
        parsed = app.parser.parse("@homelab status")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.AGENT

    def test_unknown_command_routes_to_agent(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/nosuchcommand")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.AGENT

    def test_quit_routes_to_system(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/quit")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SYSTEM

    def test_tools_routes_to_service(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/tools")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SERVICE

    def test_back_routes_to_agent_tier(self) -> None:
        app = TuiApp()
        parsed = app.parser.parse("/back")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.AGENT
