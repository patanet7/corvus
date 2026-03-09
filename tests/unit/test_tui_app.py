"""Behavioral tests for TuiApp instantiation and builtin command registration."""

from corvus.tui.app import TuiApp
from corvus.tui.commands.registry import CommandRegistry, InputTier
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser
from corvus.tui.output.renderer import ChatRenderer
from corvus.tui.theme import TuiTheme


class TestTuiAppInstantiation:
    """TuiApp creates all components on construction."""

    def test_instantiates_without_error(self) -> None:
        app = TuiApp()
        assert app is not None

    def test_has_agent_stack(self) -> None:
        app = TuiApp()
        assert isinstance(app.agent_stack, AgentStack)

    def test_has_command_registry(self) -> None:
        app = TuiApp()
        assert isinstance(app.command_registry, CommandRegistry)

    def test_has_parser(self) -> None:
        app = TuiApp()
        assert isinstance(app.parser, InputParser)

    def test_has_event_handler(self) -> None:
        app = TuiApp()
        assert isinstance(app.event_handler, EventHandler)

    def test_has_renderer(self) -> None:
        app = TuiApp()
        assert isinstance(app.renderer, ChatRenderer)

    def test_has_theme(self) -> None:
        app = TuiApp()
        assert isinstance(app.theme, TuiTheme)


class TestBuiltinCommandLookup:
    """Core commands are found via registry lookup."""

    def test_help_registered(self) -> None:
        app = TuiApp()
        cmd = app.command_registry.lookup("help")
        assert cmd is not None
        assert cmd.name == "help"

    def test_quit_registered(self) -> None:
        app = TuiApp()
        cmd = app.command_registry.lookup("quit")
        assert cmd is not None
        assert cmd.name == "quit"

    def test_agents_registered(self) -> None:
        app = TuiApp()
        cmd = app.command_registry.lookup("agents")
        assert cmd is not None
        assert cmd.name == "agents"

    def test_agent_registered(self) -> None:
        app = TuiApp()
        cmd = app.command_registry.lookup("agent")
        assert cmd is not None
        assert cmd.name == "agent"


class TestBuiltinSystemCommands:
    """All SYSTEM tier commands are registered."""

    SYSTEM_COMMANDS = [
        "help", "quit", "agents", "agent", "models", "model",
        "reload", "setup", "breakglass", "focus", "split", "theme",
        "login", "panel", "config",
    ]

    def test_all_system_commands_registered(self) -> None:
        app = TuiApp()
        for name in self.SYSTEM_COMMANDS:
            cmd = app.command_registry.lookup(name)
            assert cmd is not None, f"System command '{name}' not registered"
            assert cmd.tier is InputTier.SYSTEM, (
                f"Command '{name}' has tier {cmd.tier}, expected SYSTEM"
            )

    def test_system_tier_count(self) -> None:
        app = TuiApp()
        system_cmds = app.command_registry.commands_for_tier(InputTier.SYSTEM)
        assert len(system_cmds) == len(self.SYSTEM_COMMANDS)


class TestBuiltinServiceCommands:
    """All SERVICE tier commands are registered."""

    SERVICE_COMMANDS = [
        "sessions", "session", "memory", "tools", "tool", "tool-history",
        "view", "edit", "diff", "workers", "tokens", "status", "export",
        "audit", "policy",
    ]

    def test_all_service_commands_registered(self) -> None:
        app = TuiApp()
        for name in self.SERVICE_COMMANDS:
            cmd = app.command_registry.lookup(name)
            assert cmd is not None, f"Service command '{name}' not registered"
            assert cmd.tier is InputTier.SERVICE, (
                f"Command '{name}' has tier {cmd.tier}, expected SERVICE"
            )

    def test_service_tier_count(self) -> None:
        app = TuiApp()
        service_cmds = app.command_registry.commands_for_tier(InputTier.SERVICE)
        assert len(service_cmds) == len(self.SERVICE_COMMANDS)


class TestBuiltinAgentCommands:
    """All AGENT tier commands are registered."""

    AGENT_COMMANDS = [
        "spawn", "enter", "back", "top", "summon", "kill",
    ]

    def test_all_agent_commands_registered(self) -> None:
        app = TuiApp()
        for name in self.AGENT_COMMANDS:
            cmd = app.command_registry.lookup(name)
            assert cmd is not None, f"Agent command '{name}' not registered"
            assert cmd.tier is InputTier.AGENT, (
                f"Command '{name}' has tier {cmd.tier}, expected AGENT"
            )

    def test_agent_tier_count(self) -> None:
        app = TuiApp()
        agent_cmds = app.command_registry.commands_for_tier(InputTier.AGENT)
        assert len(agent_cmds) == len(self.AGENT_COMMANDS)
