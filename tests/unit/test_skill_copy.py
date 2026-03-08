"""Tests for tool skill copying into agent workspaces."""

from pathlib import Path

from corvus.gateway.workspace_runtime import copy_agent_skills


def _create_tool_skill(skills_root: Path, module: str) -> None:
    """Create a minimal tool skill directory."""
    skill_dir = skills_root / "tools" / module
    script_dir = skill_dir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {module}\n---\nSkill for {module}\n")
    (script_dir / f"{module}.py").write_text(f"# {module} script\n")

    # Also create the _lib directory
    lib_dir = skills_root / "tools" / "_lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "corvus_tool_client.py").write_text("# shared client\n")


class TestCopyToolSkills:
    """Tests for copying tool skills based on agent modules."""

    def test_copies_only_allowed_modules(self, tmp_path: Path) -> None:
        """Only skills for modules in the agent spec are copied."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        for mod in ["obsidian", "ha", "firefly"]:
            _create_tool_skill(skills_root, mod)

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["obsidian"],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "obsidian" / "SKILL.md").exists()
        assert not (skills_dest / "ha").exists()
        assert not (skills_dest / "firefly").exists()

    def test_always_copies_memory(self, tmp_path: Path) -> None:
        """Memory skill is always copied even if not in modules."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "memory")
        _create_tool_skill(skills_root, "obsidian")

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["obsidian"],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "memory" / "SKILL.md").exists()
        assert (skills_dest / "obsidian" / "SKILL.md").exists()

    def test_copies_shared_client_lib(self, tmp_path: Path) -> None:
        """The _lib/corvus_tool_client.py is copied for scripts to import."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "memory")

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=[],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "_lib" / "corvus_tool_client.py").exists()

    def test_copies_scripts_subdirectory(self, tmp_path: Path) -> None:
        """Script files inside the scripts/ subdirectory are copied."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "ha")

        copy_agent_skills(
            agent_name="homelab",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["ha"],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "ha" / "scripts" / "ha.py").exists()

    def test_agent_specific_skills_still_copied(self, tmp_path: Path) -> None:
        """Agent-specific skills from config/agents/{name}/skills/ are still copied."""
        config_dir = tmp_path / "project"
        agent_skills = config_dir / "config" / "agents" / "work" / "skills"
        agent_skills.mkdir(parents=True)
        (agent_skills / "custom-workflow.md").write_text("# Custom\n")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        copy_agent_skills(
            agent_name="work",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=[],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "custom-workflow.md").exists()
