---
name: drive
description: List, read, create, edit, and manage files in Google Drive and Google Docs.
allowed-tools: Bash(python *)
user-invocable: false
---

# Google Drive Tools

Access Google Drive for file management and Google Docs editing.

## Available Actions

Run via: `python .claude/skills/drive/scripts/drive.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `list` | `--query <text>` `--folder_id <id>` `--limit <int>` `--account <name>` | List or search files |
| `read` | `--file_id <id>` `--account <name>` | Read file metadata and content (Docs as text, Sheets as CSV) |
| `create` | `--name <text>` `--mime_type <type>` `--folder_id <id>` `--account <name>` | Create a file or Google Doc |
| `edit` | `--file_id <id>` `--insertions <json>` `--replacements <json>` `--account <name>` | Edit a Google Doc via batchUpdate |
| `move` | `--file_id <id>` `--folder_id <id>` `--account <name>` | Move a file to a different folder |
| `delete` | `--file_id <id>` `--account <name>` | Move a file to trash. **Requires confirmation.** |
| `permanent_delete` | `--file_id <id>` `--account <name>` | Permanently delete a file. **Requires confirmation.** |
| `share` | `--file_id <id>` `--email <address>` `--role <reader\|writer>` `--account <name>` | Share a file. **Requires confirmation.** |
| `cleanup` | `--older_than <days>` `--query <text>` `--dry_run <true\|false>` `--account <name>` | Find and trash old files. **Requires confirmation unless dry_run.** |
