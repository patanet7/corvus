"""Firefly III tools — direct functions for personal finance management.

Tools:
    firefly_transactions      — Query transactions with optional filters
    firefly_accounts          — List accounts with optional type filter
    firefly_categories        — List spending categories
    firefly_summary           — Get spending summary for date range
    firefly_create_transaction — Create a new transaction (CONFIRM-GATED)

Configuration:
    Call configure(firefly_url, firefly_token) before using any tool.

All outputs are sanitized via claw.sanitize.sanitize() to prevent
credential leakage.
"""

from datetime import date
from typing import Any

import requests

from corvus.tools.response import make_error_response, make_tool_response

# Module-level configuration set via configure()
_firefly_url: str | None = None
_firefly_token: str | None = None


def configure(firefly_url: str, firefly_token: str) -> None:
    """Set the Firefly III API base URL and authentication token.

    Args:
        firefly_url: Firefly III base URL (e.g., "http://firefly-host:8081").
        firefly_token: Personal Access Token for the Firefly III REST API.
    """
    global _firefly_url, _firefly_token  # noqa: PLW0603
    _firefly_url = firefly_url.rstrip("/")
    _firefly_token = firefly_token


def _get_config() -> tuple[str, str]:
    """Return (url, token) or raise if not configured."""
    if _firefly_url is None or _firefly_token is None:
        raise RuntimeError("Firefly tools not configured. Call claw.tools.firefly.configure(url, token) first.")
    return _firefly_url, _firefly_token


def _api_request(
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict | list:
    """Make an authenticated request to the Firefly III REST API.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: URL path (appended to base URL, e.g. "/api/v1/transactions").
        params: Query parameters.
        data: JSON body for POST/PATCH requests.

    Returns:
        Parsed JSON response.
    """
    url, token = _get_config()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    resp = requests.request(
        method,
        f"{url}{path}",
        headers=headers,
        params=params,
        json=data,
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.text
    if not raw:
        return {}
    result: dict | list = resp.json()
    return result


def _format_transaction(entry: dict[str, Any], tx: dict[str, Any]) -> dict[str, Any]:
    """Format a Firefly transaction dict into a clean summary.

    Args:
        entry: The top-level data entry (contains id, attributes).
        tx: A single transaction from attributes.transactions[].

    Returns:
        Flat dict with the key transaction fields.
    """
    return {
        "id": entry.get("id"),
        "date": tx.get("date", ""),
        "description": tx.get("description", ""),
        "amount": tx.get("amount", "0"),
        "currency_code": tx.get("currency_code", ""),
        "type": tx.get("type", ""),
        "source_name": tx.get("source_name", ""),
        "destination_name": tx.get("destination_name", ""),
        "category_name": tx.get("category_name", ""),
        "budget_name": tx.get("budget_name", ""),
    }


# ---------------------------------------------------------------------------
# Tool functions — sync, keyword arguments (matches ha.py / drive.py pattern)
# ---------------------------------------------------------------------------


def firefly_transactions(
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
    type: str | None = None,
) -> dict[str, Any]:
    """Query transactions with optional filters.

    Args:
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.
        limit: Max results per page.
        type: Transaction type filter (withdrawal, deposit, transfer).

    Returns:
        Tool response with count and transactions array.
    """
    try:
        params: dict[str, str] = {}
        if start:
            params["start"] = str(start)
        if end:
            params["end"] = str(end)
        if limit:
            params["limit"] = str(limit)
        if type:
            params["type"] = str(type)

        resp = _api_request("GET", "/api/v1/transactions", params=params)
        data_list = resp.get("data", []) if isinstance(resp, dict) else []
        transactions = []
        for entry in data_list:
            attrs = entry.get("attributes", {})
            for tx in attrs.get("transactions", []):
                transactions.append(_format_transaction(entry, tx))

        return make_tool_response({"count": len(transactions), "transactions": transactions})
    except requests.exceptions.ConnectionError:
        return make_error_response("Firefly III is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Firefly API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def firefly_accounts(type: str | None = None) -> dict[str, Any]:
    """List accounts with optional type filter.

    Args:
        type: Account type filter (asset, expense, revenue, liability).

    Returns:
        Tool response with accounts array.
    """
    try:
        params: dict[str, str] = {}
        if type:
            params["type"] = str(type)

        resp = _api_request("GET", "/api/v1/accounts", params=params)
        data_list = resp.get("data", []) if isinstance(resp, dict) else []
        accounts = []
        for entry in data_list:
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

        return make_tool_response({"accounts": accounts})
    except requests.exceptions.ConnectionError:
        return make_error_response("Firefly III is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Firefly API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def firefly_categories() -> dict[str, Any]:
    """List spending categories.

    Returns:
        Tool response with categories array.
    """
    try:
        resp = _api_request("GET", "/api/v1/categories")
        data_list = resp.get("data", []) if isinstance(resp, dict) else []
        categories = []
        for entry in data_list:
            attrs = entry.get("attributes", {})
            spent_list = attrs.get("spent", [])
            spent_sum = spent_list[0].get("sum", "0") if spent_list else "0"
            currency = spent_list[0].get("currency_code", "") if spent_list else ""
            categories.append(
                {
                    "id": entry.get("id"),
                    "name": attrs.get("name", ""),
                    "spent": spent_sum,
                    "currency_code": currency,
                }
            )

        return make_tool_response({"categories": categories})
    except requests.exceptions.ConnectionError:
        return make_error_response("Firefly III is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Firefly API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def firefly_summary(
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Get spending summary for date range (defaults to current month).

    Args:
        start: Start date YYYY-MM-DD. Defaults to 1st of current month.
        end: End date YYYY-MM-DD. Defaults to today.

    Returns:
        Tool response with summary dict.
    """
    try:
        today = date.today()
        start = start or today.replace(day=1).isoformat()
        end = end or today.isoformat()

        params: dict[str, str] = {"start": str(start), "end": str(end)}
        resp = _api_request("GET", "/api/v1/summary/basic", params=params)

        summary: dict[str, Any] = {}
        if isinstance(resp, dict):
            for key, value in resp.items():
                if isinstance(value, dict):
                    summary[key] = {
                        "value": value.get("monetary_value", value.get("value", 0)),
                        "currency_code": value.get("currency_code", ""),
                        "label": value.get("label", key),
                    }

        return make_tool_response({"summary": summary})
    except requests.exceptions.ConnectionError:
        return make_error_response("Firefly III is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Firefly API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def firefly_create_transaction(
    description: str,
    amount: str | float,
    type: str = "withdrawal",
    source_name: str | None = None,
    destination_name: str | None = None,
    category_name: str | None = None,
    date: str | None = None,
    currency_code: str | None = None,
) -> dict[str, Any]:
    """Create a new transaction. CONFIRM-GATED.

    Args:
        description: Transaction description.
        amount: Transaction amount.
        type: Transaction type (withdrawal, deposit, transfer).
        source_name: Source account name.
        destination_name: Destination account name.
        category_name: Category name.
        date: Transaction date YYYY-MM-DD. Defaults to today.
        currency_code: Currency code (e.g., "USD").

    Returns:
        Tool response confirming the transaction was created.
    """
    from datetime import date as date_cls

    try:
        tx_data: dict[str, Any] = {
            "type": type,
            "description": description,
            "amount": str(amount),
            "date": date or date_cls.today().isoformat(),
        }
        if source_name:
            tx_data["source_name"] = source_name
        if destination_name:
            tx_data["destination_name"] = destination_name
        if category_name:
            tx_data["category_name"] = category_name
        if currency_code:
            tx_data["currency_code"] = currency_code

        body = {"transactions": [tx_data]}
        resp = _api_request("POST", "/api/v1/transactions", data=body)

        # Extract the created transaction ID from the response
        created_id = None
        if isinstance(resp, dict) and "data" in resp:
            created_id = resp["data"].get("id")

        return make_tool_response(
            {
                "status": "created",
                "id": created_id,
                "description": description,
                "amount": str(amount),
                "type": tx_data["type"],
                "date": tx_data["date"],
            }
        )
    except requests.exceptions.ConnectionError:
        return make_error_response("Firefly III is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Firefly API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))
