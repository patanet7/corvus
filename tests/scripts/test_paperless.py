"""Tests for paperless.py CLI interface.

Verifies the CLI contract (JSON output shapes) and behavioral correctness
by running the script as a subprocess against a real local HTTP server
that mimics the Paperless-ngx API — no mocks, no patches.
"""

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = str(WORKTREE_ROOT / "scripts" / "paperless.py")
_PYTHON_DIR = str(Path(sys.executable).parent)


# ---------------------------------------------------------------------------
# Fake Paperless-ngx API server
# ---------------------------------------------------------------------------

# Shared state for the fake server — mutable so tests can seed data
_FAKE_TAGS: list[dict[str, Any]] = []
_FAKE_DOCUMENTS: list[dict[str, Any]] = []
_BULK_EDIT_LOG: list[dict[str, Any]] = []


def _reset_fake_data() -> None:
    """Reset fake server state between tests."""
    _FAKE_TAGS.clear()
    _FAKE_DOCUMENTS.clear()
    _BULK_EDIT_LOG.clear()

    _FAKE_TAGS.extend(
        [
            {"id": 1, "name": "invoice", "colour": "#ff0000", "document_count": 5},
            {"id": 2, "name": "receipt", "colour": "#00ff00", "document_count": 3},
            {"id": 3, "name": "tax", "colour": "#0000ff", "document_count": 2},
            {"id": 4, "name": "manual", "colour": "#ffff00", "document_count": 1},
        ]
    )

    _FAKE_DOCUMENTS.extend(
        [
            {
                "id": 101,
                "title": "Electric Bill January 2026",
                "content": "ComEd electric bill for service period 12/15/2025 to 01/15/2026. Total amount due: $142.37. Account number: XXXXX1234.",
                "created": "2026-01-20T00:00:00Z",
                "modified": "2026-01-20T12:00:00Z",
                "added": "2026-01-21T08:30:00Z",
                "tags": [1],
                "correspondent": 10,
                "document_type": 2,
                "archive_serial_number": 1001,
                "original_file_name": "comed-jan-2026.pdf",
                "__search_hit__": {"score": 0.95, "highlights": "electric bill", "rank": 0},
            },
            {
                "id": 102,
                "title": "Grocery Receipt Trader Joes",
                "content": "Trader Joe's receipt dated 01/25/2026. Items: bananas, olive oil, dark chocolate. Total: $34.56.",
                "created": "2026-01-25T00:00:00Z",
                "modified": "2026-01-25T10:00:00Z",
                "added": "2026-01-26T09:00:00Z",
                "tags": [2],
                "correspondent": 11,
                "document_type": 3,
                "archive_serial_number": 1002,
                "original_file_name": "trader-joes-receipt.jpg",
                "__search_hit__": {"score": 0.80, "highlights": "grocery receipt", "rank": 1},
            },
            {
                "id": 103,
                "title": "W-2 Form 2025",
                "content": "W-2 Wage and Tax Statement for tax year 2025. Employer: Acme Corp. Federal income tax withheld: $12,345.67.",
                "created": "2026-01-30T00:00:00Z",
                "modified": "2026-01-30T14:00:00Z",
                "added": "2026-02-01T07:00:00Z",
                "tags": [3],
                "correspondent": 12,
                "document_type": 4,
                "archive_serial_number": 1003,
                "original_file_name": "w2-2025.pdf",
                "__search_hit__": {"score": 0.70, "highlights": "W-2 tax", "rank": 2},
            },
        ]
    )


class FakePaperlessHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler mimicking Paperless-ngx API endpoints."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress server log output during tests."""
        pass

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Token "):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "Authentication required"}).encode())
            return False
        return True

    def _send_json(self, data: Any, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)
        # Flatten single-value params for convenience
        params = {k: v[0] for k, v in qs.items()}

        # GET /api/tags/
        if path == "/api/tags":
            page_size = int(params.get("page_size", "50"))
            results = _FAKE_TAGS[:page_size]
            self._send_json(
                {
                    "count": len(results),
                    "next": None,
                    "previous": None,
                    "results": results,
                }
            )
            return

        # GET /api/documents/{id}/
        if path.startswith("/api/documents/") and path.replace("/api/documents/", "").isdigit():
            doc_id = int(path.replace("/api/documents/", ""))
            for doc in _FAKE_DOCUMENTS:
                if doc["id"] == doc_id:
                    # Return without __search_hit__ for single-doc endpoint
                    result = {k: v for k, v in doc.items() if k != "__search_hit__"}
                    self._send_json(result)
                    return
            self._send_json({"detail": "Not found."}, status=404)
            return

        # GET /api/documents/
        if path == "/api/documents":
            query = params.get("query", "").lower()
            page_size = int(params.get("page_size", "10"))
            tag_filter = params.get("tags__id__in")

            filtered = _FAKE_DOCUMENTS
            if query:
                filtered = [d for d in filtered if query in d["title"].lower() or query in d["content"].lower()]
            if tag_filter:
                tag_id = int(tag_filter)
                filtered = [d for d in filtered if tag_id in d["tags"]]

            results = filtered[:page_size]
            self._send_json(
                {
                    "count": len(results),
                    "next": None,
                    "previous": None,
                    "results": results,
                }
            )
            return

        self._send_json({"detail": "Not found."}, status=404)

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        path = self.path.split("?")[0].rstrip("/")

        # POST /api/documents/bulk_edit/
        if path == "/api/documents/bulk_edit":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length).decode())
            _BULK_EDIT_LOG.append(body)
            self._send_json({"status": "ok"})
            return

        self._send_json({"detail": "Not found."}, status=404)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_data() -> None:
    """Reset fake server data before each test."""
    _reset_fake_data()


@pytest.fixture(scope="session")
def fake_server() -> str:
    """Start a real HTTP server for the test session, return its base URL."""
    server = http.server.HTTPServer(("127.0.0.1", 0), FakePaperlessHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def _run_cli(
    args: list[str],
    *,
    server_url: str,
    token: str = "test-token-abc123",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the paperless CLI as a subprocess.

    Note: PYTHONPATH is intentionally NOT set. paperless.py is a standalone
    script using only stdlib — setting PYTHONPATH to the worktree root would
    cause scripts/email.py to shadow Python's stdlib email package.
    """
    env = {
        "PAPERLESS_URL": server_url,
        "PAPERLESS_API_TOKEN": token,
        "PATH": f"{_PYTHON_DIR}:/usr/bin:/usr/local/bin",
    }
    if extra_env:
        env.update(extra_env)

    # Use -P to prevent Python from adding the script's directory to sys.path.
    # Without -P, scripts/email.py shadows the stdlib email package.
    return subprocess.run(
        [sys.executable, "-P", CLI_SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Contract: search returns valid JSON array with required keys
# ---------------------------------------------------------------------------


class TestSearchContract:
    def test_search_returns_json_array(self, fake_server: str) -> None:
        result = _run_cli(["search", "electric"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_search_results_have_required_keys(self, fake_server: str) -> None:
        result = _run_cli(["search", "electric"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required_keys = {"id", "title", "created", "tags"}
        for item in data:
            assert required_keys.issubset(item.keys()), f"Missing keys: {required_keys - item.keys()}"

    def test_search_no_matches_returns_empty_array(self, fake_server: str) -> None:
        result = _run_cli(["search", "xyznonexistentquery"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_search_respects_limit(self, fake_server: str) -> None:
        result = _run_cli(["search", "2026", "--limit", "1"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) <= 1

    def test_search_includes_content_snippet(self, fake_server: str) -> None:
        result = _run_cli(["search", "electric"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        assert "content" in data[0]
        assert len(data[0]["content"]) > 0

    def test_search_includes_search_hit_metadata(self, fake_server: str) -> None:
        result = _run_cli(["search", "electric"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        # Our fake server includes __search_hit__, so score should be present
        assert "score" in data[0]
        assert isinstance(data[0]["score"], (int, float))

    def test_search_with_tag_filter(self, fake_server: str) -> None:
        result = _run_cli(
            ["search", "2026", "--tag", "invoice"],
            server_url=fake_server,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Only the electric bill has the "invoice" tag (id=1)
        assert len(data) >= 1
        for item in data:
            assert 1 in item["tags"]


# ---------------------------------------------------------------------------
# Contract: get returns valid JSON with required keys
# ---------------------------------------------------------------------------


class TestGetContract:
    def test_get_returns_json_with_required_keys(self, fake_server: str) -> None:
        result = _run_cli(["get", "101"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        required_keys = {
            "id",
            "title",
            "content",
            "created",
            "modified",
            "added",
            "tags",
            "original_file_name",
        }
        assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - data.keys()}"

    def test_get_returns_correct_document(self, fake_server: str) -> None:
        result = _run_cli(["get", "101"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["id"] == 101
        assert "Electric Bill" in data["title"]

    def test_get_includes_full_content(self, fake_server: str) -> None:
        result = _run_cli(["get", "101"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "ComEd" in data["content"]
        assert "$142.37" in data["content"]

    def test_get_nonexistent_document_fails(self, fake_server: str) -> None:
        result = _run_cli(["get", "99999"], server_url=fake_server)
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error


# ---------------------------------------------------------------------------
# Contract: tags returns valid JSON array with required keys
# ---------------------------------------------------------------------------


class TestTagsContract:
    def test_tags_returns_json_array(self, fake_server: str) -> None:
        result = _run_cli(["tags"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_tags_have_required_keys(self, fake_server: str) -> None:
        result = _run_cli(["tags"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) > 0
        required_keys = {"id", "name", "color", "document_count"}
        for tag in data:
            assert required_keys.issubset(tag.keys()), f"Missing keys: {required_keys - tag.keys()}"

    def test_tags_returns_expected_tags(self, fake_server: str) -> None:
        result = _run_cli(["tags"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        names = {tag["name"] for tag in data}
        assert "invoice" in names
        assert "receipt" in names
        assert "tax" in names


# ---------------------------------------------------------------------------
# Contract: tag command returns status JSON
# ---------------------------------------------------------------------------


class TestTagCommand:
    def test_tag_returns_status_json(self, fake_server: str) -> None:
        result = _run_cli(["tag", "101", "receipt"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "tagged"
        assert data["document_id"] == 101
        assert data["tag_name"] == "receipt"
        assert data["tag_id"] == 2  # receipt tag id

    def test_tag_sends_correct_bulk_edit_request(self, fake_server: str) -> None:
        _BULK_EDIT_LOG.clear()
        result = _run_cli(["tag", "102", "tax"], server_url=fake_server)
        assert result.returncode == 0
        # Verify the bulk_edit request was sent correctly
        assert len(_BULK_EDIT_LOG) == 1
        req = _BULK_EDIT_LOG[0]
        assert req["documents"] == [102]
        assert req["method"] == "add_tag"
        assert req["parameters"]["tag"] == 3  # tax tag id

    def test_tag_nonexistent_tag_fails(self, fake_server: str) -> None:
        result = _run_cli(["tag", "101", "nonexistent_tag"], server_url=fake_server)
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "not found" in error["error"].lower()


# ---------------------------------------------------------------------------
# Behavioral: search finds documents by content
# ---------------------------------------------------------------------------


class TestSearchBehavior:
    def test_search_finds_by_title(self, fake_server: str) -> None:
        result = _run_cli(["search", "Grocery"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        assert any("Grocery" in item["title"] for item in data)

    def test_search_finds_by_content(self, fake_server: str) -> None:
        result = _run_cli(["search", "olive oil"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        assert any("Trader" in item["title"] for item in data)

    def test_search_tax_documents(self, fake_server: str) -> None:
        result = _run_cli(["search", "W-2"], server_url=fake_server)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) >= 1
        assert any("W-2" in item["title"] for item in data)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_token_fails(self, fake_server: str) -> None:
        result = _run_cli(["search", "test"], server_url=fake_server, token="")
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
        assert "PAPERLESS_API_TOKEN" in error["error"]

    def test_invalid_subcommand(self, fake_server: str) -> None:
        result = _run_cli(["nonexistent"], server_url=fake_server)
        assert result.returncode != 0

    def test_missing_required_args(self, fake_server: str) -> None:
        result = _run_cli(["get"], server_url=fake_server)
        assert result.returncode != 0

    def test_connection_refused(self) -> None:
        result = _run_cli(
            ["search", "test"],
            server_url="http://127.0.0.1:1",  # nothing listening here
            token="test-token",
        )
        assert result.returncode != 0
        error = json.loads(result.stderr)
        assert "error" in error
