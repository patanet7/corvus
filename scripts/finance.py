#!/usr/bin/env python3
"""Finance CLI — Firefly III + YNAB, called by finance agent via Bash tool.

Firefly III commands:
    python scripts/finance.py transactions [--from DATE] [--to DATE] [--limit N] [--type withdrawal|deposit|transfer]
    python scripts/finance.py accounts [--type asset|expense|revenue|liability]
    python scripts/finance.py budgets [--month YYYY-MM]
    python scripts/finance.py summary [--start DATE] [--end DATE]

YNAB commands:
    python scripts/finance.py ynab-budgets
    python scripts/finance.py ynab-transactions [--budget BUDGET_NAME] [--since DATE]
    python scripts/finance.py ynab-accounts [--budget BUDGET_NAME]
    python scripts/finance.py ynab-categories [--budget BUDGET_NAME] [--month YYYY-MM]

Environment variables:
    FIREFLY_URL        — Base URL for Firefly III (default: http://localhost:8081)
    FIREFLY_API_TOKEN  — Firefly III Personal Access Token (required for Firefly commands)
    YNAB_API_TOKEN     — YNAB Personal Access Token (required for YNAB commands)
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> str:
    """Validate and return a YYYY-MM-DD date string."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except ValueError:
        print(
            json.dumps({"error": f"Invalid date format: {value!r} — expected YYYY-MM-DD"}),
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_month(value: str) -> str:
    """Validate and return a YYYY-MM month string."""
    try:
        datetime.strptime(value, "%Y-%m")
        return value
    except ValueError:
        print(
            json.dumps({"error": f"Invalid month format: {value!r} — expected YYYY-MM"}),
            file=sys.stderr,
        )
        sys.exit(1)


def _http_get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None, provider: str = "API") -> Any:
    """Make an authenticated GET request, handling common HTTP errors."""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        print(
            json.dumps({"error": f"Cannot connect to {provider} at {url.split('/api')[0]}"}),
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.Timeout:
        print(
            json.dumps({"error": f"Request to {provider} timed out"}),
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        print(
            json.dumps({"error": f"{provider} returned HTTP {status}"}),
            file=sys.stderr,
        )
        sys.exit(1)


# ===========================================================================
# Firefly III
# ===========================================================================


def _firefly_config() -> tuple[str, str]:
    """Return (base_url, token) for Firefly III, or exit with error."""
    base_url = os.environ.get("FIREFLY_URL", "http://localhost:8081")
    token = os.environ.get("FIREFLY_API_TOKEN", "")
    if not token:
        print(
            json.dumps({"error": "FIREFLY_API_TOKEN environment variable is required"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return base_url.rstrip("/"), token


def _firefly_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Authenticated GET to Firefly III API."""
    base_url, token = _firefly_config()
    url = f"{base_url}/api/v1/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return _http_get(url, headers, params, provider="Firefly III")


def cmd_transactions(args: argparse.Namespace) -> None:
    """List Firefly III transactions with optional filters."""
    params: dict[str, Any] = {}
    if args.start:
        params["start"] = _parse_date(args.start)
    if args.end:
        params["end"] = _parse_date(args.end)
    if args.limit:
        params["limit"] = args.limit
    if args.type:
        params["type"] = args.type

    raw = _firefly_get("transactions", params)
    transactions = []
    for entry in raw.get("data", []):
        attrs = entry.get("attributes", {})
        for tx in attrs.get("transactions", []):
            transactions.append(
                {
                    "id": entry.get("id"),
                    "date": tx.get("date", ""),
                    "description": tx.get("description", ""),
                    "amount": tx.get("amount", "0"),
                    "currency_code": tx.get("currency_code", ""),
                    "type": tx.get("type", ""),
                    "source": tx.get("source_name", ""),
                    "destination": tx.get("destination_name", ""),
                    "category": tx.get("category_name", ""),
                    "budget": tx.get("budget_name", ""),
                }
            )
    print(json.dumps(transactions, indent=2))


def cmd_accounts(args: argparse.Namespace) -> None:
    """List Firefly III accounts with optional type filter."""
    params: dict[str, Any] = {}
    if args.type:
        params["type"] = args.type

    raw = _firefly_get("accounts", params)
    accounts = []
    for entry in raw.get("data", []):
        attrs = entry.get("attributes", {})
        accounts.append(
            {
                "id": entry.get("id"),
                "name": attrs.get("name", ""),
                "type": attrs.get("type", ""),
                "current_balance": attrs.get("current_balance", "0"),
                "currency_code": attrs.get("currency_code", ""),
                "active": attrs.get("active", True),
            }
        )
    print(json.dumps(accounts, indent=2))


def cmd_budgets(args: argparse.Namespace) -> None:
    """List Firefly III budgets with optional month filter."""
    params: dict[str, Any] = {}
    if args.month:
        _parse_month(args.month)
        params["start"] = f"{args.month}-01"
        year, month = args.month.split("-")
        if int(month) == 12:
            params["end"] = f"{int(year) + 1}-01-01"
        else:
            params["end"] = f"{year}-{int(month) + 1:02d}-01"

    raw = _firefly_get("budgets", params)
    budgets = []
    for entry in raw.get("data", []):
        attrs = entry.get("attributes", {})
        spent_list = attrs.get("spent", [])
        spent_amount = spent_list[0].get("sum", "0") if spent_list else "0"
        currency = spent_list[0].get("currency_code", "") if spent_list else ""

        budgets.append(
            {
                "id": entry.get("id"),
                "name": attrs.get("name", ""),
                "active": attrs.get("active", True),
                "spent": spent_amount,
                "currency_code": currency,
            }
        )
    print(json.dumps(budgets, indent=2))


def cmd_summary(args: argparse.Namespace) -> None:
    """Get Firefly III spending summary for a date range."""
    today = date.today()
    start = args.start if args.start else today.replace(day=1).isoformat()
    end = args.end if args.end else today.isoformat()

    start = _parse_date(start)
    end = _parse_date(end)

    params = {"start": start, "end": end}
    raw = _firefly_get("summary/basic", params)

    summary = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            summary[key] = {
                "value": value.get("monetary_value", value.get("value", 0)),
                "currency_code": value.get("currency_code", ""),
                "label": value.get("label", key),
            }
    print(json.dumps(summary, indent=2))


# ===========================================================================
# YNAB
# ===========================================================================


def _ynab_config() -> str:
    """Return YNAB API token, or exit with error."""
    token = os.environ.get("YNAB_API_TOKEN", "")
    if not token:
        print(
            json.dumps({"error": "YNAB_API_TOKEN environment variable is required"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _ynab_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Authenticated GET to YNAB API."""
    token = _ynab_config()
    base_url = os.environ.get("YNAB_URL", "https://api.ynab.com/v1")
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    return _http_get(url, headers, params, provider="YNAB")


def _ynab_milliunits_to_str(milliunits: int | float) -> str:
    """Convert YNAB milliunits (1000 = $1.00) to a decimal string."""
    return f"{milliunits / 1000:.2f}"


def _ynab_resolve_budget_id(budget_name: str | None) -> str:
    """Resolve a budget name to its YNAB budget ID.

    If budget_name is None, returns "last-used" (YNAB's default budget alias).
    """
    if not budget_name:
        return "last-used"

    raw = _ynab_get("budgets")
    budgets = raw.get("data", {}).get("budgets", [])
    for b in budgets:
        if b.get("name", "").lower() == budget_name.lower():
            return str(b["id"])

    # No exact match — try substring
    for b in budgets:
        if budget_name.lower() in b.get("name", "").lower():
            return str(b["id"])

    print(
        json.dumps({"error": f"YNAB budget not found: {budget_name!r}"}),
        file=sys.stderr,
    )
    sys.exit(1)


def cmd_ynab_budgets(args: argparse.Namespace) -> None:
    """List all YNAB budgets."""
    raw = _ynab_get("budgets")
    budgets = []
    for b in raw.get("data", {}).get("budgets", []):
        budgets.append(
            {
                "id": b.get("id", ""),
                "name": b.get("name", ""),
                "currency_format": b.get("currency_format", {}).get("iso_code", ""),
                "last_modified": b.get("last_modified_on", ""),
            }
        )
    print(json.dumps(budgets, indent=2))


def cmd_ynab_transactions(args: argparse.Namespace) -> None:
    """List YNAB transactions for a budget."""
    budget_id = _ynab_resolve_budget_id(args.budget)
    params: dict[str, Any] = {}
    if args.since:
        params["since_date"] = _parse_date(args.since)

    raw = _ynab_get(f"budgets/{budget_id}/transactions", params)
    transactions = []
    for tx in raw.get("data", {}).get("transactions", []):
        transactions.append(
            {
                "id": tx.get("id", ""),
                "date": tx.get("date", ""),
                "payee": tx.get("payee_name", ""),
                "amount": _ynab_milliunits_to_str(tx.get("amount", 0)),
                "memo": tx.get("memo", ""),
                "category": tx.get("category_name", ""),
                "account": tx.get("account_name", ""),
                "cleared": tx.get("cleared", ""),
                "approved": tx.get("approved", False),
            }
        )
    print(json.dumps(transactions, indent=2))


def cmd_ynab_accounts(args: argparse.Namespace) -> None:
    """List YNAB accounts for a budget."""
    budget_id = _ynab_resolve_budget_id(args.budget)
    raw = _ynab_get(f"budgets/{budget_id}/accounts")
    accounts = []
    for acct in raw.get("data", {}).get("accounts", []):
        accounts.append(
            {
                "id": acct.get("id", ""),
                "name": acct.get("name", ""),
                "type": acct.get("type", ""),
                "balance": _ynab_milliunits_to_str(acct.get("balance", 0)),
                "cleared_balance": _ynab_milliunits_to_str(acct.get("cleared_balance", 0)),
                "on_budget": acct.get("on_budget", False),
                "closed": acct.get("closed", False),
            }
        )
    print(json.dumps(accounts, indent=2))


def cmd_ynab_categories(args: argparse.Namespace) -> None:
    """List YNAB categories with spending for a budget."""
    budget_id = _ynab_resolve_budget_id(args.budget)

    if args.month:
        month = _parse_month(args.month)
        path = f"budgets/{budget_id}/months/{month}-01"
        raw = _ynab_get(path)
        # Month detail returns categories nested in the month object
        month_data = raw.get("data", {}).get("month", {})
        categories = []
        for cat in month_data.get("categories", []):
            categories.append(
                {
                    "id": cat.get("id", ""),
                    "name": cat.get("name", ""),
                    "category_group": cat.get("category_group_name", ""),
                    "budgeted": _ynab_milliunits_to_str(cat.get("budgeted", 0)),
                    "activity": _ynab_milliunits_to_str(cat.get("activity", 0)),
                    "balance": _ynab_milliunits_to_str(cat.get("balance", 0)),
                }
            )
    else:
        path = f"budgets/{budget_id}/categories"
        raw = _ynab_get(path)
        categories = []
        for group in raw.get("data", {}).get("category_groups", []):
            group_name = group.get("name", "")
            for cat in group.get("categories", []):
                categories.append(
                    {
                        "id": cat.get("id", ""),
                        "name": cat.get("name", ""),
                        "category_group": group_name,
                        "budgeted": _ynab_milliunits_to_str(cat.get("budgeted", 0)),
                        "activity": _ynab_milliunits_to_str(cat.get("activity", 0)),
                        "balance": _ynab_milliunits_to_str(cat.get("balance", 0)),
                    }
                )
    print(json.dumps(categories, indent=2))


# ===========================================================================
# Argument parser
# ===========================================================================


def main() -> None:
    """Parse arguments and dispatch to subcommand handler."""
    parser = argparse.ArgumentParser(description="Finance CLI — Firefly III + YNAB")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- Firefly III commands ---
    p_tx = sub.add_parser("transactions", help="List Firefly III transactions")
    p_tx.add_argument("--from", dest="start", default=None, help="Start date (YYYY-MM-DD)")
    p_tx.add_argument("--to", dest="end", default=None, help="End date (YYYY-MM-DD)")
    p_tx.add_argument("--limit", type=int, default=None, help="Max results per page")
    p_tx.add_argument(
        "--type",
        choices=["withdrawal", "deposit", "transfer"],
        default=None,
        help="Transaction type filter",
    )

    p_acc = sub.add_parser("accounts", help="List Firefly III accounts")
    p_acc.add_argument(
        "--type",
        choices=["asset", "expense", "revenue", "liability"],
        default=None,
        help="Account type filter",
    )

    p_bud = sub.add_parser("budgets", help="List Firefly III budgets")
    p_bud.add_argument("--month", default=None, help="Month to query (YYYY-MM)")

    p_sum = sub.add_parser("summary", help="Firefly III spending summary")
    p_sum.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    p_sum.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")

    # --- YNAB commands ---
    sub.add_parser("ynab-budgets", help="List all YNAB budgets")

    p_ytx = sub.add_parser("ynab-transactions", help="List YNAB transactions")
    p_ytx.add_argument("--budget", default=None, help="Budget name (default: last-used)")
    p_ytx.add_argument("--since", default=None, help="Only transactions since date (YYYY-MM-DD)")

    p_yacc = sub.add_parser("ynab-accounts", help="List YNAB accounts")
    p_yacc.add_argument("--budget", default=None, help="Budget name (default: last-used)")

    p_ycat = sub.add_parser("ynab-categories", help="List YNAB categories with spending")
    p_ycat.add_argument("--budget", default=None, help="Budget name (default: last-used)")
    p_ycat.add_argument("--month", default=None, help="Month for spending data (YYYY-MM)")

    args = parser.parse_args()

    handlers = {
        "transactions": cmd_transactions,
        "accounts": cmd_accounts,
        "budgets": cmd_budgets,
        "summary": cmd_summary,
        "ynab-budgets": cmd_ynab_budgets,
        "ynab-transactions": cmd_ynab_transactions,
        "ynab-accounts": cmd_ynab_accounts,
        "ynab-categories": cmd_ynab_categories,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
