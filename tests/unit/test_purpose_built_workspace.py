"""Behavioral tests for purpose-built workspace composition.

Verifies that agent workspaces are created with minimal, secure contents:
- Only .claude/settings.json, .claude/CLAUDE.md, and optional skills/
- No source code, no .env, no credentials
- 0o700 permissions on workspace root
- Cleanup refuses to delete paths outside temp dir
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from corvus.cli.workspace import cleanup_workspace, create_workspace, verify_workspace_integrity


@pytest.fixture()
def workspace_dir():
    """Create a workspace and clean it up after the test."""
    created: list[Path] = []

    def _create(**kwargs):
        defaults = {
            "agent_name": "testbot",
            "session_id": "abcd1234-5678-90ef",
            "settings_json": json.dumps({"permissions": {"deny": ["Bash"]}}),
            "claude_md": "# Test Agent\n\nYou are a test agent.",
        }
        defaults.update(kwargs)
        ws = create_workspace(**defaults)
        created.append(ws)
        return ws

    yield _create

    for ws in created:
        if ws.exists():
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestCreateWorkspace:
    """Tests for create_workspace()."""

    def test_workspace_created_in_temp_directory(self, workspace_dir):
        ws = workspace_dir()
        assert str(ws).startswith(tempfile.gettempdir())

    def test_workspace_has_restrictive_permissions(self, workspace_dir):
        ws = workspace_dir()
        mode = os.stat(ws).st_mode
        # Owner has rwx, group and other have nothing
        assert mode & 0o700 == 0o700
        assert mode & 0o077 == 0

    def test_workspace_prefix_contains_agent_name(self, workspace_dir):
        ws = workspace_dir(agent_name="finance")
        assert "corvus-finance-" in ws.name

    def test_workspace_prefix_contains_session_prefix(self, workspace_dir):
        ws = workspace_dir(session_id="deadbeef-1234-5678")
        assert "deadbeef" in ws.name

    def test_settings_json_exists_with_correct_content(self, workspace_dir):
        settings_content = json.dumps({"permissions": {"deny": ["Bash", "Edit"]}})
        ws = workspace_dir(settings_json=settings_content)
        settings_path = ws / ".claude" / "settings.json"
        assert settings_path.is_file()
        loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        assert loaded["permissions"]["deny"] == ["Bash", "Edit"]

    def test_claude_md_exists_with_correct_content(self, workspace_dir):
        md_content = "# Finance Agent\n\nYou handle money."
        ws = workspace_dir(claude_md=md_content)
        md_path = ws / ".claude" / "CLAUDE.md"
        assert md_path.is_file()
        assert md_path.read_text(encoding="utf-8") == md_content

    def test_skills_directory_created_with_files(self, workspace_dir):
        skills = {
            "search.md": "# Search Skill\nHow to search.",
            "summarize.md": "# Summarize Skill\nHow to summarize.",
        }
        ws = workspace_dir(skills=skills)
        skills_dir = ws / "skills"
        assert skills_dir.is_dir()
        assert (skills_dir / "search.md").read_text(encoding="utf-8") == skills["search.md"]
        assert (skills_dir / "summarize.md").read_text(encoding="utf-8") == skills["summarize.md"]

    def test_no_skills_directory_when_none_provided(self, workspace_dir):
        ws = workspace_dir(skills=None)
        assert not (ws / "skills").exists()

    def test_no_env_files_exist(self, workspace_dir):
        ws = workspace_dir()
        env_files = list(ws.rglob(".env*"))
        assert env_files == []

    def test_no_python_source_code_exists(self, workspace_dir):
        ws = workspace_dir()
        py_files = list(ws.rglob("*.py"))
        assert py_files == []

    def test_no_config_directory_exists(self, workspace_dir):
        ws = workspace_dir()
        assert not (ws / "config").exists()

    def test_workspace_contains_only_expected_structure(self, workspace_dir):
        ws = workspace_dir(skills={"hello.md": "hi"})
        all_files = sorted(str(f.relative_to(ws)) for f in ws.rglob("*") if f.is_file())
        assert all_files == [
            ".claude/CLAUDE.md",
            ".claude/settings.json",
            ".claude/skill_checksums.json",
            "skills/hello.md",
        ]

    def test_custom_base_dir(self):
        custom_base = Path(tempfile.mkdtemp(prefix="corvus-test-base-"))
        try:
            ws = create_workspace(
                agent_name="test",
                session_id="12345678",
                settings_json="{}",
                claude_md="# Test",
                base_dir=str(custom_base),
            )
            assert str(ws).startswith(str(custom_base))
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
        finally:
            import shutil
            shutil.rmtree(custom_base, ignore_errors=True)


class TestCleanupWorkspace:
    """Tests for cleanup_workspace()."""

    def test_cleanup_removes_directory(self):
        ws = create_workspace(
            agent_name="cleanup-test",
            session_id="abcd1234",
            settings_json="{}",
            claude_md="# Test",
        )
        assert ws.exists()
        cleanup_workspace(ws)
        assert not ws.exists()

    def test_cleanup_nonexistent_is_noop(self, tmp_path):
        fake = tmp_path / "nonexistent"
        # Should not raise
        cleanup_workspace(fake)

    def test_cleanup_refuses_path_outside_temp_dir(self, tmp_path):
        # Create a directory outside the system temp dir
        outside_dir = tmp_path / "outside-workspace"
        outside_dir.mkdir()
        marker = outside_dir / "marker.txt"
        marker.write_text("should survive", encoding="utf-8")

        # cleanup_workspace should refuse to delete it
        cleanup_workspace(outside_dir)

        # Directory should still exist
        assert outside_dir.exists()
        assert marker.read_text(encoding="utf-8") == "should survive"


class TestVerifyWorkspaceIntegrity:
    """Tests for verify_workspace_integrity()."""

    def test_clean_workspace_passes(self, workspace_dir):
        ws = workspace_dir()
        violations = verify_workspace_integrity(ws)
        assert violations == []

    def test_catches_env_file(self, workspace_dir):
        ws = workspace_dir()
        (ws / ".env").write_text("SECRET=oops", encoding="utf-8")
        violations = verify_workspace_integrity(ws)
        assert any(".env" in v for v in violations)

    def test_catches_credentials_file(self, workspace_dir):
        ws = workspace_dir()
        (ws / "credentials.json").write_text("{}", encoding="utf-8")
        violations = verify_workspace_integrity(ws)
        assert any("credentials" in v.lower() for v in violations)

    def test_catches_ssh_key(self, workspace_dir):
        ws = workspace_dir()
        ssh_dir = ws / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "id_rsa").write_text("fake key", encoding="utf-8")
        violations = verify_workspace_integrity(ws)
        assert any(".ssh" in v for v in violations)

    def test_catches_pem_file(self, workspace_dir):
        ws = workspace_dir()
        (ws / "server.pem").write_text("fake cert", encoding="utf-8")
        violations = verify_workspace_integrity(ws)
        assert any(".pem" in v for v in violations)

    def test_catches_open_permissions(self, workspace_dir):
        ws = workspace_dir()
        os.chmod(ws, 0o755)
        violations = verify_workspace_integrity(ws)
        assert any("permissions" in v.lower() for v in violations)
        # Restore for cleanup
        os.chmod(ws, 0o700)

    def test_workspace_with_skills_passes(self, workspace_dir):
        ws = workspace_dir(skills={"task.md": "# Task"})
        violations = verify_workspace_integrity(ws)
        assert violations == []
