"""Behavioral tests for skill file integrity checksums (SEC-010).

Verifies that:
- SHA-256 checksums are correctly computed for skill file contents
- Integrity verification detects tampered, missing, and extra files
- create_workspace stores checksums when skills are provided
- Round-trip create -> verify passes cleanly
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from corvus.cli.workspace import (
    _validate_skill_filename,
    compute_skill_checksums,
    create_workspace,
    verify_skill_integrity,
)


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
            shutil.rmtree(ws, ignore_errors=True)


class TestComputeSkillChecksums:
    """Tests for compute_skill_checksums()."""

    def test_returns_correct_sha256_for_known_content(self):
        content = "Hello, world!"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result = compute_skill_checksums({"greeting.md": content})
        assert result == {"greeting.md": expected}

    def test_handles_empty_dict(self):
        result = compute_skill_checksums({})
        assert result == {}

    def test_handles_multiple_files(self):
        skills = {
            "alpha.md": "Alpha content",
            "beta.md": "Beta content",
            "gamma.md": "Gamma content",
        }
        result = compute_skill_checksums(skills)
        assert len(result) == 3
        for filename, content in skills.items():
            expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
            assert result[filename] == expected


class TestVerifySkillIntegrity:
    """Tests for verify_skill_integrity()."""

    def test_passes_when_files_match_checksums(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        content = "# Search Skill\nHow to search."
        (skills_dir / "search.md").write_text(content, encoding="utf-8")
        checksums = {"search.md": hashlib.sha256(content.encode("utf-8")).hexdigest()}

        violations = verify_skill_integrity(tmp_path, checksums)
        assert violations == []

    def test_detects_modified_content(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        original = "# Legit Skill"
        (skills_dir / "task.md").write_text("# INJECTED MALICIOUS CONTENT", encoding="utf-8")
        checksums = {"task.md": hashlib.sha256(original.encode("utf-8")).hexdigest()}

        violations = verify_skill_integrity(tmp_path, checksums)
        assert len(violations) == 1
        assert "tampered" in violations[0].lower()
        assert "task.md" in violations[0]

    def test_detects_missing_files(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        checksums = {"missing.md": "deadbeef" * 8}

        violations = verify_skill_integrity(tmp_path, checksums)
        assert len(violations) == 1
        assert "missing" in violations[0].lower()
        assert "missing.md" in violations[0]

    def test_detects_extra_files(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        content = "# Good Skill"
        (skills_dir / "good.md").write_text(content, encoding="utf-8")
        (skills_dir / "evil.md").write_text("# Evil injected", encoding="utf-8")
        checksums = {"good.md": hashlib.sha256(content.encode("utf-8")).hexdigest()}

        violations = verify_skill_integrity(tmp_path, checksums)
        assert len(violations) == 1
        assert "unexpected" in violations[0].lower()
        assert "evil.md" in violations[0]


class TestCreateWorkspaceChecksums:
    """Tests for checksum integration in create_workspace()."""

    def test_writes_checksums_file_when_skills_provided(self, workspace_dir):
        skills = {
            "search.md": "# Search Skill",
            "summarize.md": "# Summarize Skill",
        }
        ws = workspace_dir(skills=skills)
        checksum_path = ws / ".claude" / "skill_checksums.json"
        assert checksum_path.is_file()

        stored = json.loads(checksum_path.read_text(encoding="utf-8"))
        assert len(stored) == 2
        for filename, content in skills.items():
            expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
            assert stored[filename] == expected

    def test_no_checksums_file_when_no_skills(self, workspace_dir):
        ws = workspace_dir(skills=None)
        checksum_path = ws / ".claude" / "skill_checksums.json"
        assert not checksum_path.exists()

    def test_round_trip_create_then_verify(self, workspace_dir):
        skills = {
            "alpha.md": "Alpha skill content here.",
            "beta.md": "Beta skill content here.",
            "gamma.md": "Gamma skill content here.",
        }
        ws = workspace_dir(skills=skills)

        # Load stored checksums
        checksum_path = ws / ".claude" / "skill_checksums.json"
        stored_checksums = json.loads(checksum_path.read_text(encoding="utf-8"))

        # Verify integrity passes
        violations = verify_skill_integrity(ws, stored_checksums)
        assert violations == [], f"Unexpected violations: {violations}"


class TestSkillFilenameValidation:
    """Tests for path traversal prevention in skill filenames."""

    def test_rejects_dotdot_traversal(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with pytest.raises(ValueError, match="path separators"):
            _validate_skill_filename("../../../etc/passwd", skills_dir)

    def test_rejects_forward_slash(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with pytest.raises(ValueError, match="path separators"):
            _validate_skill_filename("subdir/evil.md", skills_dir)

    def test_rejects_backslash(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with pytest.raises(ValueError, match="path separators"):
            _validate_skill_filename("subdir\\evil.md", skills_dir)

    def test_rejects_empty_filename(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with pytest.raises(ValueError, match="empty"):
            _validate_skill_filename("", skills_dir)

    def test_accepts_normal_filename(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _validate_skill_filename("search-skill.md", skills_dir)

    def test_accepts_filename_with_dots(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        _validate_skill_filename("my.skill.v2.md", skills_dir)

    def test_create_workspace_rejects_traversal(self, workspace_dir):
        with pytest.raises(ValueError, match="path separators"):
            workspace_dir(skills={"../../../etc/passwd": "evil content"})
