# Obsidian API Reference

## Path Format
Paths are relative to the vault root, e.g., `personal/daily/2026-03-08.md`.

## Search Response
Returns a list of matching notes with filename, relevance score, and matching context snippets.

## Write Behavior
- If the note exists: overwrites it entirely
- If the note doesn't exist: creates it (including parent directories)
- Content should be valid Markdown

## Prefix Restrictions
Your agent may be restricted to certain vault prefixes (e.g., `personal/`, `shared/`). Writing outside allowed prefixes will return an error.
