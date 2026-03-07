"""Tests for CLI chat ANSI rendering."""

from corvus.cli.chat_render import (
    format_agent_name,
    format_info_line,
    format_memory_event,
    format_tool_call,
    render_welcome,
)


def test_format_agent_name_includes_name() -> None:
    result = format_agent_name("homelab")
    assert "homelab" in result


def test_format_tool_call_shows_tool_and_input() -> None:
    result = format_tool_call("Bash", {"command": "docker ps"})
    assert "Bash" in result
    assert "docker ps" in result


def test_format_memory_event_shows_domain_and_content() -> None:
    result = format_memory_event("save", "homelab", "NAS IP is 10.0.0.50")
    assert "homelab" in result
    assert "NAS IP" in result


def test_format_info_line() -> None:
    result = format_info_line("Model", "claude-sonnet-4-6")
    assert "Model" in result
    assert "claude-sonnet-4-6" in result


def test_render_welcome_lists_agents() -> None:
    agents = [("homelab", "Server management"), ("finance", "Budget tracking")]
    result = render_welcome(agents)
    assert "homelab" in result
    assert "finance" in result
