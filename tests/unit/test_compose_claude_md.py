"""Tests for CLAUDE.md composition for agent workspaces."""

from pathlib import Path

from corvus.cli.compose_claude_md import compose_claude_md


class _FakeSpec:
    def __init__(self, name: str = "personal", description: str = "Personal agent"):
        self.name = name
        self.description = description
        self.prompt_file = None
        self._prompt_content = "You help with daily planning."

    def prompt(self, config_dir: Path) -> str:
        return self._prompt_content


class TestComposeCLAUDEMd:
    """Tests for CLAUDE.md generation."""

    def test_includes_agent_prompt(self) -> None:
        """CLAUDE.md contains the agent's prompt content."""
        spec = _FakeSpec()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[("work", "Work agent"), ("finance", "Finance agent")],
            memory_lines=["- (personal) Example memory"],
            memory_domain="personal",
        )
        assert "daily planning" in result

    def test_includes_siblings(self) -> None:
        """CLAUDE.md lists sibling agents."""
        spec = _FakeSpec()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[("work", "Work projects"), ("finance", "Budget tracking")],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "**work**" in result
        assert "**finance**" in result
        assert "Budget tracking" in result

    def test_includes_memory_context(self) -> None:
        """CLAUDE.md includes seeded memory lines."""
        spec = _FakeSpec()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[
                "- [evergreen] (personal) Thomas prefers dark mode [preferences]",
                "- (personal) Set up NAS last week [homelab]",
            ],
            memory_domain="personal",
        )
        assert "Thomas prefers dark mode" in result
        assert "Memory Context" in result
        assert "personal" in result

    def test_empty_memory_still_has_domain(self) -> None:
        """CLAUDE.md shows memory domain even with no memories."""
        spec = _FakeSpec()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "Your memory domain is **personal**" in result

    def test_no_siblings_omits_section(self) -> None:
        """CLAUDE.md omits siblings section when there are none."""
        spec = _FakeSpec()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "Other Agents" not in result
