"""Tests for minimal system prompt composition."""

from pathlib import Path

from corvus.cli.compose_system_prompt import compose_system_prompt


class TestComposeSystemPrompt:
    """Tests for the minimal system prompt builder."""

    def test_includes_soul_content(self, tmp_path: Path) -> None:
        """System prompt includes soul.md content."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\nYou are an agent in Corvus.\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "You are an agent in Corvus" in result

    def test_includes_identity_assertion(self, tmp_path: Path) -> None:
        """System prompt includes agent identity assertion."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "**personal**" in result
        assert "personal agent" in result

    def test_includes_agent_soul_when_provided(self, tmp_path: Path) -> None:
        """System prompt includes agent soul content."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content="You are warm but efficient.",
        )
        assert "warm but efficient" in result

    def test_no_domain_instructions(self, tmp_path: Path) -> None:
        """System prompt does NOT include domain instructions (those go in CLAUDE.md)."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\nCore principles.\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        # Should be short — no siblings, no memory, no domain prompt
        assert len(result) < 3000

    def test_fallback_when_soul_missing(self, tmp_path: Path) -> None:
        """Uses fallback identity when soul.md doesn't exist."""
        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "Corvus" in result
        assert "NOT Claude" in result
