"""Gmail MCP stdio server — 6 tools for email management.

Runs as a subprocess of the Claw gateway, communicating via stdin/stdout JSON-RPC.
Credentials are read from environment variables (GMAIL_CREDENTIALS, GMAIL_TOKEN).

Tools:
  gmail_list     — List messages matching a Gmail search query
  gmail_read     — Read a specific message by ID (full body)
  gmail_draft    — Create a draft message
  gmail_send     — Send a message or draft (CONFIRM-GATED)
  gmail_archive  — Archive a message (CONFIRM-GATED)
  gmail_label    — Apply or remove labels
"""

import base64
import json
import logging
import os
import re
import sys
from email.mime.text import MIMEText
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("gmail-mcp")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

server = Server("gmail")


# --- Helper functions (testable independently) ---


def _extract_header(headers: list[dict[str, str]], name: str) -> str:
    """Extract a header value by name (case-insensitive)."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Extract plain-text body from a Gmail message payload.

    Prefers text/plain, falls back to HTML with tags stripped.
    Recurses into multipart payloads.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    if mime_type.startswith("multipart/"):
        parts = payload.get("parts", [])
        # Prefer text/plain
        for part in parts:
            if part.get("mimeType") == "text/plain":
                return _extract_body(part)
        # Fall back to first part
        if parts:
            return _extract_body(parts[0])

    # HTML fallback — strip tags
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", "", html)

    return ""


def _format_message_summary(msg: dict[str, Any]) -> dict[str, Any]:
    """Format a Gmail API message into a summary dict."""
    headers = msg.get("payload", {}).get("headers", [])
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "subject": _extract_header(headers, "Subject"),
        "from": _extract_header(headers, "From"),
        "to": _extract_header(headers, "To"),
        "date": _extract_header(headers, "Date"),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


def _parse_message_list_response(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse a list of Gmail API messages into a response dict."""
    return {
        "count": len(messages),
        "messages": [_format_message_summary(m) for m in messages],
    }


def _get_service() -> Any:
    """Build authenticated Gmail API service.

    Reads GMAIL_TOKEN env var for the stored OAuth token path.
    Automatically refreshes expired tokens and writes them back.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = os.environ.get("GMAIL_TOKEN", "")
    if not token_path or not os.path.exists(token_path):
        raise RuntimeError(
            f"Gmail token not found at {token_path!r}. "
            "Run: python -m mcp_servers.gmail_server --auth-setup"
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# --- MCP Tool Definitions ---


TOOLS = [
    Tool(
        name="gmail_list",
        description=(
            "List Gmail messages matching a search query. Uses Gmail search syntax "
            "(from:, subject:, is:unread, has:attachment, newer_than:, etc.)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query (e.g., 'is:unread', "
                        "'from:github.com subject:PR')"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of messages to return (default: 20, max: 100)"
                    ),
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="gmail_read",
        description=(
            "Read a specific Gmail message by ID. Returns full message body "
            "(plain text preferred, falls back to HTML stripped of tags)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID (from gmail_list results)",
                },
            },
            "required": ["message_id"],
        },
    ),
    Tool(
        name="gmail_draft",
        description=(
            "Create a Gmail draft message. Use this to compose a reply or new "
            "message before sending."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body (plain text)"},
                "in_reply_to": {
                    "type": "string",
                    "description": (
                        "Message ID to reply to (sets In-Reply-To and "
                        "References headers)"
                    ),
                },
            },
            "required": ["to", "subject", "body"],
        },
    ),
    Tool(
        name="gmail_send",
        description=(
            "Send a Gmail message. REQUIRES USER CONFIRMATION. "
            "Always draft first and show the user what will be sent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": (
                        "Draft ID to send (preferred — draft first, then send)"
                    ),
                },
                "to": {
                    "type": "string",
                    "description": (
                        "Recipient email (used only if not sending a draft)"
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": (
                        "Subject line (used only if not sending a draft)"
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Body text (used only if not sending a draft)"
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="gmail_archive",
        description=(
            "Archive a Gmail message by removing the INBOX label. "
            "REQUIRES USER CONFIRMATION."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID to archive",
                },
            },
            "required": ["message_id"],
        },
    ),
    Tool(
        name="gmail_label",
        description="Apply or remove a Gmail label from a message.",
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID",
                },
                "add_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to add",
                },
                "remove_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to remove",
                },
            },
            "required": ["message_id"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


_KNOWN_TOOLS = {
    "gmail_list", "gmail_read", "gmail_draft",
    "gmail_send", "gmail_archive", "gmail_label",
}


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name not in _KNOWN_TOOLS:
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"}),
        )]

    try:
        service = _get_service()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    try:
        if name == "gmail_list":
            return _handle_list(service, arguments)
        elif name == "gmail_read":
            return _handle_read(service, arguments)
        elif name == "gmail_draft":
            return _handle_draft(service, arguments)
        elif name == "gmail_send":
            return _handle_send(service, arguments)
        elif name == "gmail_archive":
            return _handle_archive(service, arguments)
        elif name == "gmail_label":
            return _handle_label(service, arguments)
        else:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}),
            )]
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


def _handle_list(service: Any, args: dict[str, Any]) -> list[TextContent]:
    query = args.get("query", "is:inbox")
    limit = min(args.get("limit", 20), 100)

    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=limit)
        .execute()
    )

    message_ids = results.get("messages", [])
    messages: list[dict[str, Any]] = []
    for msg_ref in message_ids:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            )
            .execute()
        )
        messages.append(_format_message_summary(msg))

    return [TextContent(
        type="text",
        text=json.dumps({"count": len(messages), "messages": messages}),
    )]


def _handle_read(service: Any, args: dict[str, Any]) -> list[TextContent]:
    message_id = args["message_id"]
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = msg.get("payload", {}).get("headers", [])
    body = _extract_body(msg.get("payload", {}))

    attachments: list[dict[str, Any]] = []
    for part in msg.get("payload", {}).get("parts", []):
        if part.get("filename"):
            attachments.append({
                "filename": part["filename"],
                "mime_type": part.get("mimeType", ""),
                "size_bytes": int(part.get("body", {}).get("size", 0)),
            })

    result = {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": _extract_header(headers, "Subject"),
        "from": _extract_header(headers, "From"),
        "to": _extract_header(headers, "To"),
        "date": _extract_header(headers, "Date"),
        "body": body,
        "labels": msg.get("labelIds", []),
        "attachments": attachments,
    }
    return [TextContent(type="text", text=json.dumps(result))]


def _handle_draft(service: Any, args: dict[str, Any]) -> list[TextContent]:
    message = MIMEText(args["body"])
    message["to"] = args["to"]
    message["subject"] = args["subject"]
    message["from"] = os.environ.get("GMAIL_ADDRESS", "")

    if args.get("in_reply_to"):
        message["In-Reply-To"] = args["in_reply_to"]
        message["References"] = args["in_reply_to"]

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )

    return [TextContent(type="text", text=json.dumps({
        "draft_id": draft["id"],
        "message_id": draft.get("message", {}).get("id", ""),
        "status": "created",
    }))]


def _handle_send(service: Any, args: dict[str, Any]) -> list[TextContent]:
    if args.get("draft_id"):
        result = (
            service.users()
            .drafts()
            .send(userId="me", body={"id": args["draft_id"]})
            .execute()
        )
    else:
        message = MIMEText(args.get("body", ""))
        message["to"] = args.get("to", "")
        message["subject"] = args.get("subject", "")
        message["from"] = os.environ.get("GMAIL_ADDRESS", "")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )

    return [TextContent(type="text", text=json.dumps({
        "message_id": result.get("id", ""),
        "status": "sent",
    }))]


def _handle_archive(service: Any, args: dict[str, Any]) -> list[TextContent]:
    message_id = args["message_id"]
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["INBOX"]},
    ).execute()
    return [TextContent(type="text", text=json.dumps({
        "message_id": message_id,
        "status": "archived",
    }))]


def _handle_label(service: Any, args: dict[str, Any]) -> list[TextContent]:
    message_id = args["message_id"]
    add_labels = args.get("add_labels", [])
    remove_labels = args.get("remove_labels", [])

    body: dict[str, list[str]] = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    service.users().messages().modify(
        userId="me",
        id=message_id,
        body=body,
    ).execute()

    return [TextContent(type="text", text=json.dumps({
        "message_id": message_id,
        "labels_added": add_labels,
        "labels_removed": remove_labels,
        "status": "updated",
    }))]


def _run_auth_setup() -> None:
    """Interactive OAuth2 consent flow (one-time setup)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = os.environ.get("GMAIL_CREDENTIALS", "")
    token_path = os.environ.get("GMAIL_TOKEN", "")

    if not creds_path or not os.path.exists(creds_path):
        print(
            f"ERROR: GMAIL_CREDENTIALS not found at {creds_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not token_path:
        print("ERROR: GMAIL_TOKEN env var not set", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_path, "w") as f:
        f.write(creds.to_json())
    print(f"Token saved to {token_path}", file=sys.stderr)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    if "--auth-setup" in sys.argv:
        _run_auth_setup()
    else:
        import asyncio

        asyncio.run(main())
