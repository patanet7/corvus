#!/usr/bin/env python3
"""Background re-indexer: scan Obsidian vault, chunk, and update FTS5 + Cognee.

Usage:
    python scripts/reindex.py --vault-dir /mnt/vaults --db /data/memory/main.sqlite
    python scripts/reindex.py --dry-run
    python scripts/reindex.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

from scripts.common.cognee_engine import CogneeEngine
from scripts.common.memory_engine import init_db

logger = logging.getLogger("reindexer")

DOMAIN_FOLDERS = {
    "personal",
    "work",
    "homelab",
    "finance",
    "music",
    "email",
    "docs",
    "home",
    "shared",
}


def file_hash(path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (words * 1.3)."""
    return int(len(text.split()) * 1.3)


def strip_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    """Strip YAML frontmatter, return (body, metadata)."""
    if not text.startswith("---"):
        return text, {}
    end = text.find("---", 3)
    if end == -1:
        return text, {}
    frontmatter_text = text[3:end].strip()
    body = text[end + 3 :].strip()
    # Simple key:value parsing (no full YAML dependency)
    metadata: dict[str, str] = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()
    return body, metadata


def chunk_markdown(text: str, target_tokens: int = 500) -> list[str]:
    """Split markdown into ~500-token chunks at heading boundaries."""
    body, _ = strip_frontmatter(text)
    if not body.strip():
        return []

    # Split by h2 headings
    sections = _split_by_heading(body, "## ")

    chunks: list[str] = []
    for section in sections:
        if estimate_tokens(section) <= target_tokens * 1.2:
            chunks.append(section.strip())
        else:
            # Split further by h3
            subsections = _split_by_heading(section, "### ")
            for sub in subsections:
                if estimate_tokens(sub) <= target_tokens * 1.2:
                    chunks.append(sub.strip())
                else:
                    # Split by paragraphs
                    paragraphs = sub.split("\n\n")
                    current = ""
                    for para in paragraphs:
                        if estimate_tokens(current + para) > target_tokens:
                            if current.strip():
                                chunks.append(current.strip())
                            current = para
                        else:
                            current += "\n\n" + para if current else para
                    if current.strip():
                        chunks.append(current.strip())

    return [c for c in chunks if c.strip()]


def _split_by_heading(text: str, heading_prefix: str) -> list[str]:
    """Split text by heading markers, keeping the heading with its section."""
    parts = text.split(f"\n{heading_prefix}")
    result = [parts[0]]
    for part in parts[1:]:
        result.append(f"{heading_prefix}{part}")
    return result


def infer_domain(file_path: Path, vault_root: Path) -> str | None:
    """Infer domain from vault subfolder path."""
    try:
        relative = file_path.relative_to(vault_root)
        top_folder = relative.parts[0] if relative.parts else None
        if top_folder and top_folder in DOMAIN_FOLDERS:
            return top_folder
    except ValueError:
        pass
    return None


def reindex(
    vault_dir: Path,
    db_path: Path,
    dry_run: bool = False,
    force: bool = False,
    domain_filter: str | None = None,
    cognee_enabled: bool = True,
) -> dict[str, int | float | list[str]]:
    """Scan vault, chunk, and update index. Returns stats dict."""
    start = time.time()
    stats: dict[str, int | float | list[str]] = {
        "scanned": 0,
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "chunks_created": 0,
        "cognee_indexed": 0,
        "errors": [],
    }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)

    cognee = CogneeEngine() if cognee_enabled else None

    # Scan all .md files
    md_files = sorted(vault_dir.rglob("*.md"))
    if domain_filter:
        md_files = [f for f in md_files if infer_domain(f, vault_dir) == domain_filter]

    indexed_paths: set[str] = set()
    errors: list[str] = []

    for md_file in md_files:
        stats["scanned"] = int(stats["scanned"]) + 1
        relative_path = str(md_file.relative_to(vault_dir))

        try:
            current_hash = file_hash(md_file)
        except OSError as e:
            errors.append(f"Cannot read {relative_path}: {e}")
            continue

        # Check existing hash
        row = conn.execute("SELECT hash FROM files WHERE path = ?", (relative_path,)).fetchone()

        if row and row["hash"] == current_hash and not force:
            stats["unchanged"] = int(stats["unchanged"]) + 1
            indexed_paths.add(relative_path)
            continue

        # File is new or changed
        is_new = row is None
        if is_new:
            stats["new"] = int(stats["new"]) + 1
        else:
            stats["updated"] = int(stats["updated"]) + 1

        if dry_run:
            indexed_paths.add(relative_path)
            continue

        # Read and chunk
        try:
            text = md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            errors.append(f"Encoding error {relative_path}: {e}")
            continue

        chunks = chunk_markdown(text)
        if not chunks:
            # Update files table even if no chunks (e.g., empty frontmatter-only file)
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            conn.execute(
                "INSERT OR REPLACE INTO files (path, hash, last_indexed) VALUES (?, ?, ?)",
                (relative_path, current_hash, now_iso),
            )
            conn.commit()
            indexed_paths.add(relative_path)
            continue

        # Delete old chunks for this file
        conn.execute("DELETE FROM chunks WHERE file_path = ?", (relative_path,))
        # Delete old FTS entries
        conn.execute("DELETE FROM chunks_fts WHERE file_path = ?", (relative_path,))

        # Insert new chunks
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for idx, chunk in enumerate(chunks):
            cursor = conn.execute(
                "INSERT INTO chunks (content, file_path, chunk_index, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (chunk, relative_path, idx, now_iso, now_iso),
            )
            chunk_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO chunks_fts(rowid, content, file_path) VALUES (?, ?, ?)",
                (chunk_id, chunk, relative_path),
            )
            stats["chunks_created"] = int(stats["chunks_created"]) + 1

        # Update files table
        conn.execute(
            "INSERT OR REPLACE INTO files (path, hash, last_indexed) VALUES (?, ?, ?)",
            (relative_path, current_hash, now_iso),
        )

        # Cognee indexing
        domain = infer_domain(md_file, vault_dir)
        if cognee and cognee.is_available and domain:
            try:
                import asyncio

                asyncio.run(cognee.index(text, domain))
                stats["cognee_indexed"] = int(stats["cognee_indexed"]) + 1
            except Exception as e:
                errors.append(f"Cognee indexing failed for {relative_path}: {e}")

        indexed_paths.add(relative_path)
        conn.commit()

    conn.close()
    stats["errors"] = errors
    stats["duration_seconds"] = round(time.time() - start, 2)
    return stats


def main() -> None:
    """CLI entry point for the background re-indexer."""
    parser = argparse.ArgumentParser(description="Re-index Obsidian vault into FTS5 + Cognee")
    parser.add_argument("--vault-dir", type=Path, default=Path("/mnt/vaults"))
    parser.add_argument("--db", type=Path, default=Path("/data/memory/main.sqlite"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--domain", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    stats = reindex(
        vault_dir=args.vault_dir,
        db_path=args.db,
        dry_run=args.dry_run,
        force=args.force,
        domain_filter=args.domain,
    )

    print(json.dumps(stats, indent=2))
    sys.exit(1 if stats["errors"] else 0)


if __name__ == "__main__":
    main()
