"""Obsidian vault writer — writes memories as properly formatted vault files.

Each saved memory file has:
- YAML frontmatter (tags, created, source, importance, aliases)
- Wiki-style [[internal links]] for cross-referencing
- Hierarchical tags (#domain/subtopic)
- Kebab-case filenames, organized into domain subfolders
"""

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

# Domain → vault subfolder mapping
DOMAIN_FOLDERS: dict[str, str] = {
    "personal": "personal",
    "work": "work",
    "homelab": "homelab",
    "finance": "finance",
    "music": "music",
    "email": "email",
    "docs": "docs",
    "home": "home",
    "shared": "shared",
}

# Content type → subfolder within domain
CONTENT_TYPE_FOLDERS: dict[str, str] = {
    "journal": "journal",
    "meeting": "meetings",
    "task": "tasks",
    "project": "projects",
    "runbook": "runbooks",
    "inventory": "inventory",
    "health": "health",
    "planning": "planning",
}


def slugify(title: str) -> str:
    """Convert a title to a kebab-case filename slug.

    - Lowercases, strips accents, replaces non-alphanumeric with hyphens
    - Collapses consecutive hyphens, strips leading/trailing hyphens
    """
    # Normalize unicode → ASCII decomposition, strip combining chars
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    # Replace non-alphanumeric (except hyphens) with hyphens
    slug = re.sub(r"[^a-z0-9-]", "-", lowered)
    # Collapse consecutive hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def generate_frontmatter(
    tags: list[str],
    source: str,
    importance: float = 0.5,
    aliases: list[str] | None = None,
    created: datetime | None = None,
) -> str:
    """Generate YAML frontmatter block for an Obsidian note."""
    created = created or datetime.now(UTC)
    created_str = created.strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = ["---"]
    # Format tags as YAML list
    tag_str = ", ".join(tags) if tags else ""
    lines.append(f"tags: [{tag_str}]")
    lines.append(f"created: {created_str}")
    lines.append(f"source: {source}")
    lines.append(f"importance: {importance}")
    if aliases:
        alias_str = ", ".join(aliases)
        lines.append(f"aliases: [{alias_str}]")
    lines.append("---")
    return "\n".join(lines)


def resolve_links(content: str) -> str:
    """Preserve existing [[wiki links]] and auto-link date references.

    Finds ISO date patterns (YYYY-MM-DD) not already inside [[ ]] and wraps
    them as [[YYYY-MM-DD]] for daily-note linking.
    """
    # Auto-link bare ISO dates not already inside wiki links
    # Negative lookbehind for [[ and negative lookahead for ]]
    content = re.sub(
        r"(?<!\[\[)(\d{4}-\d{2}-\d{2})(?!\]\])",
        r"[[\1]]",
        content,
    )
    return content


def route_to_folder(
    vault_root: Path,
    domain: str,
    content_type: str | None = None,
) -> Path:
    """Determine the correct vault subfolder for a given domain and content type."""
    domain_folder = DOMAIN_FOLDERS.get(domain, "shared")
    base = vault_root / domain_folder

    if content_type and content_type in CONTENT_TYPE_FOLDERS:
        return base / CONTENT_TYPE_FOLDERS[content_type]

    return base


def _build_hierarchical_tags(tags: list[str], domain: str) -> list[str]:
    """Ensure tags include the domain prefix and are hierarchical."""
    result: list[str] = []
    has_domain_tag = False

    for tag in tags:
        cleaned = tag.lstrip("#").strip()
        if not cleaned:
            continue
        # Check if any tag already starts with the domain
        if cleaned.startswith(f"{domain}/") or cleaned == domain:
            has_domain_tag = True
        result.append(cleaned)

    # Auto-add domain tag if missing
    if not has_domain_tag:
        result.insert(0, domain)

    return result


class VaultWriter:
    """Writes memory content to an Obsidian vault with proper formatting."""

    def __init__(self, vault_root: Path | str):
        self.vault_root = Path(vault_root)

    def save_to_vault(
        self,
        content: str,
        domain: str,
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        source: str | None = None,
        importance: float = 0.5,
        content_type: str | None = None,
        title: str | None = None,
        created: datetime | None = None,
    ) -> Path:
        """Save content to the Obsidian vault.

        Returns the Path of the written file.
        """
        created = created or datetime.now(UTC)
        source = source or f"claw-{domain}-agent"
        raw_tags = tags or []

        # Build hierarchical tags with domain prefix
        hier_tags = _build_hierarchical_tags(raw_tags, domain)

        # Resolve wiki links in content
        linked_content = resolve_links(content)

        # Generate frontmatter
        frontmatter = generate_frontmatter(
            tags=hier_tags,
            source=source,
            importance=importance,
            aliases=aliases,
            created=created,
        )

        # Determine output folder
        folder = route_to_folder(self.vault_root, domain, content_type)
        folder.mkdir(parents=True, exist_ok=True)

        # Determine filename
        filename = self._make_filename(title, content_type, created)
        file_path = folder / filename

        # For daily journals, append to existing file if one exists
        if content_type == "journal" and file_path.exists():
            self._append_to_daily_note(file_path, linked_content, created)
        else:
            full_content = f"{frontmatter}\n\n{linked_content}\n"
            file_path.write_text(full_content, encoding="utf-8")

        return file_path

    def _make_filename(
        self,
        title: str | None,
        content_type: str | None,
        created: datetime,
    ) -> str:
        """Generate a kebab-case filename."""
        date_str = created.strftime("%Y-%m-%d")

        if content_type == "journal":
            return f"{date_str}.md"

        if content_type == "meeting" and title:
            slug = slugify(title)
            return f"{date_str}-{slug}.md"

        if title:
            return f"{slugify(title)}.md"

        # Fallback: date + timestamp slug
        time_str = created.strftime("%H%M%S")
        return f"{date_str}-{time_str}.md"

    def _append_to_daily_note(
        self,
        file_path: Path,
        content: str,
        created: datetime,
    ) -> None:
        """Append a new entry to an existing daily note."""
        existing = file_path.read_text(encoding="utf-8")
        time_str = created.strftime("%H:%M")
        separator = f"\n\n---\n\n## {time_str}\n\n"
        file_path.write_text(existing + separator + content + "\n", encoding="utf-8")
