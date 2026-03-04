#!/usr/bin/env python3
"""Obsidian vault CLI — called by agent via Bash tool.

Direct filesystem operations on the Obsidian vault (no REST API).

Usage:
    python scripts/obsidian.py search "<query>" [--domain DOMAIN] [--limit N]
    python scripts/obsidian.py read "<note_path>"
    python scripts/obsidian.py list [--domain DOMAIN] [--tag TAG]
    python scripts/obsidian.py recent [--days N] [--domain DOMAIN]
    python scripts/obsidian.py create "<content>" --domain DOMAIN --title TITLE [--tags tag1,tag2]
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from scripts.common.vault_writer import DOMAIN_FOLDERS, VaultWriter


def get_vault_root() -> Path:
    """Return the vault root from MEMORY_DIR env var."""
    vault_root = os.environ.get("MEMORY_DIR", "/mnt/vaults")
    return Path(vault_root)


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        parsed = yaml.safe_load(parts[1])
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        return {}


def _strip_frontmatter(text: str) -> str:
    """Return the body of a markdown file, stripping frontmatter."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2].strip()


def _note_to_dict(file_path: Path, vault_root: Path) -> dict:
    """Convert a vault note file to a JSON-serializable dict."""
    text = file_path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(text)
    body = _strip_frontmatter(text)
    rel_path = str(file_path.relative_to(vault_root))
    stat = file_path.stat()

    return {
        "path": rel_path,
        "title": file_path.stem,
        "frontmatter": frontmatter,
        "body": body,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "size_bytes": stat.st_size,
    }


def _collect_notes(vault_root: Path, domain: str | None = None) -> list[Path]:
    """Collect all .md files under the vault root, optionally filtered by domain."""
    if domain:
        folder_name = DOMAIN_FOLDERS.get(domain, domain)
        search_root = vault_root / folder_name
        if not search_root.is_dir():
            return []
        return sorted(search_root.rglob("*.md"))
    return sorted(vault_root.rglob("*.md"))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> None:
    """Search vault notes by query string (filename + frontmatter + body)."""
    vault_root = get_vault_root()
    if not vault_root.is_dir():
        print(json.dumps({"error": f"Vault directory not found: {vault_root}"}), file=sys.stderr)
        sys.exit(1)

    query_lower = args.query.lower()
    notes = _collect_notes(vault_root, domain=args.domain)

    matches: list[dict] = []
    for note_path in notes:
        try:
            text = note_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        text_lower = text.lower()
        filename_lower = note_path.stem.lower()

        # Score: filename match > frontmatter tag match > body match
        score = 0.0
        if query_lower in filename_lower:
            score += 3.0
        frontmatter = _parse_frontmatter(text)
        tags = frontmatter.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if query_lower in str(tag).lower():
                    score += 2.0
                    break
        if query_lower in text_lower:
            score += 1.0

        if score > 0:
            matches.append(
                {
                    "path": str(note_path.relative_to(vault_root)),
                    "title": note_path.stem,
                    "score": round(score, 2),
                    "frontmatter": frontmatter,
                    "modified": datetime.fromtimestamp(note_path.stat().st_mtime, tz=UTC).isoformat(),
                }
            )

    # Sort by score descending, then by modified descending
    matches.sort(key=lambda m: (-m["score"], m["modified"]), reverse=False)
    matches = matches[: args.limit]
    print(json.dumps(matches, indent=2, default=str))


def cmd_read(args: argparse.Namespace) -> None:
    """Read a specific vault note by path."""
    vault_root = get_vault_root()
    target = vault_root / args.note_path

    # Prevent path traversal
    try:
        target.resolve().relative_to(vault_root.resolve())
    except ValueError:
        print(json.dumps({"error": "Path traversal not allowed"}), file=sys.stderr)
        sys.exit(1)

    if not target.is_file():
        print(json.dumps({"error": f"Note not found: {args.note_path}"}), file=sys.stderr)
        sys.exit(1)

    result = _note_to_dict(target, vault_root)
    print(json.dumps(result, indent=2, default=str))


def cmd_list(args: argparse.Namespace) -> None:
    """List vault notes, optionally filtered by domain and/or tag."""
    vault_root = get_vault_root()
    if not vault_root.is_dir():
        print(json.dumps({"error": f"Vault directory not found: {vault_root}"}), file=sys.stderr)
        sys.exit(1)

    notes = _collect_notes(vault_root, domain=args.domain)

    results: list[dict] = []
    for note_path in notes:
        try:
            text = note_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        frontmatter = _parse_frontmatter(text)

        # Filter by tag if specified
        if args.tag:
            tags = frontmatter.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tag_strs = [str(t).lower() for t in tags]
            if not any(args.tag.lower() in t for t in tag_strs):
                continue

        results.append(
            {
                "path": str(note_path.relative_to(vault_root)),
                "title": note_path.stem,
                "frontmatter": frontmatter,
                "modified": datetime.fromtimestamp(note_path.stat().st_mtime, tz=UTC).isoformat(),
            }
        )

    print(json.dumps(results, indent=2, default=str))


def cmd_recent(args: argparse.Namespace) -> None:
    """List recently modified vault notes."""
    vault_root = get_vault_root()
    if not vault_root.is_dir():
        print(json.dumps({"error": f"Vault directory not found: {vault_root}"}), file=sys.stderr)
        sys.exit(1)

    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    cutoff_ts = cutoff.timestamp()

    notes = _collect_notes(vault_root, domain=args.domain)

    results: list[dict] = []
    for note_path in notes:
        stat = note_path.stat()
        if stat.st_mtime < cutoff_ts:
            continue

        try:
            text = note_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        frontmatter = _parse_frontmatter(text)
        results.append(
            {
                "path": str(note_path.relative_to(vault_root)),
                "title": note_path.stem,
                "frontmatter": frontmatter,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )

    # Sort by modified descending (most recent first)
    results.sort(key=lambda r: r["modified"], reverse=True)
    print(json.dumps(results, indent=2, default=str))


def cmd_create(args: argparse.Namespace) -> None:
    """Create a new vault note using VaultWriter."""
    vault_root = get_vault_root()
    writer = VaultWriter(vault_root)

    tags = args.tags.split(",") if args.tags else []
    tags = [t.strip() for t in tags if t.strip()]

    path = writer.save_to_vault(
        content=args.content,
        domain=args.domain,
        tags=tags,
        title=args.title,
        content_type=args.content_type,
        importance=args.importance,
    )

    rel_path = str(path.relative_to(vault_root))
    print(
        json.dumps(
            {
                "status": "created",
                "path": rel_path,
                "title": path.stem,
                "domain": args.domain,
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and dispatch to subcommand handler."""
    parser = argparse.ArgumentParser(description="Obsidian vault CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search vault notes")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--domain", default=None, help="Filter by domain")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")

    # read
    p_read = sub.add_parser("read", help="Read a vault note")
    p_read.add_argument("note_path", help="Relative path to note within vault")

    # list
    p_list = sub.add_parser("list", help="List vault notes")
    p_list.add_argument("--domain", default=None, help="Filter by domain")
    p_list.add_argument("--tag", default=None, help="Filter by tag")

    # recent
    p_recent = sub.add_parser("recent", help="Recently modified notes")
    p_recent.add_argument("--days", type=int, default=7, help="Look-back days")
    p_recent.add_argument("--domain", default=None, help="Filter by domain")

    # create
    p_create = sub.add_parser("create", help="Create a new vault note")
    p_create.add_argument("content", help="Note content")
    p_create.add_argument("--domain", required=True, help="Domain (personal, work, homelab, ...)")
    p_create.add_argument("--title", required=True, help="Note title")
    p_create.add_argument("--tags", default=None, help="Comma-separated tags")
    p_create.add_argument(
        "--content-type", default=None, dest="content_type", help="Content type (journal, meeting, note, ...)"
    )
    p_create.add_argument("--importance", type=float, default=0.5, help="Importance 0.0-1.0")

    args = parser.parse_args()

    handlers = {
        "search": cmd_search,
        "read": cmd_read,
        "list": cmd_list,
        "recent": cmd_recent,
        "create": cmd_create,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
