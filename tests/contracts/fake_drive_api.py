"""Fake Google Drive v3 + Docs v1 API server for contract testing.

Serves canned responses matching real API shapes.
Tracks mutations (create, edit, delete, share) for assertion.

Endpoints:
    GET  /drive/v3/files                              → list files
    GET  /drive/v3/files/{id}                         → file metadata
    GET  /drive/v3/files/{id}/export                  → export content (text/CSV)
    POST /drive/v3/files                              → create file
    POST /drive/v3/files/{id}/permissions              → share file
    POST /v1/documents/{id}:batchUpdate               → edit Google Doc
    GET  /v1/documents/{id}                           → get Google Doc structure
    PATCH /drive/v3/files/{id}                        → update file (move, trash)
    DELETE /drive/v3/files/{id}                       → permanent delete

Auth: Bearer token required on all endpoints (401 if missing/invalid).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

SAMPLE_FILES: list[dict[str, Any]] = [
    {
        "id": "1BxiMVs0XRA5nFMdKvBdBZjg",
        "name": "Q4 Report",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2026-02-26T15:30:00.000Z",
        "size": "12345",
        "parents": ["0AK9folder"],
    },
    {
        "id": "2CyiNWt1YSB6oGNeLeDeAzhi",
        "name": "Budget 2026.xlsx",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "modifiedTime": "2026-02-25T10:00:00.000Z",
        "size": "8765",
        "parents": ["0AK9folder"],
    },
    {
        "id": "3DziOXu2ZTC7pH0fMgEfBaij",
        "name": "photo.jpg",
        "mimeType": "image/jpeg",
        "modifiedTime": "2026-02-24T08:00:00.000Z",
        "size": "2048000",
        "parents": ["0AK9photos"],
    },
]

SAMPLE_DOC_CONTENT = (
    "Q4 Report\n\nRevenue grew 15% YoY. Key highlights:\n- Cloud migration completed\n- New hire onboarding improved"
)

SAMPLE_CSV_CONTENT = "Category,Amount\nRevenue,150000\nExpenses,120000"

# Mutable state — reset between tests
_created_files: list[dict[str, Any]] = []
_batch_updates: list[dict[str, Any]] = []
_trashed: list[str] = []
_deleted: list[str] = []
_shared: list[dict[str, Any]] = []
_moved: list[dict[str, Any]] = []

# Lookup by file ID
_FILE_MAP: dict[str, dict[str, Any]] = {f["id"]: f for f in SAMPLE_FILES}


def reset_state() -> None:
    """Clear all mutable state between tests."""
    _created_files.clear()
    _batch_updates.clear()
    _trashed.clear()
    _deleted.clear()
    _shared.clear()
    _moved.clear()


def get_created_files() -> list[dict[str, Any]]:
    return list(_created_files)


def get_batch_updates() -> list[dict[str, Any]]:
    return list(_batch_updates)


def get_trashed() -> list[str]:
    return list(_trashed)


def get_deleted() -> list[str]:
    return list(_deleted)


def get_shared() -> list[dict[str, Any]]:
    return list(_shared)


def get_moved() -> list[dict[str, Any]]:
    return list(_moved)


class FakeDriveHandler(BaseHTTPRequestHandler):
    """Serves Drive v3 + Docs v1 endpoints with canned responses."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress request logging in test output."""

    def _check_auth(self) -> bool:
        """Validate Bearer token. Returns False and sends 401 if invalid."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= 7:
            self._respond(401, {"error": {"code": 401, "message": "Unauthorized"}})
            return False
        return True

    def _respond(self, status: int, body: Any) -> None:
        """Send a JSON response."""
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _respond_text(self, status: int, text: str) -> None:
        """Send a plain text response."""
        payload = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if not self._check_auth():
            return

        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # Drive: list files
        if path == "/drive/v3/files":
            q = qs.get("q", [None])[0]
            files = list(SAMPLE_FILES)
            if q:
                # Simple name-based filter
                if "name contains" in q:
                    search_term = q.split("'")[1] if "'" in q else ""
                    files = [f for f in files if search_term.lower() in f["name"].lower()]
                # modifiedTime filter (for cleanup queries)
                if "modifiedTime <" in q:
                    # Extract date like '2026-02-26T00:00:00'
                    import re as _re

                    m = _re.search(r"modifiedTime\s*<\s*'([^']+)'", q)
                    if m:
                        cutoff = m.group(1)
                        files = [f for f in files if f.get("modifiedTime", "") < cutoff]
            self._respond(200, {"kind": "drive#fileList", "files": files})
            return

        # Drive: export file content
        if path.endswith("/export"):
            file_id = path.split("/")[-2]
            file_meta = _FILE_MAP.get(file_id)
            if file_meta:
                if "document" in file_meta["mimeType"]:
                    self._respond_text(200, SAMPLE_DOC_CONTENT)
                elif "spreadsheet" in file_meta["mimeType"]:
                    self._respond_text(200, SAMPLE_CSV_CONTENT)
                else:
                    self._respond(
                        400,
                        {
                            "error": {"code": 400, "message": "Export not supported for this file type."},
                        },
                    )
                return
            self._respond(404, {"error": {"code": 404, "message": "File not found."}})
            return

        # Drive: get file metadata
        if path.startswith("/drive/v3/files/"):
            file_id = path.split("/")[-1]
            file_meta = _FILE_MAP.get(file_id)
            if file_meta:
                self._respond(200, file_meta)
            else:
                self._respond(404, {"error": {"code": 404, "message": "File not found."}})
            return

        # Docs: get document structure
        if path.startswith("/v1/documents/"):
            doc_id = path.split("/")[-1]
            if doc_id in _FILE_MAP:
                self._respond(
                    200,
                    {
                        "documentId": doc_id,
                        "title": _FILE_MAP[doc_id]["name"],
                        "body": {
                            "content": [
                                {
                                    "paragraph": {
                                        "elements": [
                                            {"textRun": {"content": SAMPLE_DOC_CONTENT}},
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                )
            else:
                self._respond(404, {"error": {"code": 404, "message": "Document not found."}})
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}"}})

    def do_POST(self) -> None:
        if not self._check_auth():
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
        path = urlparse(self.path).path

        # Drive: create file
        if path == "/drive/v3/files":
            new_file = {
                "id": f"new-{len(_created_files) + 1}",
                "name": body.get("name", "Untitled"),
                "mimeType": body.get("mimeType", "application/octet-stream"),
                "modifiedTime": "2026-02-27T12:00:00.000Z",
            }
            if "parents" in body:
                new_file["parents"] = body["parents"]
            _created_files.append(new_file)
            self._respond(200, new_file)
            return

        # Drive: share (permissions)
        if "/permissions" in path:
            file_id = path.split("/files/")[1].split("/")[0]
            _shared.append({"file_id": file_id, **body})
            self._respond(
                200,
                {
                    "id": f"perm-{len(_shared)}",
                    "type": body.get("type", "user"),
                    "role": body.get("role", "reader"),
                },
            )
            return

        # Docs: batchUpdate
        if path.endswith(":batchUpdate"):
            doc_id = path.split("/")[-1].replace(":batchUpdate", "")
            requests_list = body.get("requests", [])
            _batch_updates.append({"documentId": doc_id, "requests": requests_list})
            self._respond(
                200,
                {
                    "documentId": doc_id,
                    "replies": [{}] * len(requests_list),
                },
            )
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}"}})

    def do_PATCH(self) -> None:
        if not self._check_auth():
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(content_length)) if content_length > 0 else {}
        path = urlparse(self.path).path

        # Drive: update file (move, trash)
        if path.startswith("/drive/v3/files/"):
            file_id = path.split("/")[-1]

            qs = parse_qs(urlparse(self.path).query)

            if body.get("trashed"):
                _trashed.append(file_id)

            # Track moves (addParents/removeParents in query params)
            add_parents = qs.get("addParents", [None])[0]
            remove_parents = qs.get("removeParents", [None])[0]
            if add_parents or remove_parents:
                _moved.append(
                    {
                        "file_id": file_id,
                        "addParents": add_parents,
                        "removeParents": remove_parents,
                    }
                )

            self._respond(200, {"id": file_id, **body})
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}"}})

    def do_DELETE(self) -> None:
        if not self._check_auth():
            return

        path = urlparse(self.path).path
        if path.startswith("/drive/v3/files/"):
            file_id = path.split("/")[-1]
            _deleted.append(file_id)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}"}})


def start_fake_drive_server() -> tuple[HTTPServer, str]:
    """Start a fake Drive/Docs API server on a random port.

    Returns:
        Tuple of (server_instance, base_url).
        The server runs in a daemon thread.
    """
    reset_state()

    server = HTTPServer(("127.0.0.1", 0), FakeDriveHandler)
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, base_url
