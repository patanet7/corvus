#!/usr/bin/env python3
"""Rename claw -> corvus across the entire codebase.

This script performs the following replacements:
1. Python imports: from claw. -> from corvus., import claw. -> import corvus.
2. Module references: claw.server -> corvus.server, etc.
3. Logger names: claw-gateway -> corvus-gateway
4. Env var prefixes: CLAW_ -> CORVUS_
5. Package name: claw-gateway -> corvus-gateway
6. Directory: claw/ -> corvus/
7. pyproject.toml, mise.toml, Dockerfile references

Usage: python scripts/rename_claw_to_corvus.py [--dry-run]
"""

import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRY_RUN = "--dry-run" in sys.argv

# Files/dirs to skip
SKIP_DIRS = {".git", ".venv", "node_modules", ".svelte-kit", "storybook-static",
             "__pycache__", ".data", ".worktrees", "infra"}
SKIP_FILES = {"rename_claw_to_corvus.py"}  # Don't modify self


def should_process(path: Path) -> bool:
    """Check if file should be processed for replacements."""
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    if path.name in SKIP_FILES:
        return False
    suffix = path.suffix
    return suffix in {".py", ".ts", ".toml", ".yaml", ".yml", ".md", ".json",
                      ".conf", ".cfg", ".txt", ".svelte", ".html", ".css", ".js"}


# Ordered replacements — order matters (longer/more specific patterns first)
REPLACEMENTS = [
    # Python imports (must come before generic claw. replacement)
    (r"\bfrom claw\.", "from corvus."),
    (r"\bimport claw\.", "import corvus."),
    (r"\bimport claw\b", "import corvus"),

    # Module string references
    (r'"claw\.', '"corvus.'),
    (r"'claw\.", "'corvus."),

    # Logger / name references
    (r"\bclaw-gateway\b", "corvus-gateway"),

    # Env var prefixes
    (r"\bCLAW_CLAUDE_HOME\b", "CORVUS_CLAUDE_HOME"),
    (r"\bCLAW_CLAUDE_HOME_SCOPE\b", "CORVUS_CLAUDE_HOME_SCOPE"),
    (r"\bCLAW_ISOLATE_CLAUDE_HOME\b", "CORVUS_ISOLATE_CLAUDE_HOME"),
    (r"\bCLAW_CLAUDE_CONFIG_TEMPLATE\b", "CORVUS_CLAUDE_CONFIG_TEMPLATE"),
    (r"\bCLAW_BREAK_GLASS\b", "CORVUS_BREAK_GLASS"),
    (r"\bCLAW_DEV_REMOTE_USER\b", "CORVUS_DEV_REMOTE_USER"),

    # Package name in pyproject.toml
    (r'\bname = "claw-gateway"', 'name = "corvus-gateway"'),

    # Dockerfile COPY and CMD
    (r"\bCOPY claw/", "COPY corvus/"),
    (r"python -m claw\.server", "python -m corvus.server"),
    (r"python -m claw\.cli", "python -m corvus.cli"),

    # Config path references
    (r"\bclaw/Dockerfile\b", "Dockerfile"),
]

# Only apply to .py and .toml files — bare "claw" string references
PY_TOML_REPLACEMENTS = [
    (r'"claw"', '"corvus"'),
]

# Special handling for pyproject.toml package find
PYPROJECT_REPLACEMENTS = [
    ('where = ["claw"]', 'where = ["corvus"]'),
    ('include = ["claw", "claw.*"]', 'include = ["corvus", "corvus.*"]'),
    ('"claw"', '"corvus"'),
]


def apply_replacements(content: str, filepath: Path) -> str:
    """Apply all regex replacements to file content."""
    original = content

    # Special handling for pyproject.toml
    if filepath.name == "pyproject.toml":
        for old, new in PYPROJECT_REPLACEMENTS:
            content = content.replace(old, new)

    # Bare "claw" replacements only in Python/TOML files
    if filepath.suffix in {".py", ".toml"}:
        for pattern, replacement in PY_TOML_REPLACEMENTS:
            content = re.sub(pattern, replacement, content)

    for pattern, replacement in REPLACEMENTS:
        content = re.sub(pattern, replacement, content)

    return content


def process_file(filepath: Path) -> bool:
    """Process a single file. Returns True if modified."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return False

    new_content = apply_replacements(content, filepath)

    if new_content != content:
        if not DRY_RUN:
            filepath.write_text(new_content, encoding="utf-8")
        return True
    return False


def rename_directory() -> None:
    """Rename claw/ -> corvus/ directory."""
    src = REPO_ROOT / "claw"
    dst = REPO_ROOT / "corvus"

    if not src.exists():
        print(f"  SKIP: {src} does not exist (already renamed?)")
        return

    if dst.exists():
        print(f"  ERROR: {dst} already exists!")
        sys.exit(1)

    print(f"  {'WOULD RENAME' if DRY_RUN else 'RENAMING'}: claw/ -> corvus/")
    if not DRY_RUN:
        shutil.move(str(src), str(dst))


def main():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"\n=== Claw -> Corvus Rename ({mode}) ===\n")

    # Phase 1: Text replacements in all files
    print("Phase 1: Text replacements...")
    modified_count = 0
    for root, dirs, files in os.walk(REPO_ROOT):
        # Prune skip dirs
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in files:
            filepath = Path(root) / fname
            if not should_process(filepath):
                continue
            if process_file(filepath):
                rel = filepath.relative_to(REPO_ROOT)
                print(f"  MODIFIED: {rel}")
                modified_count += 1

    print(f"\n  {modified_count} files modified\n")

    # Phase 2: Rename directory
    print("Phase 2: Directory rename...")
    rename_directory()

    # Phase 3: Update internal __init__.py or module references if needed
    print("\nPhase 3: Post-rename verification...")
    if not DRY_RUN:
        corvus_dir = REPO_ROOT / "corvus"
        if corvus_dir.exists():
            # Verify key files exist
            for check in ["server.py", "__init__.py", "config.py", "agents/hub.py"]:
                target = corvus_dir / check
                status = "OK" if target.exists() else "MISSING"
                print(f"  {status}: corvus/{check}")

    print(f"\n=== Rename complete ({mode}) ===")
    if DRY_RUN:
        print("  Run without --dry-run to apply changes.")
    else:
        print("  Run tests to verify: uv run pytest tests/ -x -q")


if __name__ == "__main__":
    main()
