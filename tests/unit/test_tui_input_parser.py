"""Behavioral tests for corvus.tui.input.parser — InputParser and ParsedInput."""

from corvus.tui.input.parser import InputParser, ParsedInput


class TestParsedInputDataclass:
    """ParsedInput is a frozen-slots dataclass with correct defaults."""

    def test_slots_enabled(self) -> None:
        pi = ParsedInput(raw="hi", kind="chat", text="hi")
        assert hasattr(pi, "__slots__")

    def test_defaults(self) -> None:
        pi = ParsedInput(raw="hi", kind="chat", text="hi")
        assert pi.command is None
        assert pi.command_args is None
        assert pi.tool_name is None
        assert pi.tool_args is None
        assert pi.mentions == []


class TestPlainChat:
    """Undecorated text becomes kind='chat'."""

    def test_plain_text(self) -> None:
        parser = InputParser()
        result = parser.parse("hello world")
        assert result.kind == "chat"
        assert result.text == "hello world"
        assert result.raw == "hello world"

    def test_empty_input(self) -> None:
        parser = InputParser()
        result = parser.parse("")
        assert result.kind == "chat"
        assert result.text == ""

    def test_whitespace_stripped(self) -> None:
        parser = InputParser()
        result = parser.parse("  hello  ")
        assert result.text == "hello"
        assert result.raw == "  hello  "
        assert result.kind == "chat"


class TestCommands:
    """/command parsing."""

    def test_help_no_args(self) -> None:
        parser = InputParser()
        result = parser.parse("/help")
        assert result.kind == "command"
        assert result.command == "help"
        assert result.command_args is None
        assert result.text == "/help"

    def test_agent_with_args(self) -> None:
        parser = InputParser()
        result = parser.parse("/agent homelab")
        assert result.kind == "command"
        assert result.command == "agent"
        assert result.command_args == "homelab"

    def test_memory_search_with_quoted_args(self) -> None:
        parser = InputParser()
        result = parser.parse('/memory search "query"')
        assert result.kind == "command"
        assert result.command == "memory"
        assert result.command_args == 'search "query"'


class TestToolCalls:
    """!tool.name parsing."""

    def test_tool_call(self) -> None:
        parser = InputParser()
        result = parser.parse('!obsidian.search "query"')
        assert result.kind == "tool_call"
        assert result.tool_name == "obsidian.search"
        assert result.tool_args == '"query"'

    def test_tool_call_no_args(self) -> None:
        parser = InputParser()
        result = parser.parse("!system.status")
        assert result.kind == "tool_call"
        assert result.tool_name == "system.status"
        assert result.tool_args is None


class TestMentions:
    """@agent parsing — only known agents become mentions."""

    def test_single_mention(self) -> None:
        parser = InputParser(known_agents=["homelab", "finance"])
        result = parser.parse("@homelab check nginx")
        assert result.kind == "mention"
        assert result.mentions == ["homelab"]
        assert result.text == "check nginx"

    def test_multiple_mentions(self) -> None:
        parser = InputParser(known_agents=["homelab", "finance"])
        result = parser.parse("@homelab @finance status")
        assert result.kind == "mention"
        assert result.mentions == ["homelab", "finance"]
        assert result.text == "status"

    def test_all_mention(self) -> None:
        parser = InputParser(known_agents=["homelab"])
        result = parser.parse("@all broadcast")
        assert result.kind == "mention"
        assert result.mentions == ["all"]
        assert result.text == "broadcast"

    def test_unknown_mention_falls_to_chat(self) -> None:
        parser = InputParser(known_agents=["homelab"])
        result = parser.parse("@nobody hello")
        assert result.kind == "chat"
        assert result.mentions == []
        assert result.text == "@nobody hello"


class TestUpdateAgents:
    """update_agents dynamically adds known agents."""

    def test_update_agents(self) -> None:
        parser = InputParser()
        # Initially unknown
        result = parser.parse("@homelab hi")
        assert result.kind == "chat"

        parser.update_agents(["homelab"])
        result = parser.parse("@homelab hi")
        assert result.kind == "mention"
        assert result.mentions == ["homelab"]
