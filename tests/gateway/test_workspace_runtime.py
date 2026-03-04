"""Behavioral tests for isolated runtime workspaces."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from corvus.gateway.workspace_runtime import prepare_agent_workspace


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("source checkout\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@claw.local"],
        cwd=str(path),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Claw Tests"],
        cwd=str(path),
        check=True,
    )
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(path), check=True)


def _set_workspace_env(*, source: Path, root: Path) -> tuple[str | None, str | None]:
    old_source = os.environ.get("CORVUS_AGENT_WORKSPACE_SOURCE")
    old_root = os.environ.get("CORVUS_AGENT_WORKSPACE_ROOT")
    os.environ["CORVUS_AGENT_WORKSPACE_SOURCE"] = str(source)
    os.environ["CORVUS_AGENT_WORKSPACE_ROOT"] = str(root)
    return old_source, old_root


def _restore_workspace_env(old_source: str | None, old_root: str | None) -> None:
    if old_source is None:
        os.environ.pop("CORVUS_AGENT_WORKSPACE_SOURCE", None)
    else:
        os.environ["CORVUS_AGENT_WORKSPACE_SOURCE"] = old_source
    if old_root is None:
        os.environ.pop("CORVUS_AGENT_WORKSPACE_ROOT", None)
    else:
        os.environ["CORVUS_AGENT_WORKSPACE_ROOT"] = old_root


def test_prepare_agent_workspace_isolated_from_source_repo(tmp_path: Path) -> None:
    """Workspace edits must not mutate the source repository checkout."""
    if shutil.which("git") is None:
        pytest.skip("git is required for worktree workspace test")

    source = tmp_path / "source-repo"
    _init_git_repo(source)
    workspace_root = tmp_path / "agent-workspaces"

    old_source, old_root = _set_workspace_env(source=source, root=workspace_root)
    try:
        workspace = prepare_agent_workspace(session_id="sess/1", agent_name="@huginn")
        assert workspace.is_dir()
        assert workspace_root in workspace.parents
        assert workspace != source
        assert (workspace / "README.md").read_text(encoding="utf-8") == "source checkout\n"

        # Edit the isolated workspace and verify source checkout stays unchanged.
        (workspace / "README.md").write_text("workspace-only change\n", encoding="utf-8")
        assert (source / "README.md").read_text(encoding="utf-8") == "source checkout\n"

        # Re-request should be stable and return the same workspace path.
        workspace_again = prepare_agent_workspace(session_id="sess/1", agent_name="@huginn")
        assert workspace_again == workspace
    finally:
        _restore_workspace_env(old_source, old_root)


def test_prepare_agent_workspace_copies_non_git_source(tmp_path: Path) -> None:
    """Non-git source roots should still yield a populated isolated workspace."""
    source = tmp_path / "plain-source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "notes.txt").write_text("hello workspace\n", encoding="utf-8")
    workspace_root = tmp_path / "agent-workspaces"

    old_source, old_root = _set_workspace_env(source=source, root=workspace_root)
    try:
        workspace = prepare_agent_workspace(session_id="session two", agent_name="general")
        assert workspace.is_dir()
        assert workspace_root in workspace.parents
        assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello workspace\n"
    finally:
        _restore_workspace_env(old_source, old_root)


def test_prepare_agent_workspace_rehomes_root_when_inside_source(tmp_path: Path) -> None:
    """Workspace roots nested under source should be re-homed outside source."""
    if shutil.which("git") is None:
        pytest.skip("git is required for worktree workspace test")

    source = tmp_path / "source-repo"
    _init_git_repo(source)
    nested_workspace_root = source / "nested-workspaces"

    old_source, old_root = _set_workspace_env(source=source, root=nested_workspace_root)
    try:
        workspace = prepare_agent_workspace(session_id="session-a", agent_name="general")
        assert workspace.is_dir()
        assert source not in workspace.parents
    finally:
        _restore_workspace_env(old_source, old_root)
