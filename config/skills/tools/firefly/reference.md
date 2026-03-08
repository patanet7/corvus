# Firefly III API Reference

## Transaction Types
- `withdrawal` — Money going out (expenses)
- `deposit` — Money coming in (income)
- `transfer` — Between your own accounts

## Date Format
All dates use ISO 8601: `YYYY-MM-DD` (e.g., `2026-03-08`).

## Account Types
- `asset` — Bank accounts, cash, savings
- `expense` — Where money goes (stores, services)
- `revenue` — Where money comes from (employers, clients)

## Create Transaction
- `source_name` = the account money leaves (for withdrawals)
- `destination_name` = the account money goes to (for deposits)
- For transfers, both source and destination are your own accounts
- `currency_code` defaults to your Firefly default currency
