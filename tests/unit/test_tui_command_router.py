"""Behavioral tests for the command registry and three-tier command router."""

from __future__ import annotations

from corvus.tui.commands.registry import CommandRegistry, InputTier, SlashCommand
from corvus.tui.core.command_router import CommandRouter
from corvus.tui.input.parser import InputParser


# ---------------------------------------------------------------------------
# Registry: register + lookup
# ---------------------------------------------------------------------------


def test_register_and_lookup() -> None:
    reg = CommandRegistry()
    cmd = SlashCommand(name="help", description="Show help", tier=InputTier.SYSTEM)
    reg.register(cmd)
    found = reg.lookup("help")
    assert found is not None
    assert found.name == "help"
    assert found.tier is InputTier.SYSTEM


def test_lookup_missing_returns_none() -> None:
    reg = CommandRegistry()
    assert reg.lookup("nonexistent") is None


# ---------------------------------------------------------------------------
# Registry: completions
# ---------------------------------------------------------------------------


def test_completions_partial_matching() -> None:
    reg = CommandRegistry()
    reg.register(SlashCommand(name="help", description="Show help", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="history", description="Show history", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="agent", description="Switch agent", tier=InputTier.SERVICE))

    matches = reg.completions("h")
    assert matches == ["help", "history"]

    matches = reg.completions("he")
    assert matches == ["help"]

    matches = reg.completions("a")
    assert matches == ["agent"]

    matches = reg.completions("z")
    assert matches == []


def test_completions_empty_returns_all_sorted() -> None:
    reg = CommandRegistry()
    reg.register(SlashCommand(name="beta", description="B", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="alpha", description="A", tier=InputTier.SYSTEM))
    matches = reg.completions("")
    assert matches == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Registry: all_commands + commands_for_tier
# ---------------------------------------------------------------------------


def test_all_commands() -> None:
    reg = CommandRegistry()
    c1 = SlashCommand(name="help", description="Help", tier=InputTier.SYSTEM)
    c2 = SlashCommand(name="agent", description="Agent", tier=InputTier.SERVICE)
    c3 = SlashCommand(name="memory", description="Memory", tier=InputTier.AGENT)
    reg.register(c1)
    reg.register(c2)
    reg.register(c3)
    all_cmds = reg.all_commands()
    assert len(all_cmds) == 3
    names = {c.name for c in all_cmds}
    assert names == {"help", "agent", "memory"}


def test_commands_for_tier() -> None:
    reg = CommandRegistry()
    reg.register(SlashCommand(name="help", description="Help", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="quit", description="Quit", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="agent", description="Agent", tier=InputTier.SERVICE))

    system = reg.commands_for_tier(InputTier.SYSTEM)
    assert len(system) == 2
    assert all(c.tier is InputTier.SYSTEM for c in system)

    service = reg.commands_for_tier(InputTier.SERVICE)
    assert len(service) == 1
    assert service[0].name == "agent"

    agent = reg.commands_for_tier(InputTier.AGENT)
    assert len(agent) == 0


# ---------------------------------------------------------------------------
# Router: classify
# ---------------------------------------------------------------------------


def _build_router() -> tuple[CommandRouter, InputParser]:
    reg = CommandRegistry()
    reg.register(SlashCommand(name="help", description="Help", tier=InputTier.SYSTEM))
    reg.register(SlashCommand(name="agent", description="Agent", tier=InputTier.SERVICE))
    reg.register(SlashCommand(name="memory", description="Memory", tier=InputTier.AGENT))
    router = CommandRouter(reg)
    parser = InputParser(known_agents=["homelab", "finance"])
    return router, parser


def test_router_classifies_system_command() -> None:
    router, parser = _build_router()
    parsed = parser.parse("/help")
    assert router.classify(parsed) is InputTier.SYSTEM


def test_router_classifies_service_command() -> None:
    router, parser = _build_router()
    parsed = parser.parse("/agent homelab")
    assert router.classify(parsed) is InputTier.SERVICE


def test_router_classifies_agent_tier_command() -> None:
    router, parser = _build_router()
    parsed = parser.parse("/memory search foo")
    assert router.classify(parsed) is InputTier.AGENT


def test_router_classifies_unknown_command_as_agent() -> None:
    router, parser = _build_router()
    parsed = parser.parse("/unknown_cmd")
    assert router.classify(parsed) is InputTier.AGENT


def test_router_classifies_chat_as_agent() -> None:
    router, parser = _build_router()
    parsed = parser.parse("hello world")
    assert router.classify(parsed) is InputTier.AGENT


def test_router_classifies_mention_as_agent() -> None:
    router, parser = _build_router()
    parsed = parser.parse("@homelab check nginx")
    assert router.classify(parsed) is InputTier.AGENT


def test_router_classifies_tool_call_as_agent() -> None:
    router, parser = _build_router()
    parsed = parser.parse("!obsidian.search query")
    assert router.classify(parsed) is InputTier.AGENT
