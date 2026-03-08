---
name: firefly
description: Query financial transactions, accounts, categories, and summaries from Firefly III. Create new transactions.
allowed-tools: Bash(python *)
user-invocable: false
---

# Firefly III Finance Tools

Access the Firefly III personal finance manager. For detailed API information, see [reference.md](reference.md).

## Available Actions

Run via: `python .claude/skills/firefly/scripts/firefly.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `transactions` | `--start <YYYY-MM-DD>` `--end <YYYY-MM-DD>` `--limit <int>` `--type <type>` | Query transactions with optional date/type filters |
| `accounts` | `--type <type>` | List accounts (asset, expense, revenue, etc.) |
| `categories` | *(none)* | List spending categories |
| `summary` | `--start <YYYY-MM-DD>` `--end <YYYY-MM-DD>` | Get spending summary for a date range (defaults to current month) |
| `create_transaction` | `--description <text>` `--amount <number>` `--type <withdrawal\|deposit\|transfer>` `--source_name <name>` `--destination_name <name>` `--category_name <name>` `--date <YYYY-MM-DD>` `--currency_code <code>` | Create a transaction. **Requires confirmation.** |
