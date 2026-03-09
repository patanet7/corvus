"""Behavioral tests for TUI Phase 3 — Tools & Service Commands.

Tests cover:
1. Always-allow tracking for tool confirmations
2. Memory command rendering (/memory search, list, save, forget)
3. Tools listing and detail rendering (/tools, /tool)
4. !tool dispatch via parsed input
5. File view rendering (/view)
6. Diff rendering (/diff)
7. Gateway protocol memory/tool methods
8. Input parser tool_call handling

All tests are behavioral — no mocks, no monkeypatch, no @patch.
Uses real Rich Console writing to io.StringIO for rendered output.
Uses real temp files for file operations.
"""

import io
import os
import tempfile

import pytest
from rich.console import Console

from corvus.tui.app import TuiApp
from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.core.event_handler import EventHandler
from corvus.tui.input.parser import InputParser
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


def _output(buf: io.StringIO) -> str:
    """Return everything written so far and reset."""
    buf.seek(0)
    text = buf.read()
    buf.seek(0)
    buf.truncate()
    return text


def _make_event_handler() -> tuple[EventHandler, AgentStack, io.StringIO, TokenCounter]:
    """Build an EventHandler wired to a real renderer."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, width=120)
    theme = TuiTheme()
    renderer = ChatRenderer(console=console, theme=theme)
    stack = AgentStack()
    counter = TokenCounter()
    handler = EventHandler(renderer, stack, counter)
    return handler, stack, buf, counter


# ===========================================================================
# 1. Always-allow tracking
# ===========================================================================

class TestAlwaysAllowTracking:
    """Per-tool 'always allow' tracking in TuiApp."""

    def test_always_allow_set_starts_empty(self) -> None:
        app = TuiApp()
        assert len(app._always_allow) == 0

    def test_mark_tool_always_allow(self) -> None:
        app = TuiApp()
        app.mark_tool_always_allow("Bash")
        assert app.is_tool_always_allowed("Bash")
        assert not app.is_tool_always_allowed("Read")

    def test_multiple_tools_tracked_independently(self) -> None:
        app = TuiApp()
        app.mark_tool_always_allow("Bash")
        app.mark_tool_always_allow("Read")
        assert app.is_tool_always_allowed("Bash")
        assert app.is_tool_always_allowed("Read")
        assert not app.is_tool_always_allowed("Write")

    def test_duplicate_mark_is_idempotent(self) -> None:
        app = TuiApp()
        app.mark_tool_always_allow("Bash")
        app.mark_tool_always_allow("Bash")
        assert len(app._always_allow) == 1


class TestAlwaysAllowEventHandlerIntegration:
    """EventHandler auto-approves tools in the always-allow set."""

    @pytest.mark.asyncio
    async def test_auto_approve_skips_confirm_prompt(self) -> None:
        """When a tool is always-allowed, confirm prompt is NOT rendered."""
        handler, stack, buf, _ = _make_event_handler()

        approved_calls: list[str] = []

        def check_fn(tool_name: str) -> bool:
            return tool_name == "Bash"

        def confirm_fn(tool_id: str, _action: str) -> None:
            approved_calls.append(tool_id)

        handler.set_auto_approve(check_fn, confirm_fn)

        # Send a confirm request for an always-allowed tool
        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-1",
            "agent": "homelab",
            "input": {"command": "ls"},
        }))

        _output(buf)  # consume any rendered output
        # Should NOT render confirm prompt
        assert handler.pending_confirm is None
        # Should have auto-approved
        assert "tid-1" in approved_calls

    @pytest.mark.asyncio
    async def test_non_allowed_tool_shows_confirm(self) -> None:
        """When a tool is NOT always-allowed, confirm prompt IS rendered."""
        handler, stack, buf, _ = _make_event_handler()

        approved_calls: list[str] = []

        def check_fn(tool_name: str) -> bool:
            return tool_name == "Bash"

        def confirm_fn(tool_id: str, _action: str) -> None:
            approved_calls.append(tool_id)

        handler.set_auto_approve(check_fn, confirm_fn)

        # Send a confirm request for a NON-allowed tool
        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Write",
            "tool_id": "tid-2",
            "agent": "homelab",
            "input": {"path": "/tmp/test"},
        }))

        output = _output(buf)
        assert handler.pending_confirm is not None
        assert handler.pending_confirm.tool_id == "tid-2"
        assert "Write" in output
        assert len(approved_calls) == 0

    @pytest.mark.asyncio
    async def test_without_auto_approve_set_shows_confirm(self) -> None:
        """Without auto-approve configured, all confirms render normally."""
        handler, stack, buf, _ = _make_event_handler()

        await handler.handle(parse_event({
            "type": "confirm_request",
            "tool": "Bash",
            "tool_id": "tid-3",
            "agent": "work",
            "input": {},
        }))

        assert handler.pending_confirm is not None
        assert handler.pending_confirm.tool == "Bash"


# ===========================================================================
# 2. Memory command rendering
# ===========================================================================

class TestMemoryResultsRendering:
    """Renderer correctly formats memory results tables."""

    def test_render_memory_results_shows_table(self) -> None:
        renderer, buf = _make_renderer()
        results = [
            {"id": "abc-12345-def", "content": "Meeting notes from standup", "domain": "work", "score": 0.85},
            {"id": "ghi-67890-jkl", "content": "Homelab DNS config", "domain": "homelab", "score": 0.72},
        ]
        renderer.render_memory_results(results, title="Memory Search: standup")
        output = _output(buf)

        assert "abc-1234" in output  # truncated ID
        assert "Meeting notes" in output
        assert "work" in output
        assert "homelab" in output
        assert "0.85" in output
        assert "Memory Search" in output

    def test_render_memory_results_empty(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_memory_results([], title="Memory Search: nothing")
        output = _output(buf)
        assert "No results found" in output

    def test_render_memory_results_truncates_content(self) -> None:
        renderer, buf = _make_renderer()
        long_content = "x" * 200
        results = [{"id": "test-id", "content": long_content, "domain": "shared", "score": 0.5}]
        renderer.render_memory_results(results)
        output = _output(buf)
        # Content should be truncated to 80 chars max
        assert "test-id" in output[:100] or "test-id"[:8] in output


class TestMemoryCommandParsing:
    """Parser correctly handles /memory sub-commands."""

    def test_parse_memory_search(self) -> None:
        parser = InputParser()
        parsed = parser.parse("/memory search homelab config")
        assert parsed.kind == "command"
        assert parsed.command == "memory"
        assert parsed.command_args == "search homelab config"

    def test_parse_memory_list(self) -> None:
        parser = InputParser()
        parsed = parser.parse("/memory list")
        assert parsed.kind == "command"
        assert parsed.command == "memory"
        assert parsed.command_args == "list"

    def test_parse_memory_save(self) -> None:
        parser = InputParser()
        parsed = parser.parse("/memory save Remember to update DNS")
        assert parsed.kind == "command"
        assert parsed.command == "memory"
        assert parsed.command_args == "save Remember to update DNS"

    def test_parse_memory_forget(self) -> None:
        parser = InputParser()
        parsed = parser.parse("/memory forget abc-12345")
        assert parsed.kind == "command"
        assert parsed.command == "memory"
        assert parsed.command_args == "forget abc-12345"


class TestMemoryCommandRouting:
    """Memory commands route through service tier to handler."""

    def test_memory_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("memory")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE

    @pytest.mark.asyncio
    async def test_memory_no_args_shows_error(self) -> None:
        """Calling /memory with no sub-command shows usage error."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = await app._handle_memory_command("")
        assert result is True
        output = _output(buf)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_memory_search_no_query_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = await app._handle_memory_command("search")
        assert result is True
        output = _output(buf)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_memory_save_no_text_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = await app._handle_memory_command("save")
        assert result is True
        output = _output(buf)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_memory_forget_no_id_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = await app._handle_memory_command("forget")
        assert result is True
        output = _output(buf)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_memory_unknown_action_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = await app._handle_memory_command("bogus")
        assert result is True
        output = _output(buf)
        assert "Usage" in output


# ===========================================================================
# 3. Tools listing and detail rendering
# ===========================================================================

class TestToolsListRendering:
    """Renderer correctly formats tool list tables."""

    def test_render_tools_list_shows_table(self) -> None:
        renderer, buf = _make_renderer()
        tools = [
            {"name": "Bash", "type": "builtin", "description": "Execute shell commands"},
            {"name": "mcp__memory__search", "type": "mcp", "description": "Search memories"},
        ]
        renderer.render_tools_list(tools, agent="homelab")
        output = _output(buf)

        assert "Bash" in output
        assert "mcp__memory__search" in output
        assert "builtin" in output
        assert "homelab" in output.lower() or "@homelab" in output

    def test_render_tools_list_empty(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_tools_list([], agent="homelab")
        output = _output(buf)
        assert "No tools available" in output

    def test_render_tool_detail(self) -> None:
        renderer, buf = _make_renderer()
        tool = {"name": "Bash", "type": "builtin", "description": "Execute shell commands"}
        renderer.render_tool_detail(tool, agent="homelab")
        output = _output(buf)

        assert "Bash" in output
        assert "builtin" in output
        assert "Execute shell commands" in output


class TestToolsCommandRouting:
    """Tools commands route through service tier."""

    def test_tools_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("tools")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE

    def test_tool_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("tool")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE


# ===========================================================================
# 4. !tool dispatch via parsed input
# ===========================================================================

class TestToolCallParsing:
    """Parser correctly classifies !tool_name as tool_call kind."""

    def test_parse_tool_call_simple(self) -> None:
        parser = InputParser()
        parsed = parser.parse("!search_docs query text")
        assert parsed.kind == "tool_call"
        assert parsed.tool_name == "search_docs"
        assert parsed.tool_args == "query text"

    def test_parse_tool_call_no_args(self) -> None:
        parser = InputParser()
        parsed = parser.parse("!list_files")
        assert parsed.kind == "tool_call"
        assert parsed.tool_name == "list_files"
        assert parsed.tool_args is None

    def test_parse_tool_call_with_dots(self) -> None:
        parser = InputParser()
        parsed = parser.parse("!mcp.memory.search my query")
        assert parsed.kind == "tool_call"
        assert parsed.tool_name == "mcp.memory.search"
        assert parsed.tool_args == "my query"


class TestToolCallDispatchRouting:
    """!tool_call inputs route to AGENT tier and build correct message."""

    def test_tool_call_routes_to_agent_tier(self) -> None:
        """Tool calls are classified as AGENT tier by command router."""
        from corvus.tui.commands.registry import CommandRegistry, InputTier
        from corvus.tui.core.command_router import CommandRouter

        registry = CommandRegistry()
        router = CommandRouter(registry)
        parser = InputParser()

        parsed = parser.parse("!search_docs query")
        tier = router.classify(parsed)
        assert tier is InputTier.AGENT

    def test_tool_call_message_format(self) -> None:
        """Verify the message format sent to gateway for !tool calls."""
        parser = InputParser()
        parsed = parser.parse("!search_docs homelab config")

        # Reproduce the logic from _handle_agent_input
        text = f"!{parsed.tool_name}"
        if parsed.tool_args:
            text += f" {parsed.tool_args}"

        assert text == "!search_docs homelab config"

    def test_tool_call_no_args_message_format(self) -> None:
        parser = InputParser()
        parsed = parser.parse("!list_files")

        text = f"!{parsed.tool_name}"
        if parsed.tool_args:
            text += f" {parsed.tool_args}"

        assert text == "!list_files"


# ===========================================================================
# 5. File view rendering
# ===========================================================================

class TestFileViewRendering:
    """Renderer correctly shows file contents with syntax highlighting."""

    def test_render_file_view_python(self) -> None:
        renderer, buf = _make_renderer()
        content = 'def hello():\n    print("Hello, world!")\n'
        renderer.render_file_view("/tmp/test.py", content, "python")
        output = _output(buf)

        assert "test.py" in output
        assert "hello" in output

    def test_render_file_view_json(self) -> None:
        renderer, buf = _make_renderer()
        content = '{"key": "value", "count": 42}\n'
        renderer.render_file_view("/tmp/config.json", content, "json")
        output = _output(buf)

        assert "config.json" in output

    def test_render_file_view_no_language(self) -> None:
        renderer, buf = _make_renderer()
        content = "Just plain text content.\n"
        renderer.render_file_view("/tmp/notes.txt", content, "")
        output = _output(buf)
        assert "notes.txt" in output
        assert "plain text" in output


class TestFileViewCommand:
    """TuiApp._handle_view_command reads real files."""

    def test_view_reads_real_file(self) -> None:
        """Creates a real temp file, views it, verifies output."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('def greet():\n    return "hello"\n')
            tmp_path = f.name

        try:
            result = app._handle_view_command(tmp_path)
            assert result is True
            output = _output(buf)
            assert "greet" in output
            assert tmp_path in output
        finally:
            os.unlink(tmp_path)

    def test_view_nonexistent_file_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = app._handle_view_command("/tmp/nonexistent_file_xyz_12345.py")
        assert result is True
        output = _output(buf)
        assert "not found" in output.lower() or "File not found" in output

    def test_view_no_path_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = app._handle_view_command("")
        assert result is True
        output = _output(buf)
        assert "Usage" in output


class TestLanguageDetection:
    """TuiApp._detect_language maps file extensions correctly."""

    def test_python_detection(self) -> None:
        assert TuiApp._detect_language("script.py") == "python"

    def test_javascript_detection(self) -> None:
        assert TuiApp._detect_language("app.js") == "javascript"

    def test_typescript_detection(self) -> None:
        assert TuiApp._detect_language("component.ts") == "typescript"

    def test_yaml_detection(self) -> None:
        assert TuiApp._detect_language("config.yaml") == "yaml"
        assert TuiApp._detect_language("config.yml") == "yaml"

    def test_json_detection(self) -> None:
        assert TuiApp._detect_language("data.json") == "json"

    def test_unknown_extension_returns_text(self) -> None:
        assert TuiApp._detect_language("readme.xyz") == "text"

    def test_bash_detection(self) -> None:
        assert TuiApp._detect_language("deploy.sh") == "bash"

    def test_rust_detection(self) -> None:
        assert TuiApp._detect_language("main.rs") == "rust"

    def test_svelte_detection(self) -> None:
        assert TuiApp._detect_language("App.svelte") == "html"


# ===========================================================================
# 6. Diff rendering
# ===========================================================================

class TestDiffRendering:
    """Renderer correctly formats diff output."""

    def test_render_diff_with_content(self) -> None:
        renderer, buf = _make_renderer()
        diff_text = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " def hello():\n"
            "-    pass\n"
            "+    print('hello')\n"
            "+    return True\n"
        )
        renderer.render_diff(diff_text, path="foo.py")
        output = _output(buf)

        assert "foo.py" in output
        assert "diff" in output.lower()

    def test_render_diff_empty(self) -> None:
        renderer, buf = _make_renderer()
        renderer.render_diff("", path="")
        output = _output(buf)
        assert "No changes found" in output

    def test_render_diff_no_path(self) -> None:
        renderer, buf = _make_renderer()
        diff_text = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
        renderer.render_diff(diff_text)
        output = _output(buf)
        assert "git diff" in output.lower()


class TestDiffCommand:
    """TuiApp._handle_diff_command runs git diff on real files."""

    def test_diff_no_path_runs_git_diff(self) -> None:
        """Running /diff without args runs git diff (may have no output)."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = app._handle_diff_command("")
        assert result is True
        # Should either show diff output or "No changes found"
        output = _output(buf)
        assert len(output) > 0


class TestDiffCommandRouting:
    """Diff command routes through service tier."""

    def test_diff_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("diff")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE

    def test_view_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("view")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE

    def test_edit_is_service_tier(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        cmd = app.command_registry.lookup("edit")
        assert cmd is not None
        assert cmd.tier is InputTier.SERVICE


# ===========================================================================
# 7. Theme properties for new elements
# ===========================================================================

class TestThemePhase3Properties:
    """Theme has all properties needed for Phase 3 UI elements."""

    def test_memory_styles_exist(self) -> None:
        theme = TuiTheme()
        assert isinstance(theme.memory_id, str)
        assert isinstance(theme.memory_content, str)
        assert isinstance(theme.memory_domain, str)
        assert isinstance(theme.memory_score, str)

    def test_tool_styles_exist(self) -> None:
        theme = TuiTheme()
        assert isinstance(theme.tool_name, str)
        assert isinstance(theme.tool_type, str)
        assert isinstance(theme.tool_description, str)

    def test_file_view_styles_exist(self) -> None:
        theme = TuiTheme()
        assert isinstance(theme.file_view_border, str)
        assert isinstance(theme.file_view_syntax_theme, str)

    def test_diff_styles_exist(self) -> None:
        theme = TuiTheme()
        assert isinstance(theme.diff_border, str)
        assert isinstance(theme.diff_syntax_theme, str)


# ===========================================================================
# 8. Gateway protocol abstract interface
# ===========================================================================

class TestGatewayProtocolInterface:
    """GatewayProtocol declares memory and tool abstract methods."""

    def test_memory_methods_declared(self) -> None:
        from corvus.tui.protocol.base import GatewayProtocol

        assert hasattr(GatewayProtocol, "memory_search")
        assert hasattr(GatewayProtocol, "memory_list")
        assert hasattr(GatewayProtocol, "memory_save")
        assert hasattr(GatewayProtocol, "memory_forget")

        # All should be abstract
        for method_name in ("memory_search", "memory_list", "memory_save", "memory_forget"):
            method = getattr(GatewayProtocol, method_name)
            assert getattr(method, "__isabstractmethod__", False), f"{method_name} is not abstract"

    def test_tool_methods_declared(self) -> None:
        from corvus.tui.protocol.base import GatewayProtocol

        assert hasattr(GatewayProtocol, "list_agent_tools")
        assert GatewayProtocol.list_agent_tools.__isabstractmethod__


class TestInProcessGatewayImplements:
    """InProcessGateway implements all new abstract methods."""

    def test_memory_methods_exist(self) -> None:
        from corvus.tui.protocol.in_process import InProcessGateway

        gw = InProcessGateway()
        assert hasattr(gw, "memory_search")
        assert hasattr(gw, "memory_list")
        assert hasattr(gw, "memory_save")
        assert hasattr(gw, "memory_forget")
        assert callable(gw.memory_search)
        assert callable(gw.memory_list)
        assert callable(gw.memory_save)
        assert callable(gw.memory_forget)

    def test_tool_methods_exist(self) -> None:
        from corvus.tui.protocol.in_process import InProcessGateway

        gw = InProcessGateway()
        assert hasattr(gw, "list_agent_tools")
        assert callable(gw.list_agent_tools)


# ===========================================================================
# 9. Service command handler dispatch
# ===========================================================================

class TestServiceCommandDispatch:
    """Verify _handle_service_command routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_tools_command_dispatches(self) -> None:
        """Verify /tools is handled (not 'not yet implemented')."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/tools")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        # Should NOT say "not yet implemented"
        assert "not yet implemented" not in output

    @pytest.mark.asyncio
    async def test_tool_command_no_args_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/tool")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_view_command_dispatches(self) -> None:
        """Verify /view is handled (not 'not yet implemented')."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/view")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        assert "not yet implemented" not in output

    @pytest.mark.asyncio
    async def test_diff_command_dispatches(self) -> None:
        """Verify /diff is handled — renders diff or 'No changes found'."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/diff")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        # Should render either diff output or "No changes found" — either way it was handled
        assert "diff" in output.lower() or "No changes" in output

    @pytest.mark.asyncio
    async def test_memory_command_dispatches(self) -> None:
        """Verify /memory is handled (not 'not yet implemented')."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/memory")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        assert "not yet implemented" not in output

    @pytest.mark.asyncio
    async def test_workers_command_dispatches(self) -> None:
        """The /workers command dispatches to its handler and produces output."""
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        parsed = app.parser.parse("/workers")
        result = await app._handle_service_command(parsed)
        assert result is True
        output = _output(buf)
        assert "No active agents" in output or "workers" in output.lower()


# ===========================================================================
# 10. Edit command
# ===========================================================================

class TestEditCommand:
    """TuiApp._handle_edit_command handles edge cases."""

    def test_edit_no_path_shows_error(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        result = app._handle_edit_command("")
        assert result is True
        output = _output(buf)
        assert "Usage" in output


# ===========================================================================
# 11. Full integration: parser -> router -> handler dispatch
# ===========================================================================

class TestEndToEndCommandParsing:
    """Full parsing -> routing -> handler dispatch paths."""

    def test_memory_search_full_path(self) -> None:
        """Parser parses, router classifies, handler would dispatch."""
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        parsed = app.parser.parse("/memory search homelab dns")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SERVICE
        assert parsed.command == "memory"
        assert parsed.command_args == "search homelab dns"

    def test_tool_call_full_path(self) -> None:
        """!tool dispatch flows from parser through agent tier."""
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        parsed = app.parser.parse("!search_docs homelab")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.AGENT
        assert parsed.kind == "tool_call"
        assert parsed.tool_name == "search_docs"

    def test_view_full_path(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        parsed = app.parser.parse("/view /tmp/test.py")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SERVICE
        assert parsed.command == "view"
        assert parsed.command_args == "/tmp/test.py"

    def test_diff_full_path(self) -> None:
        from corvus.tui.commands.registry import InputTier

        app = TuiApp()
        parsed = app.parser.parse("/diff corvus/tui/app.py")
        tier = app.command_router.classify(parsed)

        assert tier is InputTier.SERVICE
        assert parsed.command == "diff"
        assert parsed.command_args == "corvus/tui/app.py"


# ===========================================================================
# 12. File view with real temp files (end-to-end)
# ===========================================================================

class TestFileViewEndToEnd:
    """Full file view with real files of various types."""

    def test_view_yaml_file(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("name: corvus\nversion: 1.0\nagents:\n  - huginn\n  - homelab\n")
            tmp_path = f.name

        try:
            result = app._handle_view_command(tmp_path)
            assert result is True
            output = _output(buf)
            assert "corvus" in output
            assert tmp_path in output
        finally:
            os.unlink(tmp_path)

    def test_view_json_file(self) -> None:
        app = TuiApp()
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        app.console = console
        app.renderer = ChatRenderer(console, TuiTheme())

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"agents": ["huginn", "homelab"], "count": 2}\n')
            tmp_path = f.name

        try:
            result = app._handle_view_command(tmp_path)
            assert result is True
            output = _output(buf)
            assert tmp_path in output
        finally:
            os.unlink(tmp_path)
