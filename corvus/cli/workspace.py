"""Purpose-built workspace composition for agent sessions.

Creates a minimal, secure workspace containing only:
- .claude/settings.json (permissions.deny, plugins disabled)
- .claude/CLAUDE.md (tool docs, skills, instructions)
- skills/ (only skills this agent needs)

No source code, no .env, no config/, no credentials.
Uses tempfile.mkdtemp() with 0o700 permissions to prevent symlink attacks.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger("corvus-workspace")


def create_workspace(
    *,
    agent_name: str,
    session_id: str,
    settings_json: str,
    claude_md: str,
    skills: dict[str, str] | None = None,
    base_dir: str | None = None,
) -> Path:
    """Create a purpose-built workspace for an agent session.

    Args:
        agent_name: Name of the agent
        session_id: Unique session identifier
        settings_json: Content for .claude/settings.json
        claude_md: Content for .claude/CLAUDE.md
        skills: Optional dict of {filename: content} for skills/
        base_dir: Optional base directory (defaults to system temp)

    Returns:
        Path to the created workspace directory (0o700 permissions)
    """
    prefix = f"corvus-{agent_name}-{session_id[:8]}-"
    workspace = Path(tempfile.mkdtemp(prefix=prefix, dir=base_dir))

    # Ensure restrictive permissions
    os.chmod(workspace, 0o700)

    # .claude/ directory
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)

    (claude_dir / "settings.json").write_text(settings_json, encoding="utf-8")
    (claude_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    # Skills directory (only agent-specific skills)
    if skills:
        skills_dir = workspace / "skills"
        skills_dir.mkdir()
        for filename, content in skills.items():
            (skills_dir / filename).write_text(content, encoding="utf-8")

    logger.info(
        "Created workspace for %s at %s (session=%s)",
        agent_name, workspace, session_id,
    )
    return workspace


def cleanup_workspace(workspace: Path) -> None:
    """Remove a workspace directory and all its contents."""
    if not workspace.exists():
        return
    if not str(workspace).startswith(tempfile.gettempdir()):
        logger.error("Refusing to delete workspace outside temp dir: %s", workspace)
        return
    shutil.rmtree(workspace, ignore_errors=True)
    logger.info("Cleaned up workspace at %s", workspace)


def verify_workspace_integrity(workspace: Path) -> list[str]:
    """Verify workspace contains only expected files.

    Returns a list of violations (empty = clean).
    """
    violations: list[str] = []

    # Check for files that should NEVER be in a workspace
    forbidden_patterns = [".env", "credentials", ".ssh", ".key", ".pem", "passphrase"]
    for item in workspace.rglob("*"):
        if item.is_file():
            rel_path_lower = str(item.relative_to(workspace)).lower()
            for pattern in forbidden_patterns:
                if pattern in rel_path_lower:
                    violations.append(f"Forbidden file found: {item.relative_to(workspace)}")

    # Check permissions
    stat = os.stat(workspace)
    if stat.st_mode & 0o077:  # Any group/other permissions
        violations.append(f"Workspace permissions too open: {oct(stat.st_mode)}")

    return violations
