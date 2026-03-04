"""Behavioral tests for SDK workspace option wiring."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from corvus.gateway.options import apply_workspace_context


def test_apply_workspace_context_sets_cwd_and_adds_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "agent"
    workspace.mkdir(parents=True, exist_ok=True)
    opts = ClaudeAgentOptions(add_dirs=[])

    apply_workspace_context(opts, workspace_cwd=workspace)

    assert opts.cwd == workspace.resolve()
    assert str(opts.add_dirs[0]) == str(workspace.resolve())


def test_apply_workspace_context_dedupes_existing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "agent"
    workspace.mkdir(parents=True, exist_ok=True)
    opts = ClaudeAgentOptions(add_dirs=[workspace])

    apply_workspace_context(opts, workspace_cwd=workspace)

    normalized = [str(Path(entry).resolve()) for entry in opts.add_dirs]
    assert normalized.count(str(workspace.resolve())) == 1
