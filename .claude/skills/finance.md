# Finance — Firefly III + YNAB

You have access to two personal finance systems: **Firefly III** (self-hosted transaction tracker) and **YNAB** (You Need A Budget). Use them to query transactions, accounts, budgets, categories, and spending summaries.

---

## Firefly III Commands

### Listing transactions

Run: `python /app/scripts/finance.py transactions [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--limit N] [--type withdrawal|deposit|transfer]`

Returns JSON array with fields: `id`, `date`, `description`, `amount`, `currency_code`, `type`, `source`, `destination`, `category`, `budget`.

Examples:
- Recent transactions: `python /app/scripts/finance.py transactions --limit 20`
- This month's expenses: `python /app/scripts/finance.py transactions --from 2026-02-01 --to 2026-02-28 --type withdrawal`
- Income this year: `python /app/scripts/finance.py transactions --from 2026-01-01 --type deposit`

### Listing accounts

Run: `python /app/scripts/finance.py accounts [--type asset|expense|revenue|liability]`

Returns JSON array with fields: `id`, `name`, `type`, `current_balance`, `currency_code`, `active`.

### Viewing budgets

Run: `python /app/scripts/finance.py budgets [--month YYYY-MM]`

Returns JSON array with fields: `id`, `name`, `active`, `spent`, `currency_code`.

### Spending summary

Run: `python /app/scripts/finance.py summary [--start YYYY-MM-DD] [--end YYYY-MM-DD]`

Returns JSON object with keys like `balance-in-USD`, `spent-in-USD`, `earned-in-USD` — each with `value`, `currency_code`, and `label`. Defaults to current month if dates are omitted.

---

## YNAB Commands

### Listing budgets

Run: `python /app/scripts/finance.py ynab-budgets`

Returns JSON array with fields: `id`, `name`, `currency_format`, `last_modified`.

### Listing transactions

Run: `python /app/scripts/finance.py ynab-transactions [--budget BUDGET_NAME] [--since YYYY-MM-DD]`

Returns JSON array with fields: `id`, `date`, `payee`, `amount`, `memo`, `category`, `account`, `cleared`, `approved`.

- `--budget` resolves by name (case-insensitive). Omit to use the last-used budget.
- Amounts are converted from YNAB milliunits to decimal strings.

### Listing accounts

Run: `python /app/scripts/finance.py ynab-accounts [--budget BUDGET_NAME]`

Returns JSON array with fields: `id`, `name`, `type`, `balance`, `cleared_balance`, `on_budget`, `closed`.

### Category spending

Run: `python /app/scripts/finance.py ynab-categories [--budget BUDGET_NAME] [--month YYYY-MM]`

Returns JSON array with fields: `id`, `name`, `category_group`, `budgeted`, `activity`, `balance`.

- Without `--month`: returns all categories with current totals.
- With `--month`: returns category spending for that specific month.

---

## Error handling

- Missing `FIREFLY_API_TOKEN` or `YNAB_API_TOKEN` → JSON error to stderr, exit code 1
- Connection failures → JSON error to stderr, exit code 1
- Invalid dates → JSON error to stderr, exit code 1
- Unknown budget name → JSON error to stderr, exit code 1

## Cross-referencing workflows

- Compare YNAB category spending with Firefly transaction categories for the same month
- Use YNAB `budgeted` amounts and Firefly `spent` amounts to track adherence
- Use `ynab-categories --month` to see budget targets, then `transactions --type withdrawal` to see actual Firefly spending

## Important notes

- Both integrations are **read-only** — no creating or modifying transactions.
- All monetary values are returned as strings to preserve precision.
- YNAB amounts are automatically converted from milliunits (1000 = $1.00).
- Credentials are injected via environment variables — never ask the user for tokens.
