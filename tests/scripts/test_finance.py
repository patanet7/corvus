"""Tests for finance.py CLI interface (Firefly III + YNAB).

Verifies the CLI contract (JSON output shapes) and behavioral correctness
by running the script as a subprocess — the same way agents invoke it via Bash.

Uses real HTTP servers (http.server) as stand-ins for both APIs.
NO MOCKS. No MagicMock, no monkeypatch, no @patch.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

# ---------------------------------------------------------------------------
# Sample Firefly III API data
# ---------------------------------------------------------------------------

SAMPLE_FIREFLY_TRANSACTIONS = {
    "data": [
        {
            "id": "1",
            "attributes": {
                "transactions": [
                    {
                        "date": "2026-02-15",
                        "description": "Grocery Store",
                        "amount": "85.50",
                        "currency_code": "USD",
                        "type": "withdrawal",
                        "source_name": "Checking Account",
                        "destination_name": "Whole Foods",
                        "category_name": "Groceries",
                        "budget_name": "Food",
                    }
                ]
            },
        },
        {
            "id": "2",
            "attributes": {
                "transactions": [
                    {
                        "date": "2026-02-14",
                        "description": "Paycheck",
                        "amount": "3500.00",
                        "currency_code": "USD",
                        "type": "deposit",
                        "source_name": "Employer Inc",
                        "destination_name": "Checking Account",
                        "category_name": "Salary",
                        "budget_name": "",
                    }
                ]
            },
        },
    ]
}

SAMPLE_FIREFLY_ACCOUNTS = {
    "data": [
        {
            "id": "1",
            "attributes": {
                "name": "Checking Account",
                "type": "asset",
                "current_balance": "4250.75",
                "currency_code": "USD",
                "active": True,
            },
        },
        {
            "id": "2",
            "attributes": {
                "name": "Credit Card",
                "type": "liability",
                "current_balance": "-320.00",
                "currency_code": "USD",
                "active": True,
            },
        },
    ]
}

SAMPLE_FIREFLY_BUDGETS = {
    "data": [
        {
            "id": "1",
            "attributes": {
                "name": "Groceries",
                "active": True,
                "spent": [{"sum": "-250.00", "currency_code": "USD"}],
            },
        },
        {
            "id": "2",
            "attributes": {
                "name": "Entertainment",
                "active": True,
                "spent": [{"sum": "-75.00", "currency_code": "USD"}],
            },
        },
    ]
}

SAMPLE_FIREFLY_SUMMARY: dict[str, Any] = {
    "balance-in-USD": {
        "monetary_value": 4250.75,
        "currency_code": "USD",
        "label": "Balance",
    },
    "spent-in-USD": {
        "monetary_value": -850.00,
        "currency_code": "USD",
        "label": "Spent",
    },
    "earned-in-USD": {
        "monetary_value": 3500.00,
        "currency_code": "USD",
        "label": "Earned",
    },
}


# ---------------------------------------------------------------------------
# Sample YNAB API data
# ---------------------------------------------------------------------------

BUDGET_ID = "aaaabbbb-1111-2222-3333-ccccddddeeee"

SAMPLE_YNAB_BUDGETS = {
    "data": {
        "budgets": [
            {
                "id": BUDGET_ID,
                "name": "My Budget",
                "currency_format": {"iso_code": "USD"},
                "last_modified_on": "2026-02-20T10:00:00+00:00",
            },
            {
                "id": "ff001122-aabb-ccdd-eeff-001122334455",
                "name": "Savings Plan",
                "currency_format": {"iso_code": "USD"},
                "last_modified_on": "2026-01-15T08:00:00+00:00",
            },
        ]
    }
}

SAMPLE_YNAB_TRANSACTIONS = {
    "data": {
        "transactions": [
            {
                "id": "tx-001",
                "date": "2026-02-18",
                "payee_name": "Target",
                "amount": -45670,  # milliunits: -$45.67
                "memo": "Household supplies",
                "category_name": "Home",
                "account_name": "Checking",
                "cleared": "cleared",
                "approved": True,
            },
            {
                "id": "tx-002",
                "date": "2026-02-20",
                "payee_name": "Employer",
                "amount": 3500000,  # milliunits: $3500.00
                "memo": "Bi-weekly pay",
                "category_name": "Inflow: Ready to Assign",
                "account_name": "Checking",
                "cleared": "cleared",
                "approved": True,
            },
        ]
    }
}

SAMPLE_YNAB_ACCOUNTS = {
    "data": {
        "accounts": [
            {
                "id": "acct-001",
                "name": "Checking",
                "type": "checking",
                "balance": 5234560,  # $5234.56
                "cleared_balance": 5234560,
                "on_budget": True,
                "closed": False,
            },
            {
                "id": "acct-002",
                "name": "Savings",
                "type": "savings",
                "balance": 12000000,  # $12000.00
                "cleared_balance": 12000000,
                "on_budget": True,
                "closed": False,
            },
        ]
    }
}

SAMPLE_YNAB_CATEGORIES = {
    "data": {
        "category_groups": [
            {
                "name": "Immediate Obligations",
                "categories": [
                    {
                        "id": "cat-001",
                        "name": "Rent/Mortgage",
                        "budgeted": 1500000,
                        "activity": -1500000,
                        "balance": 0,
                    },
                    {
                        "id": "cat-002",
                        "name": "Groceries",
                        "budgeted": 400000,
                        "activity": -312500,
                        "balance": 87500,
                    },
                ],
            },
            {
                "name": "Quality of Life",
                "categories": [
                    {
                        "id": "cat-003",
                        "name": "Fun Money",
                        "budgeted": 100000,
                        "activity": -65000,
                        "balance": 35000,
                    },
                ],
            },
        ]
    }
}

SAMPLE_YNAB_MONTH = {
    "data": {
        "month": {
            "month": "2026-02-01",
            "categories": [
                {
                    "id": "cat-001",
                    "name": "Rent/Mortgage",
                    "category_group_name": "Immediate Obligations",
                    "budgeted": 1500000,
                    "activity": -1500000,
                    "balance": 0,
                },
                {
                    "id": "cat-002",
                    "name": "Groceries",
                    "category_group_name": "Immediate Obligations",
                    "budgeted": 400000,
                    "activity": -312500,
                    "balance": 87500,
                },
            ],
        }
    }
}


# ---------------------------------------------------------------------------
# Combined HTTP handler serving both Firefly and YNAB endpoints
# ---------------------------------------------------------------------------


class FinanceAPIHandler(BaseHTTPRequestHandler):
    """Real HTTP handler that mimics both Firefly III and YNAB API responses."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Check Authorization header
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._respond(401, {"error": "Unauthorized"})
            return

        # --- Firefly III routes ---
        if path == "/api/v1/transactions":
            self._respond(200, SAMPLE_FIREFLY_TRANSACTIONS)
        elif path == "/api/v1/accounts":
            self._respond(200, SAMPLE_FIREFLY_ACCOUNTS)
        elif path == "/api/v1/budgets":
            self._respond(200, SAMPLE_FIREFLY_BUDGETS)
        elif path == "/api/v1/summary/basic":
            self._respond(200, SAMPLE_FIREFLY_SUMMARY)

        # --- YNAB routes ---
        elif path == "/v1/budgets":
            self._respond(200, SAMPLE_YNAB_BUDGETS)
        elif path == f"/v1/budgets/{BUDGET_ID}/transactions" or path == "/v1/budgets/last-used/transactions":
            self._respond(200, SAMPLE_YNAB_TRANSACTIONS)
        elif path == f"/v1/budgets/{BUDGET_ID}/accounts" or path == "/v1/budgets/last-used/accounts":
            self._respond(200, SAMPLE_YNAB_ACCOUNTS)
        elif path == f"/v1/budgets/{BUDGET_ID}/categories" or path == "/v1/budgets/last-used/categories":
            self._respond(200, SAMPLE_YNAB_CATEGORIES)
        elif "/months/" in path:
            self._respond(200, SAMPLE_YNAB_MONTH)

        else:
            self._respond(404, {"error": f"Not found: {path}"})

    def _respond(self, status: int, body: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress request logging during tests."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_DIR = str(Path(sys.executable).parent)


def _run_cli(
    args: list[str],
    *,
    server_url: str | None = None,
    firefly_token: str = "test-firefly-token",
    ynab_token: str = "test-ynab-token",
    extra_env: dict[str, str] | None = None,
    omit_firefly_token: bool = False,
    omit_ynab_token: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the finance CLI as a subprocess.

    Uses ``-m scripts.finance`` instead of running the script file directly
    to avoid adding the ``scripts/`` directory to ``sys.path[0]``, which
    would shadow the stdlib ``email`` package with ``scripts/email.py``.
    """
    env: dict[str, str] = {
        "PATH": f"{_PYTHON_DIR}:/usr/bin:/usr/local/bin",
        "PYTHONPATH": str(WORKTREE_ROOT),
    }
    if server_url:
        env["FIREFLY_URL"] = server_url
        # YNAB default base includes /v1 path; match that when pointing at test server
        env["YNAB_URL"] = f"{server_url}/v1"
    if not omit_firefly_token:
        env["FIREFLY_API_TOKEN"] = firefly_token
    if not omit_ynab_token:
        env["YNAB_API_TOKEN"] = ynab_token
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "scripts.finance", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(WORKTREE_ROOT),
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def finance_server() -> str:
    """Start a real HTTP server that serves both Firefly and YNAB endpoints.

    Returns the base URL (e.g., http://127.0.0.1:PORT).
    Server runs for the entire test module, then shuts down.
    """
    server = HTTPServer(("127.0.0.1", 0), FinanceAPIHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


# ===========================================================================
# FIREFLY III TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Contract: transactions returns valid JSON array
# ---------------------------------------------------------------------------


class TestFireflyTransactionsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["transactions"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_transaction_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["transactions"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {
            "id",
            "date",
            "description",
            "amount",
            "currency_code",
            "type",
            "source",
            "destination",
            "category",
            "budget",
        }
        for tx in data:
            assert required.issubset(tx.keys()), f"Missing fields: {required - tx.keys()}"

    def test_transaction_amount_is_string(self, finance_server: str) -> None:
        """Amounts must be strings to preserve decimal precision."""
        result = _run_cli(["transactions"], server_url=finance_server)
        data = json.loads(result.stdout)
        for tx in data:
            assert isinstance(tx["amount"], str)

    def test_type_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--type", "withdrawal"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_date_range_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--from", "2026-02-01", "--to", "2026-02-28"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_limit_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--limit", "5"],
            server_url=finance_server,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Contract: accounts returns valid JSON array
# ---------------------------------------------------------------------------


class TestFireflyAccountsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["accounts"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_account_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["accounts"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "name", "type", "current_balance", "currency_code", "active"}
        for acct in data:
            assert required.issubset(acct.keys()), f"Missing fields: {required - acct.keys()}"

    def test_type_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(["accounts", "--type", "asset"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_balance_is_string(self, finance_server: str) -> None:
        result = _run_cli(["accounts"], server_url=finance_server)
        data = json.loads(result.stdout)
        for acct in data:
            assert isinstance(acct["current_balance"], str)


# ---------------------------------------------------------------------------
# Contract: budgets returns valid JSON array
# ---------------------------------------------------------------------------


class TestFireflyBudgetsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["budgets"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_budget_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["budgets"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "name", "active", "spent", "currency_code"}
        for budget in data:
            assert required.issubset(budget.keys()), f"Missing fields: {required - budget.keys()}"

    def test_month_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(["budgets", "--month", "2026-02"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Contract: summary returns valid JSON object
# ---------------------------------------------------------------------------


class TestFireflySummaryContract:
    def test_returns_json_object(self, finance_server: str) -> None:
        result = _run_cli(["summary"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_summary_entries_have_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["summary"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        for key, entry in data.items():
            assert "value" in entry, f"Entry {key!r} missing 'value'"
            assert "currency_code" in entry, f"Entry {key!r} missing 'currency_code'"
            assert "label" in entry, f"Entry {key!r} missing 'label'"

    def test_date_range_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["summary", "--start", "2026-02-01", "--end", "2026-02-28"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Firefly: error handling
# ---------------------------------------------------------------------------


class TestFireflyMissingToken:
    def test_missing_token_exits_nonzero(self) -> None:
        result = _run_cli(["transactions"], omit_firefly_token=True)
        assert result.returncode != 0

    def test_missing_token_json_error_to_stderr(self) -> None:
        result = _run_cli(["transactions"], omit_firefly_token=True)
        error = json.loads(result.stderr)
        assert "error" in error
        assert "FIREFLY_API_TOKEN" in error["error"]


class TestFireflyInvalidDates:
    def test_invalid_from_date(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--from", "not-a-date"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error

    def test_invalid_to_date(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--to", "02/28/2026"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error

    def test_invalid_month_format(self, finance_server: str) -> None:
        result = _run_cli(
            ["budgets", "--month", "February"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error

    def test_invalid_summary_date(self, finance_server: str) -> None:
        result = _run_cli(
            ["summary", "--start", "2026-13-01"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error


class TestConnectionErrors:
    def test_unreachable_server_exits_nonzero(self) -> None:
        result = _run_cli(
            ["transactions"],
            server_url="http://127.0.0.1:1",  # Nothing listens here
        )
        assert result.returncode != 0

    def test_unreachable_server_json_error_to_stderr(self) -> None:
        result = _run_cli(
            ["accounts"],
            server_url="http://127.0.0.1:1",
        )
        error = json.loads(result.stderr)
        assert "error" in error
        assert "connect" in error["error"].lower() or "Cannot" in error["error"]


# ---------------------------------------------------------------------------
# Firefly: data integrity
# ---------------------------------------------------------------------------


class TestFireflyDataIntegrity:
    def test_transaction_data_matches_server_response(self, finance_server: str) -> None:
        result = _run_cli(["transactions"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["description"] == "Grocery Store"
        assert data[0]["amount"] == "85.50"
        assert data[0]["type"] == "withdrawal"
        assert data[1]["description"] == "Paycheck"
        assert data[1]["amount"] == "3500.00"
        assert data[1]["type"] == "deposit"

    def test_account_data_matches_server_response(self, finance_server: str) -> None:
        result = _run_cli(["accounts"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["name"] == "Checking Account"
        assert data[0]["current_balance"] == "4250.75"
        assert data[1]["name"] == "Credit Card"
        assert data[1]["type"] == "liability"

    def test_budget_data_matches_server_response(self, finance_server: str) -> None:
        result = _run_cli(["budgets"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["name"] == "Groceries"
        assert data[0]["spent"] == "-250.00"
        assert data[1]["name"] == "Entertainment"

    def test_summary_data_matches_server_response(self, finance_server: str) -> None:
        result = _run_cli(["summary"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert "balance-in-USD" in data
        assert data["balance-in-USD"]["value"] == 4250.75
        assert data["spent-in-USD"]["value"] == -850.00
        assert data["earned-in-USD"]["currency_code"] == "USD"


# ===========================================================================
# YNAB TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Contract: ynab-budgets returns valid JSON array
# ---------------------------------------------------------------------------


class TestYnabBudgetsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["ynab-budgets"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_budget_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["ynab-budgets"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "name", "currency_format", "last_modified"}
        for b in data:
            assert required.issubset(b.keys()), f"Missing fields: {required - b.keys()}"

    def test_returns_multiple_budgets(self, finance_server: str) -> None:
        result = _run_cli(["ynab-budgets"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["name"] == "My Budget"
        assert data[1]["name"] == "Savings Plan"


# ---------------------------------------------------------------------------
# Contract: ynab-transactions returns valid JSON array
# ---------------------------------------------------------------------------


class TestYnabTransactionsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["ynab-transactions"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_transaction_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["ynab-transactions"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "date", "payee", "amount", "memo", "category", "account", "cleared", "approved"}
        for tx in data:
            assert required.issubset(tx.keys()), f"Missing fields: {required - tx.keys()}"

    def test_amount_is_string(self, finance_server: str) -> None:
        """Amounts must be converted from YNAB milliunits to decimal strings."""
        result = _run_cli(["ynab-transactions"], server_url=finance_server)
        data = json.loads(result.stdout)
        for tx in data:
            assert isinstance(tx["amount"], str)

    def test_since_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["ynab-transactions", "--since", "2026-02-01"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_budget_name_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["ynab-transactions", "--budget", "My Budget"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Contract: ynab-accounts returns valid JSON array
# ---------------------------------------------------------------------------


class TestYnabAccountsContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["ynab-accounts"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_account_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["ynab-accounts"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "name", "type", "balance", "cleared_balance", "on_budget", "closed"}
        for acct in data:
            assert required.issubset(acct.keys()), f"Missing fields: {required - acct.keys()}"

    def test_balance_is_string(self, finance_server: str) -> None:
        """Balances must be converted from milliunits to decimal strings."""
        result = _run_cli(["ynab-accounts"], server_url=finance_server)
        data = json.loads(result.stdout)
        for acct in data:
            assert isinstance(acct["balance"], str)
            assert isinstance(acct["cleared_balance"], str)


# ---------------------------------------------------------------------------
# Contract: ynab-categories returns valid JSON array
# ---------------------------------------------------------------------------


class TestYnabCategoriesContract:
    def test_returns_json_array(self, finance_server: str) -> None:
        result = _run_cli(["ynab-categories"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_category_has_required_fields(self, finance_server: str) -> None:
        result = _run_cli(["ynab-categories"], server_url=finance_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required = {"id", "name", "category_group", "budgeted", "activity", "balance"}
        for cat in data:
            assert required.issubset(cat.keys()), f"Missing fields: {required - cat.keys()}"

    def test_month_filter_accepted(self, finance_server: str) -> None:
        result = _run_cli(
            ["ynab-categories", "--month", "2026-02"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_amounts_are_strings(self, finance_server: str) -> None:
        result = _run_cli(["ynab-categories"], server_url=finance_server)
        data = json.loads(result.stdout)
        for cat in data:
            assert isinstance(cat["budgeted"], str)
            assert isinstance(cat["activity"], str)
            assert isinstance(cat["balance"], str)


# ---------------------------------------------------------------------------
# YNAB: error handling
# ---------------------------------------------------------------------------


class TestYnabMissingToken:
    def test_missing_token_exits_nonzero(self) -> None:
        result = _run_cli(["ynab-budgets"], omit_ynab_token=True)
        assert result.returncode != 0

    def test_missing_token_json_error_to_stderr(self) -> None:
        result = _run_cli(["ynab-budgets"], omit_ynab_token=True)
        error = json.loads(result.stderr)
        assert "error" in error
        assert "YNAB_API_TOKEN" in error["error"]


class TestYnabInvalidDates:
    def test_invalid_since_date(self, finance_server: str) -> None:
        result = _run_cli(
            ["ynab-transactions", "--since", "not-a-date"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error

    def test_invalid_month_format(self, finance_server: str) -> None:
        result = _run_cli(
            ["ynab-categories", "--month", "Feb-2026"],
            server_url=finance_server,
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error


class TestYnabConnectionErrors:
    def test_unreachable_server_exits_nonzero(self) -> None:
        result = _run_cli(
            ["ynab-budgets"],
            server_url="http://127.0.0.1:1",
        )
        assert result.returncode != 0

    def test_unreachable_server_json_error_to_stderr(self) -> None:
        result = _run_cli(
            ["ynab-accounts"],
            server_url="http://127.0.0.1:1",
        )
        error = json.loads(result.stderr)
        assert "error" in error


# ---------------------------------------------------------------------------
# YNAB: data integrity
# ---------------------------------------------------------------------------


class TestYnabDataIntegrity:
    def test_budget_data_matches_server(self, finance_server: str) -> None:
        result = _run_cli(["ynab-budgets"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["name"] == "My Budget"
        assert data[0]["currency_format"] == "USD"
        assert data[1]["name"] == "Savings Plan"

    def test_transaction_milliunits_conversion(self, finance_server: str) -> None:
        """Verify milliunits are converted correctly to decimal strings."""
        result = _run_cli(["ynab-transactions"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        # -45670 milliunits = -$45.67
        assert data[0]["amount"] == "-45.67"
        assert data[0]["payee"] == "Target"
        # 3500000 milliunits = $3500.00
        assert data[1]["amount"] == "3500.00"
        assert data[1]["payee"] == "Employer"

    def test_account_milliunits_conversion(self, finance_server: str) -> None:
        result = _run_cli(["ynab-accounts"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 2
        # 5234560 milliunits = $5234.56
        assert data[0]["balance"] == "5234.56"
        assert data[0]["name"] == "Checking"
        # 12000000 milliunits = $12000.00
        assert data[1]["balance"] == "12000.00"
        assert data[1]["name"] == "Savings"

    def test_categories_from_groups(self, finance_server: str) -> None:
        """Categories should be flattened from category groups."""
        result = _run_cli(["ynab-categories"], server_url=finance_server)
        data = json.loads(result.stdout)
        assert len(data) == 3
        assert data[0]["name"] == "Rent/Mortgage"
        assert data[0]["category_group"] == "Immediate Obligations"
        # 1500000 milliunits = $1500.00
        assert data[0]["budgeted"] == "1500.00"
        assert data[0]["activity"] == "-1500.00"
        assert data[2]["name"] == "Fun Money"
        assert data[2]["category_group"] == "Quality of Life"

    def test_categories_with_month_filter(self, finance_server: str) -> None:
        """Month filter should use the month detail endpoint."""
        result = _run_cli(
            ["ynab-categories", "--month", "2026-02"],
            server_url=finance_server,
        )
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["name"] == "Rent/Mortgage"
        assert data[0]["category_group"] == "Immediate Obligations"

    def test_budget_name_resolves_to_id(self, finance_server: str) -> None:
        """Passing --budget 'My Budget' should resolve to the correct budget ID."""
        result = _run_cli(
            ["ynab-transactions", "--budget", "My Budget"],
            server_url=finance_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 2  # Same transactions as default budget


# ---------------------------------------------------------------------------
# CLI argument validation
# ---------------------------------------------------------------------------


class TestCLIArgs:
    def test_no_subcommand_exits_nonzero(self) -> None:
        result = _run_cli([], server_url="http://unused")
        assert result.returncode != 0

    def test_invalid_type_filter(self, finance_server: str) -> None:
        result = _run_cli(
            ["transactions", "--type", "invalid"],
            server_url=finance_server,
        )
        assert result.returncode != 0

    def test_invalid_account_type(self, finance_server: str) -> None:
        result = _run_cli(
            ["accounts", "--type", "invalid"],
            server_url=finance_server,
        )
        assert result.returncode != 0
