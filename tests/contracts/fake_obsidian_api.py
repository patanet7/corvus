"""Fake Obsidian Local REST API server for contract tests.

Serves realistic Obsidian REST API responses using BaseHTTPRequestHandler.
Runs on a random free port in a background thread for test isolation.

Endpoints:
    GET    /vault/{filename}     -> raw markdown or JSON note (Accept header)
    PUT    /vault/{filename}     -> create/update note (204)
    POST   /vault/{filename}     -> append to note (204)
    DELETE /vault/{filename}     -> remove note (204)
    POST   /search/simple/       -> search vault notes (query params)

Auth: Bearer token required on all endpoints (401 if missing/invalid).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

FAKE_TOKEN = "test-obsidian-token-xyz789"

SAMPLE_NOTES: dict[str, dict[str, Any]] = {
    "journal/2026-02-27.md": {
        "content": (
            "---\n"
            "date: 2026-02-27\n"
            "tags:\n"
            "  - daily\n"
            "  - planning\n"
            "---\n"
            "\n"
            "# Daily Note — 2026-02-27\n"
            "\n"
            "## Morning Review\n"
            "- Reviewed Claw slice 12 plan\n"
            "- Checked homelab monitoring dashboards\n"
            "\n"
            "## Tasks\n"
            "- [ ] Implement Obsidian tools for Claw\n"
            "- [x] Update CLAUDE.md with new patterns\n"
            "\n"
            "## Notes\n"
            "Working on the Obsidian integration for the personal agent.\n"
        ),
        "frontmatter": {
            "date": "2026-02-27",
            "tags": ["daily", "planning"],
        },
        "tags": ["daily", "planning"],
        "stat": {
            "ctime": 1740672000000,
            "mtime": 1740672000000,
            "size": 387,
        },
    },
    "projects/openclaw.md": {
        "content": (
            "---\n"
            "project: Claw\n"
            "status: active\n"
            "---\n"
            "\n"
            "# Claw\n"
            "\n"
            "Local-first multi-agent system with domain-specific agents.\n"
            "\n"
            "## Architecture\n"
            "- Gateway handles routing and tool policy\n"
            "- Domain agents are isolated per workspace\n"
            "- Capability broker sanitizes all outputs\n"
            "\n"
            "## Current Work\n"
            "Slice 12: Obsidian tools and sanitization layer.\n"
        ),
        "frontmatter": {
            "project": "Claw",
            "status": "active",
        },
        "tags": ["project/claw"],
        "stat": {
            "ctime": 1740585600000,
            "mtime": 1740672000000,
            "size": 312,
        },
    },
    "personal/todo.md": {
        "content": (
            "---\n"
            "type: todo\n"
            "---\n"
            "\n"
            "# Personal TODO\n"
            "\n"
            "- [ ] Grocery shopping\n"
            "- [x] Schedule dentist appointment\n"
            "- [ ] Renew car registration\n"
            "- [ ] Backup NAS configuration\n"
        ),
        "frontmatter": {
            "type": "todo",
        },
        "tags": [],
        "stat": {
            "ctime": 1740499200000,
            "mtime": 1740585600000,
            "size": 182,
        },
    },
}


def _deep_copy_notes() -> dict[str, dict[str, Any]]:
    """Deep-copy SAMPLE_NOTES so each server run gets a fresh vault."""
    return {
        path: {
            "content": note["content"],
            "frontmatter": dict(note["frontmatter"]),
            "tags": list(note["tags"]),
            "stat": dict(note["stat"]),
        }
        for path, note in SAMPLE_NOTES.items()
    }


class FakeObsidianHandler(BaseHTTPRequestHandler):
    """Handler serving fake Obsidian Local REST API responses."""

    vault: dict[str, dict[str, Any]] = {}
    recorded_requests: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress request logging in test output."""

    def _check_auth(self) -> bool:
        """Validate Bearer token. Returns False and sends 401 if invalid."""
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {FAKE_TOKEN}":
            self._send_json(
                {"message": "Unauthorized", "errorCode": 401},
                status=401,
            )
            return False
        return True

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/markdown") -> None:
        """Send a plain text response."""
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int = 204) -> None:
        """Send an empty response (204 No Content)."""
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _record_request(self, method: str, path: str, body: str = "") -> None:
        """Record request for isolation testing (no auth headers)."""
        FakeObsidianHandler.recorded_requests.append({"method": method, "path": path, "body": body})

    def _read_body(self) -> bytes:
        """Read the request body."""
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length) if content_length > 0 else b""

    def _vault_path(self) -> str:
        """Extract vault file path from the URL (everything after /vault/)."""
        parsed = urlparse(self.path)
        prefix = "/vault/"
        if parsed.path.startswith(prefix):
            return parsed.path[len(prefix) :]
        return ""

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)

        if parsed.path.startswith("/vault/"):
            filepath = parsed.path[len("/vault/") :]
            self._record_request("GET", self.path)

            note = FakeObsidianHandler.vault.get(filepath)
            if note is None:
                self._send_json(
                    {"message": f"Note not found: {filepath}", "errorCode": 404},
                    status=404,
                )
                return

            accept = self.headers.get("Accept", "")
            if "application/vnd.olrapi.note+json" in accept:
                self._send_json(
                    {
                        "content": note["content"],
                        "frontmatter": note["frontmatter"],
                        "path": filepath,
                        "stat": note["stat"],
                        "tags": note["tags"],
                    }
                )
            else:
                self._send_text(note["content"])
            return

        self._send_json({"message": "Not found", "errorCode": 404}, status=404)

    def do_PUT(self) -> None:
        if not self._check_auth():
            return

        if self.path.startswith("/vault/"):
            filepath = self._vault_path()
            body = self._read_body()
            content = body.decode("utf-8", errors="replace")
            self._record_request("PUT", self.path, content)

            FakeObsidianHandler.vault[filepath] = {
                "content": content,
                "frontmatter": {},
                "tags": [],
                "stat": {
                    "ctime": int(time.time() * 1000),
                    "mtime": int(time.time() * 1000),
                    "size": len(content),
                },
            }
            self._send_empty(204)
            return

        self._send_json({"message": "Not found", "errorCode": 404}, status=404)

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)

        # POST /vault/{filename} — append to note
        if parsed.path.startswith("/vault/"):
            filepath = parsed.path[len("/vault/") :]
            body = self._read_body()
            content = body.decode("utf-8", errors="replace")
            self._record_request("POST", self.path, content)

            existing = FakeObsidianHandler.vault.get(filepath)
            if existing is not None:
                existing["content"] += content
                existing["stat"]["mtime"] = int(time.time() * 1000)
                existing["stat"]["size"] = len(existing["content"])
            else:
                FakeObsidianHandler.vault[filepath] = {
                    "content": content,
                    "frontmatter": {},
                    "tags": [],
                    "stat": {
                        "ctime": int(time.time() * 1000),
                        "mtime": int(time.time() * 1000),
                        "size": len(content),
                    },
                }
            self._send_empty(204)
            return

        # POST /search/simple/ — search vault notes
        if parsed.path.rstrip("/") == "/search/simple":
            self._record_request("POST", self.path)
            query_params = parse_qs(parsed.query)
            query = query_params.get("query", [""])[0]
            context_length = int(query_params.get("contextLength", ["100"])[0])

            results: list[dict[str, Any]] = []
            for filename, note in FakeObsidianHandler.vault.items():
                content = note["content"]
                content_lower = content.lower()
                query_lower = query.lower()

                if query_lower not in content_lower:
                    continue

                matches: list[dict[str, Any]] = []
                search_pos = 0
                while True:
                    idx = content_lower.find(query_lower, search_pos)
                    if idx == -1:
                        break
                    ctx_start = max(0, idx - context_length // 2)
                    ctx_end = min(len(content), idx + len(query) + context_length // 2)
                    matches.append(
                        {
                            "context": content[ctx_start:ctx_end],
                            "match": {
                                "start": idx - ctx_start,
                                "end": idx - ctx_start + len(query),
                            },
                        }
                    )
                    search_pos = idx + 1

                score = len(matches) / max(len(content), 1) * 100
                results.append(
                    {
                        "filename": filename,
                        "score": round(score, 4),
                        "matches": matches,
                    }
                )

            self._send_json(results)
            return

        self._send_json({"message": "Not found", "errorCode": 404}, status=404)

    def do_DELETE(self) -> None:
        if not self._check_auth():
            return

        if self.path.startswith("/vault/"):
            filepath = self._vault_path()
            self._record_request("DELETE", self.path)
            FakeObsidianHandler.vault.pop(filepath, None)
            self._send_empty(204)
            return

        self._send_json({"message": "Not found", "errorCode": 404}, status=404)


def start_fake_obsidian_server() -> tuple[HTTPServer, str]:
    """Start a fake Obsidian REST API server on a random port.

    Resets vault to SAMPLE_NOTES and clears recorded_requests.

    Returns:
        Tuple of (server_instance, base_url).
        The server runs in a daemon thread and stops when the test process exits.
    """
    FakeObsidianHandler.vault = _deep_copy_notes()
    FakeObsidianHandler.recorded_requests.clear()

    server = HTTPServer(("127.0.0.1", 0), FakeObsidianHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, base_url
