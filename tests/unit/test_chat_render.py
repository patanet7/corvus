"""Tests for CLI chat ANSI rendering."""

from corvus.cli.chat_render import render_welcome


def test_render_welcome_lists_agents() -> None:
    agents = [("homelab", "Server management"), ("finance", "Budget tracking")]
    result = render_welcome(agents)
    assert "homelab" in result
    assert "finance" in result


def test_render_welcome_shows_header() -> None:
    result = render_welcome([("homelab", "Server management")])
    assert "Corvus Chat" in result
    assert "Select an agent" in result
