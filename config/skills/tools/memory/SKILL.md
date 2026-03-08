---
name: memory
description: Search, save, and manage agent memories. Use memory_search at the start of every conversation to recall context. Save important outcomes, preferences, and decisions.
allowed-tools: Bash(python *)
user-invocable: false
---

# Memory Tools

You have a private memory domain. Use these tools to persist context across sessions.

## Available Actions

Run via: `python .claude/skills/memory/scripts/memory.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `search` | `--query <text>` `--limit <int>` `--domain <name>` | Search memories by query (BM25 ranking) |
| `save` | `--content <text>` `--visibility private\|shared` `--tags <csv>` `--importance <0-1>` | Save a memory. importance >= 0.9 = evergreen (never decays) |
| `get` | `--record_id <uuid>` | Retrieve a specific memory by ID |
| `list` | `--domain <name>` `--limit <int>` | List recent memories |
| `forget` | `--record_id <uuid>` | Soft-delete a memory (own domain only) |

## When to Use

- **Start of every conversation**: `memory search --query "<user's first message>"`
- **After decisions**: `memory save --content "Decided to use React" --importance 0.7 --tags "decision"`
- **User preferences**: `memory save --content "Thomas prefers dark mode" --importance 0.9 --visibility shared`
- **Before asking the user to repeat**: always search first
