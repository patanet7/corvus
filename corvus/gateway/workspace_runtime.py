"""Isolated runtime workspaces for SDK agent runs.

Each session/agent pair gets a dedicated working directory so SDK tool calls
do not run against the live repository checkout by default.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from corvus.config import WORKSPACE_DIR

logger = logging.getLogger("corvus-gateway")

_WORKSPACE_ROOT_ENV = "CORVUS_AGENT_WORKSPACE_ROOT"
_WORKSPACE_SOURCE_ENV = "CORVUS_AGENT_WORKSPACE_SOURCE"
_SNAPSHOT_IGNORE = (
    ".git",
    ".venv",
    "node_modules",
    ".data",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "frontend/node_modules",
    "frontend/.svelte-kit",
    "frontend/storybook-static",
)


def _sanitize_fragment(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    token = token.strip("-.")
    return token or fallback


def _workspace_root() -> Path:
    raw = os.environ.get(_WORKSPACE_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (WORKSPACE_DIR / "agent-runs").resolve()


def _workspace_source_root() -> Path:
    raw = os.environ.get(_WORKSPACE_SOURCE_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # claw/gateway/workspace_runtime.py -> <repo-root>
    return Path(__file__).resolve().parents[2]


def _create_git_worktree(source_root: Path, workspace_dir: Path) -> None:
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(workspace_dir), "HEAD"],
        cwd=str(source_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "git worktree add failed")


def _copy_source_snapshot(source_root: Path, workspace_dir: Path) -> None:
    ignore = shutil.ignore_patterns(*_SNAPSHOT_IGNORE)
    shutil.copytree(source_root, workspace_dir, dirs_exist_ok=False, ignore=ignore)


def prepare_agent_workspace(*, session_id: str, agent_name: str) -> Path:
    """Return/create isolated workspace for a session+agent run context."""
    safe_session = _sanitize_fragment(session_id, fallback="session")
    safe_agent = _sanitize_fragment(agent_name, fallback="agent")
    source_root = _workspace_source_root()
    workspace_dir = _workspace_root() / safe_session / safe_agent

    # Never place runtime workspaces inside the source repo tree.
    if source_root == workspace_dir or source_root in workspace_dir.parents:
        fallback_root = source_root.parent / f".{source_root.name}-agent-runs"
        workspace_dir = fallback_root / safe_session / safe_agent

    if workspace_dir.is_dir():
        return workspace_dir
    if workspace_dir.exists() and not workspace_dir.is_dir():
        raise RuntimeError(f"Workspace path exists and is not a directory: {workspace_dir}")

    workspace_dir.parent.mkdir(parents=True, exist_ok=True)

    if not source_root.exists():
        logger.warning("Workspace source root missing (%s); using empty workspace", source_root)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir

    git_available = shutil.which("git") is not None and (source_root / ".git").exists()
    if git_available:
        try:
            _create_git_worktree(source_root, workspace_dir)
            return workspace_dir
        except Exception as exc:
            logger.warning(
                "Failed to create git worktree at %s (%s). Falling back to source snapshot copy.",
                workspace_dir,
                exc,
            )
            if workspace_dir.exists():
                shutil.rmtree(workspace_dir)

    try:
        _copy_source_snapshot(source_root, workspace_dir)
    except Exception:
        logger.exception("Failed to copy source snapshot to %s; using empty workspace", workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)

    return workspace_dir
