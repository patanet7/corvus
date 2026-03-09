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
    # Security-sensitive files — must never leak into agent workspaces
    ".env",
    ".env.*",
    "config",
    "CLAUDE.md",
    "*.hash",
    "lockout.json",
    ".corvus",
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
    # corvus/gateway/workspace_runtime.py -> <repo-root>
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


def cleanup_agent_workspace(*, session_id: str, agent_name: str) -> None:
    """Remove a single agent worktree/workspace after a run completes."""
    safe_session = _sanitize_fragment(session_id, fallback="session")
    safe_agent = _sanitize_fragment(agent_name, fallback="agent")
    source_root = _workspace_source_root()
    workspace_dir = _workspace_root() / safe_session / safe_agent

    # Mirror the fallback logic from prepare_agent_workspace
    if source_root == workspace_dir or source_root in workspace_dir.parents:
        fallback_root = source_root.parent / f".{source_root.name}-agent-runs"
        workspace_dir = fallback_root / safe_session / safe_agent

    if not workspace_dir.exists():
        return

    git_dir = source_root / ".git"
    if git_dir.exists() and shutil.which("git"):
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(workspace_dir)],
            cwd=str(source_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.debug("Removed git worktree: %s", workspace_dir)
        else:
            # Worktree remove failed — fall back to rmtree
            logger.warning(
                "git worktree remove failed for %s (%s); falling back to rmtree",
                workspace_dir,
                (result.stderr or "").strip(),
            )
            shutil.rmtree(workspace_dir, ignore_errors=True)
    else:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        logger.debug("Removed snapshot workspace: %s", workspace_dir)

    # Clean up empty session directory
    session_dir = workspace_dir.parent
    if session_dir.is_dir() and not any(session_dir.iterdir()):
        session_dir.rmdir()
        logger.debug("Removed empty session dir: %s", session_dir)


def cleanup_session_workspaces(*, session_id: str) -> None:
    """Remove all agent workspaces for a session."""
    safe_session = _sanitize_fragment(session_id, fallback="session")
    source_root = _workspace_source_root()
    session_dir = _workspace_root() / safe_session

    # Mirror the fallback logic from prepare_agent_workspace
    if source_root == session_dir or source_root in session_dir.parents:
        fallback_root = source_root.parent / f".{source_root.name}-agent-runs"
        session_dir = fallback_root / safe_session

    if not session_dir.is_dir():
        return

    git_dir = source_root / ".git"
    use_git = git_dir.exists() and shutil.which("git") is not None

    for agent_dir in list(session_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        if use_git:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(agent_dir)],
                cwd=str(source_root),
                capture_output=True,
                text=True,
            )
        shutil.rmtree(agent_dir, ignore_errors=True)

    shutil.rmtree(session_dir, ignore_errors=True)
    logger.info("Cleaned up session workspaces: %s", session_dir)


def prune_stale_worktrees() -> int:
    """Prune only genuinely stale git worktree references.

    SAFETY: Only removes worktrees whose directories no longer exist on disk.
    Never force-removes active worktrees — those belong to running sessions
    or developer worktrees (e.g. .worktrees/ created by git-worktree skills).

    Previous version had a critical bug: it treated ALL non-main worktrees
    as stale and force-removed them, destroying active work.
    """
    source_root = _workspace_source_root()
    git_dir = source_root / ".git"
    if not git_dir.exists() or not shutil.which("git"):
        return 0

    # Only prune orphaned metadata — directories that no longer exist.
    # This is exactly what `git worktree prune` does safely.
    result = subprocess.run(
        ["git", "worktree", "prune", "--verbose"],
        cwd=str(source_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0

    # Count pruned entries from verbose output
    removed = sum(1 for line in result.stdout.splitlines() if line.startswith("Removing"))
    if removed:
        logger.info("Pruned %d stale worktrees", removed)
    return removed


def copy_agent_skills(
    agent_name: str,
    config_dir: Path,
    workspace_dir: Path,
    shared_skills: list[str] | None = None,
    tool_modules: list[str] | None = None,
) -> None:
    """Copy agent-specific, shared, and tool skills into workspace .claude/skills/."""
    skills_dest = workspace_dir / ".claude" / "skills"

    # Agent-specific skills (flat .md files)
    agent_skills_dir = config_dir / "config" / "agents" / agent_name / "skills"
    if agent_skills_dir.is_dir():
        skills_dest.mkdir(parents=True, exist_ok=True)
        for skill_file in agent_skills_dir.glob("*.md"):
            shutil.copy2(skill_file, skills_dest / skill_file.name)

    # Shared skills (flat .md files)
    if shared_skills:
        shared_dir = config_dir / "config" / "skills" / "shared"
        if shared_dir.is_dir():
            skills_dest.mkdir(parents=True, exist_ok=True)
            for skill_name in shared_skills:
                src = shared_dir / f"{skill_name}.md"
                if src.exists():
                    shutil.copy2(src, skills_dest / src.name)
                else:
                    logger.warning("Shared skill '%s' not found at %s", skill_name, src)

    # Tool skills (directory-based, with scripts/)
    tools_src = config_dir / "config" / "skills" / "tools"
    if tools_src.is_dir():
        # Always include memory
        modules_to_copy = set(tool_modules or [])
        modules_to_copy.add("memory")

        for module_name in modules_to_copy:
            src_dir = tools_src / module_name
            if src_dir.is_dir():
                dest_dir = skills_dest / module_name
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(src_dir, dest_dir)

        # Copy shared client library
        lib_src = tools_src / "_lib"
        if lib_src.is_dir():
            lib_dest = skills_dest / "_lib"
            if lib_dest.exists():
                shutil.rmtree(lib_dest)
            shutil.copytree(lib_src, lib_dest)
