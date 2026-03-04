"""Fake Gmail API v1 server for contract testing.

Serves canned responses matching exact Gmail API response shapes
documented in the design doc. Validates request paths and auth headers.
"""

import base64
import json
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

# --- Sample data matching real Gmail API response shapes ---

SAMPLE_MESSAGES = [
    {
        "id": "18e1a2b3c4d5e6f7",
        "threadId": "18e1a2b3c4d5e6f7",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hey Thomas, here's the migration plan we discussed...",
        "internalDate": "1708905600000",
        "sizeEstimate": 12845,
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Date", "value": "Mon, 26 Feb 2026 10:00:00 -0500"},
                {"name": "From", "value": "Jane Doe <jane@example.com>"},
                {"name": "To", "value": "User <user@example.com>"},
                {"name": "Subject", "value": "Re: Migration Plan"},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "body": {
                        "size": 42,
                        "data": base64.urlsafe_b64encode(b"Hey Thomas, here is the migration plan.").decode(),
                    },
                },
                {
                    "partId": "1",
                    "mimeType": "text/html",
                    "body": {
                        "size": 80,
                        "data": base64.urlsafe_b64encode(b"<p>Hey Thomas, here is the migration plan.</p>").decode(),
                    },
                },
            ],
        },
    },
    {
        "id": "28f2b3c4d5e6f708",
        "threadId": "28f2b3c4d5e6f708",
        "labelIds": ["INBOX"],
        "snippet": "Your order has shipped...",
        "internalDate": "1708992000000",
        "sizeEstimate": 5432,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Date", "value": "Tue, 27 Feb 2026 08:00:00 -0500"},
                {"name": "From", "value": "Amazon <ship@amazon.com>"},
                {"name": "To", "value": "User <user@example.com>"},
                {"name": "Subject", "value": "Your order has shipped"},
            ],
            "body": {
                "size": 25,
                "data": base64.urlsafe_b64encode(b"Your order has shipped.").decode(),
            },
        },
    },
]

SAMPLE_LABELS = [
    {"id": "INBOX", "name": "INBOX", "type": "system"},
    {"id": "SENT", "name": "SENT", "type": "system"},
    {"id": "DRAFT", "name": "DRAFT", "type": "system"},
    {"id": "UNREAD", "name": "UNREAD", "type": "system"},
    {"id": "Label_1", "name": "Work", "type": "user"},
    {"id": "Label_2", "name": "ToReview", "type": "user"},
]

# Mutable state for modify/draft/send operations
_drafts: list[dict[str, Any]] = []
_sent: list[dict[str, Any]] = []
_label_changes: list[dict[str, Any]] = []


def reset_state() -> None:
    """Reset mutable state between tests."""
    _drafts.clear()
    _sent.clear()
    _label_changes.clear()


class FakeGmailHandler(BaseHTTPRequestHandler):
    """Serves Gmail API v1 endpoints with real response shapes."""

    def do_GET(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= 7:
            self._respond(
                401,
                {
                    "error": {
                        "code": 401,
                        "message": "Request is missing required authentication credential.",
                        "status": "UNAUTHENTICATED",
                    }
                },
            )
            return

        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # GET /gmail/v1/users/me/messages — list
        if path == "/gmail/v1/users/me/messages":
            max_results = int(qs.get("maxResults", ["20"])[0])
            refs = [{"id": m["id"], "threadId": m["threadId"]} for m in SAMPLE_MESSAGES[:max_results]]
            if refs:
                self._respond(200, {"messages": refs, "resultSizeEstimate": len(refs)})
            else:
                self._respond(200, {"resultSizeEstimate": 0})
            return

        # GET /gmail/v1/users/me/messages/{id} — get
        if path.startswith("/gmail/v1/users/me/messages/"):
            msg_id = path.split("/")[-1]
            fmt = qs.get("format", ["full"])[0]
            for msg in SAMPLE_MESSAGES:
                if msg["id"] == msg_id:
                    if fmt == "metadata":
                        metadata_headers = qs.get("metadataHeaders", [])
                        filtered_headers = (
                            [h for h in msg["payload"]["headers"] if h["name"] in metadata_headers]
                            if metadata_headers
                            else msg["payload"]["headers"]
                        )
                        self._respond(
                            200,
                            {
                                "id": msg["id"],
                                "threadId": msg["threadId"],
                                "labelIds": msg.get("labelIds", []),
                                "snippet": msg.get("snippet", ""),
                                "internalDate": msg.get("internalDate", "0"),
                                "sizeEstimate": msg.get("sizeEstimate", 0),
                                "payload": {
                                    "mimeType": msg["payload"]["mimeType"],
                                    "headers": filtered_headers,
                                    "body": {"size": 0},
                                },
                            },
                        )
                    else:
                        self._respond(200, msg)
                    return
            self._respond(404, {"error": {"code": 404, "message": "Not found.", "status": "NOT_FOUND"}})
            return

        # GET /gmail/v1/users/me/labels — list labels
        if path == "/gmail/v1/users/me/labels":
            self._respond(200, {"labels": SAMPLE_LABELS})
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}", "status": "NOT_FOUND"}})

    def do_POST(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= 7:
            self._respond(401, {"error": {"code": 401, "message": "Unauthenticated", "status": "UNAUTHENTICATED"}})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        parsed = urlparse(self.path)
        path = parsed.path

        # POST /gmail/v1/users/me/messages/{id}/modify
        if path.endswith("/modify"):
            msg_id = path.split("/")[-2]
            _label_changes.append({"message_id": msg_id, **body})
            # Return updated message with modified labels
            for msg in SAMPLE_MESSAGES:
                if msg["id"] == msg_id:
                    labels = list(msg.get("labelIds", []))
                    for lbl in body.get("removeLabelIds", []):
                        if lbl in labels:
                            labels.remove(lbl)
                    for lbl in body.get("addLabelIds", []):
                        if lbl not in labels:
                            labels.append(lbl)
                    self._respond(200, {**msg, "labelIds": labels})
                    return
            self._respond(404, {"error": {"code": 404, "message": "Not found.", "status": "NOT_FOUND"}})
            return

        # POST /gmail/v1/users/me/drafts — create draft
        if path == "/gmail/v1/users/me/drafts":
            draft_id = f"r-{len(_drafts) + 1}"
            _drafts.append({"id": draft_id, "message": body.get("message", {})})
            self._respond(
                200,
                {
                    "id": draft_id,
                    "message": {"id": f"msg-draft-{len(_drafts)}", "threadId": "thread-1", "labelIds": ["DRAFT"]},
                },
            )
            return

        # POST /gmail/v1/users/me/drafts/send — send draft
        if path == "/gmail/v1/users/me/drafts/send":
            _sent.append(body)
            self._respond(
                200,
                {
                    "id": f"msg-sent-{len(_sent)}",
                    "threadId": "thread-1",
                    "labelIds": ["SENT"],
                },
            )
            return

        # POST /gmail/v1/users/me/messages/send — send message
        if path == "/gmail/v1/users/me/messages/send":
            _sent.append(body)
            self._respond(
                200,
                {
                    "id": f"msg-sent-{len(_sent)}",
                    "threadId": body.get("threadId", "thread-new"),
                    "labelIds": ["SENT"],
                },
            )
            return

        self._respond(404, {"error": {"code": 404, "message": f"Not found: {path}", "status": "NOT_FOUND"}})

    def _respond(self, status: int, body: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format: str, *args: Any) -> None:
        pass
