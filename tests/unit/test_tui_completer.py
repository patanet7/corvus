"""Behavioral tests for ChatCompleter tab completion.

All tests use real CommandRegistry and SlashCommand objects — no mocks.
"""

from __future__ import annotations

from prompt_toolkit.document import Document

from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.input.completer import ChatCompleter


def _build_registry() -> CommandRegistry:
    """Create a CommandRegistry populated with a handful of commands."""
    registry = CommandRegistry()
    registry.register(
        SlashCommand(name="help", description="Show help", tier=InputTier.SYSTEM)
    )
    registry.register(
        SlashCommand(name="history", description="Show history", tier=InputTier.SYSTEM)
    )
    registry.register(
        SlashCommand(name="agent", description="Switch agent", tier=InputTier.SERVICE)
    )
    registry.register(
        SlashCommand(name="quit", description="Exit TUI", tier=InputTier.SYSTEM)
    )
    return registry


def _build_completer() -> ChatCompleter:
    """Create a ChatCompleter with agents, tools, and commands."""
    registry = _build_registry()
    return ChatCompleter(
        command_registry=registry,
        agent_names=["homelab", "finance", "work", "personal"],
        tool_names=["search_docs", "send_email", "search_transactions"],
    )


def _complete(completer: ChatCompleter, text: str) -> list[str]:
    """Return completion text values for the given input string."""
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


# -- @agent completions ---------------------------------------------------


class TestAgentCompletions:
    def test_at_prefix_yields_all_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "@")
        assert sorted(results) == ["finance", "homelab", "personal", "work"]

    def test_at_partial_filters_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "@ho")
        assert results == ["homelab"]

    def test_at_partial_no_match(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "@zzz")
        assert results == []

    def test_at_mid_line_still_completes(self) -> None:
        completer = _build_completer()
        # Simulate typing "ask @fi" with cursor at end
        doc = Document("ask @fi", cursor_position=7)
        results = [c.text for c in completer.get_completions(doc, None)]
        assert results == ["finance"]

    def test_at_completion_start_position(self) -> None:
        completer = _build_completer()
        doc = Document("@wo", cursor_position=3)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].text == "work"
        assert completions[0].start_position == -2  # replaces "wo"

    def test_at_completion_display_meta(self) -> None:
        completer = _build_completer()
        doc = Document("@fin", cursor_position=4)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].display_meta_text == "agent"


# -- /command completions -------------------------------------------------


class TestCommandCompletions:
    def test_slash_yields_all_commands(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/")
        assert sorted(results) == ["/agent", "/help", "/history", "/quit"]

    def test_slash_partial_filters(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/he")
        assert results == ["/help"]

    def test_slash_partial_multiple_matches(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/h")
        assert sorted(results) == ["/help", "/history"]

    def test_slash_no_match(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/xyz")
        assert results == []

    def test_slash_completion_has_description_meta(self) -> None:
        completer = _build_completer()
        doc = Document("/quit", cursor_position=5)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].display_meta_text == "Exit TUI"

    def test_slash_completion_start_position(self) -> None:
        completer = _build_completer()
        doc = Document("/ag", cursor_position=3)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].start_position == -3  # replaces "/ag"


# -- !tool completions ----------------------------------------------------


class TestToolCompletions:
    def test_bang_yields_all_tools(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "!")
        assert sorted(results) == [
            "!search_docs",
            "!search_transactions",
            "!send_email",
        ]

    def test_bang_partial_filters(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "!sen")
        assert results == ["!send_email"]

    def test_bang_partial_multiple_matches(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "!search")
        assert sorted(results) == ["!search_docs", "!search_transactions"]

    def test_bang_no_match(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "!nope")
        assert results == []

    def test_bang_completion_display_meta(self) -> None:
        completer = _build_completer()
        doc = Document("!send", cursor_position=5)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].display_meta_text == "tool"

    def test_bang_completion_start_position(self) -> None:
        completer = _build_completer()
        doc = Document("!se", cursor_position=3)
        completions = list(completer.get_completions(doc, None))
        # "!search_docs", "!search_transactions", "!send_email" all match
        assert all(c.start_position == -3 for c in completions)


# -- /command argument completions -----------------------------------------


class TestCommandArgCompletions:
    """Commands like /agent, /enter, /spawn complete agent names as args."""

    def test_agent_command_space_lists_all_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/agent ")
        assert sorted(results) == ["finance", "homelab", "personal", "work"]

    def test_agent_command_partial_filters(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/agent ho")
        assert results == ["homelab"]

    def test_agent_command_no_match(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/agent zzz")
        assert results == []

    def test_enter_command_completes_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/enter fi")
        assert results == ["finance"]

    def test_spawn_command_completes_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/spawn ")
        assert sorted(results) == ["finance", "homelab", "personal", "work"]

    def test_kill_command_completes_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/kill wo")
        assert results == ["work"]

    def test_summon_command_completes_agents(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/summon per")
        assert results == ["personal"]

    def test_non_agent_command_no_arg_completion(self) -> None:
        """Commands without agent args don't get agent completion."""
        completer = _build_completer()
        results = _complete(completer, "/help ")
        assert results == []

    def test_quit_command_no_arg_completion(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "/quit ")
        assert results == []

    def test_agent_arg_completion_has_meta(self) -> None:
        completer = _build_completer()
        doc = Document("/agent ho", cursor_position=9)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].text == "homelab"
        assert completions[0].display_meta_text == "agent"

    def test_agent_arg_start_position(self) -> None:
        completer = _build_completer()
        doc = Document("/agent ho", cursor_position=9)
        completions = list(completer.get_completions(doc, None))
        assert len(completions) == 1
        assert completions[0].start_position == -2  # replaces "ho"

    def test_agent_arg_updates_dynamically(self) -> None:
        completer = _build_completer()
        completer.update_agents(["alpha", "beta"])
        results = _complete(completer, "/agent ")
        assert sorted(results) == ["alpha", "beta"]


# -- Edge cases ------------------------------------------------------------


class TestEdgeCases:
    def test_empty_input_yields_nothing(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "")
        assert results == []

    def test_plain_text_yields_nothing(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "hello world")
        assert results == []

    def test_unknown_prefix_yields_nothing(self) -> None:
        completer = _build_completer()
        results = _complete(completer, "#unknown")
        assert results == []


# -- Dynamic updates -------------------------------------------------------


class TestDynamicUpdates:
    def test_update_agents_changes_completions(self) -> None:
        completer = _build_completer()
        # Initially has homelab, finance, work, personal
        assert "homelab" in _complete(completer, "@")

        completer.update_agents(["alpha", "beta"])
        results = _complete(completer, "@")
        assert sorted(results) == ["alpha", "beta"]
        assert "homelab" not in results

    def test_update_tools_changes_completions(self) -> None:
        completer = _build_completer()
        assert "!search_docs" in _complete(completer, "!")

        completer.update_tools(["new_tool"])
        results = _complete(completer, "!")
        assert results == ["!new_tool"]
        assert "!search_docs" not in results

    def test_update_agents_to_empty(self) -> None:
        completer = _build_completer()
        completer.update_agents([])
        results = _complete(completer, "@")
        assert results == []

    def test_update_tools_to_empty(self) -> None:
        completer = _build_completer()
        completer.update_tools([])
        results = _complete(completer, "!")
        assert results == []
