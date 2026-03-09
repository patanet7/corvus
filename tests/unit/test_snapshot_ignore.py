"""Behavioral tests for workspace snapshot ignore list.

Verifies that security-sensitive files and directories are excluded from
agent workspace snapshots, preventing secret leakage into isolated
agent working directories.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from corvus.gateway.workspace_runtime import _SNAPSHOT_IGNORE, _copy_source_snapshot


class TestSnapshotIgnoreEntries:
    """Verify that _SNAPSHOT_IGNORE contains all required sensitive entries."""

    def test_env_file_in_ignore_list(self) -> None:
        assert ".env" in _SNAPSHOT_IGNORE

    def test_env_variants_in_ignore_list(self) -> None:
        assert ".env.*" in _SNAPSHOT_IGNORE

    def test_config_dir_in_ignore_list(self) -> None:
        assert "config" in _SNAPSHOT_IGNORE

    def test_claude_md_in_ignore_list(self) -> None:
        assert "CLAUDE.md" in _SNAPSHOT_IGNORE

    def test_hash_files_in_ignore_list(self) -> None:
        assert "*.hash" in _SNAPSHOT_IGNORE

    def test_lockout_json_in_ignore_list(self) -> None:
        assert "lockout.json" in _SNAPSHOT_IGNORE

    def test_corvus_dot_dir_in_ignore_list(self) -> None:
        assert ".corvus" in _SNAPSHOT_IGNORE

    def test_git_dir_in_ignore_list(self) -> None:
        assert ".git" in _SNAPSHOT_IGNORE

    def test_venv_in_ignore_list(self) -> None:
        assert ".venv" in _SNAPSHOT_IGNORE


class TestSnapshotCopyExcludesSensitiveFiles:
    """Verify that _copy_source_snapshot actually excludes sensitive files on disk."""

    def test_sensitive_files_not_copied(self) -> None:
        """Create a fake source tree with sensitive files, snapshot it,
        and confirm the sensitive entries are absent from the copy."""
        source = Path(tempfile.mkdtemp())
        dest = Path(tempfile.mkdtemp()) / "workspace"
        try:
            # Create benign files that should be copied
            (source / "corvus").mkdir()
            (source / "corvus" / "server.py").write_text("# server")
            (source / "pyproject.toml").write_text("[project]")

            # Create sensitive files/dirs that must NOT be copied
            (source / ".env").write_text("SECRET_KEY=abc123")
            (source / ".env.production").write_text("PROD_KEY=xyz")
            (source / "CLAUDE.md").write_text("instructions")
            (source / "lockout.json").write_text("{}")
            (source / "passphrase.hash").write_text("hash-value")
            (source / "config").mkdir()
            (source / "config" / "models.yaml").write_text("models:")
            (source / ".corvus").mkdir()
            (source / ".corvus" / "state.db").write_text("data")
            (source / ".git").mkdir()
            (source / ".git" / "HEAD").write_text("ref: refs/heads/main")

            _copy_source_snapshot(source, dest)

            # Benign files should exist
            assert (dest / "corvus" / "server.py").exists()
            assert (dest / "pyproject.toml").exists()

            # Sensitive files and directories must be absent
            assert not (dest / ".env").exists(), ".env was copied into workspace"
            assert not (dest / ".env.production").exists(), ".env.production was copied into workspace"
            assert not (dest / "CLAUDE.md").exists(), "CLAUDE.md was copied into workspace"
            assert not (dest / "lockout.json").exists(), "lockout.json was copied into workspace"
            assert not (dest / "passphrase.hash").exists(), "passphrase.hash was copied into workspace"
            assert not (dest / "config").exists(), "config/ was copied into workspace"
            assert not (dest / ".corvus").exists(), ".corvus/ was copied into workspace"
            assert not (dest / ".git").exists(), ".git/ was copied into workspace"
        finally:
            shutil.rmtree(source, ignore_errors=True)
            shutil.rmtree(dest.parent if dest.parent != Path("/") else dest, ignore_errors=True)
