---
name: paperless
description: Search, read, tag, and bulk-edit documents in Paperless-ngx document management system.
allowed-tools: Bash(python *)
user-invocable: false
---

# Paperless-ngx Document Tools

Access the Paperless-ngx document management system. For detailed API information, see [reference.md](reference.md).

## Available Actions

Run via: `python .claude/skills/paperless/scripts/paperless.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `search` | `--query <text>` `--tag <name>` `--limit <int>` | Search documents by query with optional tag filter |
| `read` | `--id <int>` | Read a single document by ID |
| `tags` | *(none)* | List all available tags |
| `tag` | `--id <int>` `--tag <name>` | Add a tag to a document. **Requires confirmation.** |
| `bulk_edit` | `--documents <json-list>` `--method <method>` `--parameters <json>` | Batch tag/correspondent changes. **Requires confirmation.** |
