---
name: email
description: Search, read, draft, and send emails via Gmail and Yahoo. Manage labels and archive messages.
allowed-tools: Bash(python *)
user-invocable: false
---

# Email Tools

Manage email across Gmail and Yahoo accounts.

## Available Actions

Run via: `python .claude/skills/email/scripts/email.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `list` | `--query <search>` `--account <gmail\|yahoo>` `--limit <int>` | Search emails by query |
| `read` | `--message_id <id>` `--account <gmail\|yahoo>` | Read a full email message by ID |
| `draft` | `--to <email>` `--subject <text>` `--body <text>` `--account gmail` | Create a Gmail draft |
| `send` | `--to <email>` `--subject <text>` `--body <text>` `--account gmail` | Send an email. **Requires confirmation.** |
| `archive` | `--message_id <id>` `--account gmail` | Archive a message. **Requires confirmation.** |
| `label` | `--message_id <id>` `--add <label>` `--remove <label>` `--account gmail` | Add or remove labels |
| `labels` | `--account gmail` | List available Gmail labels |
