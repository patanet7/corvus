---
name: obsidian
description: Search, read, and write notes in the Obsidian vault. Use when the user asks about notes, knowledge base, journal entries, or documentation.
allowed-tools: Bash(python *)
user-invocable: false
---

# Obsidian Vault Tools

Access the Obsidian vault for note management. For detailed API information, see [reference.md](reference.md).

## Available Actions

Run via: `python .claude/skills/obsidian/scripts/obsidian.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `search` | `--query <text>` `--context_length <int>` | Full-text search across vault notes |
| `read` | `--path <note/path.md>` | Read a note (content + frontmatter) |
| `write` | `--path <note/path.md>` `--content <text>` | Create or overwrite a note |
| `append` | `--path <note/path.md>` `--content <text>` | Append content to an existing note |
