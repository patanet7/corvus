"""Unified email tools — Gmail + Yahoo, multi-account.

Tools are async functions that return the standard tool response format:
    {"content": [{"type": "text", "text": json.dumps(...)}]}

They use module-level client instances set via configure().
"""

import base64
import re
from email.mime.text import MIMEText
from typing import Any

from corvus.google_client import GoogleClient
from corvus.tools.response import make_tool_response
from corvus.yahoo_client import YahooClient

# --- Module-level clients (set via configure()) ---

_google_client: GoogleClient | None = None
_yahoo_client: YahooClient | None = None


def configure(
    google_client: GoogleClient | None = None,
    yahoo_client: YahooClient | None = None,
) -> None:
    """Set client instances for email tools. Called at gateway startup and in tests."""
    global _google_client, _yahoo_client
    _google_client = google_client
    _yahoo_client = yahoo_client


def _get_google() -> GoogleClient:
    if _google_client:
        return _google_client
    return GoogleClient.from_env()


def _get_yahoo() -> YahooClient:
    if _yahoo_client:
        return _yahoo_client
    return YahooClient.from_env()


# --- Helper functions (ported from mcp_servers/gmail_server.py) ---


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
        for part in parts:
            if part.get("mimeType") == "text/plain":
                return _extract_body(part)
        if parts:
            return _extract_body(parts[0])

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
    """Format a list of Gmail messages into a response dict."""
    return {
        "count": len(messages),
        "messages": [_format_message_summary(m) for m in messages],
    }


# --- Gmail tool implementations ---


def _gmail_list(client: GoogleClient, query: str, limit: int = 20, account: str | None = None) -> dict[str, Any]:
    """Search Gmail messages. Returns formatted summaries."""
    limit = min(limit, 100)
    resp = client.request(
        "GET",
        "/gmail/v1/users/me/messages",
        account=account,
        params={"q": query, "maxResults": limit},
    )

    message_ids = resp.get("messages", [])
    messages: list[dict[str, Any]] = []
    for ref in message_ids:
        msg = client.request(
            "GET",
            f"/gmail/v1/users/me/messages/{ref['id']}",
            account=account,
            params={
                "format": "metadata",
                "metadataHeaders": ["Subject", "From", "To", "Date"],
            },
        )
        messages.append(_format_message_summary(msg))

    return {"count": len(messages), "messages": messages}


def _gmail_read(client: GoogleClient, message_id: str, account: str | None = None) -> dict[str, Any]:
    """Read a full Gmail message by ID."""
    msg = client.request(
        "GET",
        f"/gmail/v1/users/me/messages/{message_id}",
        account=account,
        params={"format": "full"},
    )

    headers = msg.get("payload", {}).get("headers", [])
    body = _extract_body(msg.get("payload", {}))

    attachments: list[dict[str, Any]] = []
    for part in msg.get("payload", {}).get("parts", []):
        if part.get("filename"):
            attachments.append(
                {
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType", ""),
                    "size_bytes": int(part.get("body", {}).get("size", 0)),
                }
            )

    return {
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


# --- Yahoo tool implementations ---


def _yahoo_list(client: YahooClient, query: str, limit: int = 20, account: str | None = None) -> dict[str, Any]:
    """Search Yahoo Mail via IMAP SEARCH."""
    import email

    imap = client.connect(account)
    try:
        imap.select("INBOX")
        _, data = imap.search(None, "SUBJECT", f'"{query}"')
        msg_nums = data[0].split()[-limit:] if data[0] else []

        messages: list[dict[str, Any]] = []
        for num in msg_nums:
            _, msg_data = imap.fetch(num, "(RFC822.HEADER)")
            if msg_data and msg_data[0]:
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
                parsed = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode())
                messages.append(
                    {
                        "id": num.decode() if isinstance(num, bytes) else str(num),
                        "subject": str(parsed.get("Subject", "")),
                        "from": str(parsed.get("From", "")),
                        "to": str(parsed.get("To", "")),
                        "date": str(parsed.get("Date", "")),
                    }
                )

        return {"count": len(messages), "messages": messages}
    finally:
        imap.logout()


def _yahoo_read(client: YahooClient, message_id: str, account: str | None = None) -> dict[str, Any]:
    """Read a Yahoo Mail message by sequence number."""
    import email

    imap = client.connect(account)
    try:
        imap.select("INBOX")
        _, msg_data = imap.fetch(message_id, "(RFC822)")
        if not msg_data or not msg_data[0]:
            return {"error": f"Message {message_id} not found"}

        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
        parsed = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode())

        body = ""
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == "text/plain":
                    payload_bytes = part.get_payload(decode=True)
                    if isinstance(payload_bytes, bytes):
                        body = payload_bytes.decode("utf-8", errors="replace")
                    break
        else:
            payload_bytes = parsed.get_payload(decode=True)
            if isinstance(payload_bytes, bytes):
                body = payload_bytes.decode("utf-8", errors="replace")

        return {
            "id": message_id,
            "subject": str(parsed.get("Subject", "")),
            "from": str(parsed.get("From", "")),
            "to": str(parsed.get("To", "")),
            "date": str(parsed.get("Date", "")),
            "body": body,
        }
    finally:
        imap.logout()


# --- Tool entry points (async, standard response format) ---
# NOTE: When claude_agent_sdk is available, decorate these with @tool.
# Tests call these functions directly, so they work with or without the SDK.


async def email_list(args: dict[str, Any]) -> dict[str, Any]:
    """Search email messages across Gmail or Yahoo."""
    provider = args.get("provider", "gmail")
    query = args.get("query", "is:inbox")
    account = args.get("account")
    limit = args.get("limit", 20)

    if provider == "gmail":
        result = _gmail_list(_get_google(), query, limit, account)
    elif provider == "yahoo":
        result = _yahoo_list(_get_yahoo(), query, limit, account)
    else:
        result = {"error": f"Unknown provider: {provider}"}

    return make_tool_response(result)


async def email_read(args: dict[str, Any]) -> dict[str, Any]:
    """Read a full email message by ID."""
    provider = args.get("provider", "gmail")
    message_id = args["message_id"]
    account = args.get("account")

    if provider == "gmail":
        result = _gmail_read(_get_google(), message_id, account)
    elif provider == "yahoo":
        result = _yahoo_read(_get_yahoo(), message_id, account)
    else:
        result = {"error": f"Unknown provider: {provider}"}

    return make_tool_response(result)


# --- Gmail write helper functions ---


def _get_from_address(client: GoogleClient, account: str | None) -> str:
    """Get the from address for an account, returning empty string if unavailable."""
    acct_name = account or client.default_account
    if acct_name and acct_name in client._accounts:
        return client.get_account_email(acct_name)
    return ""


def _gmail_draft(
    client: GoogleClient,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Create a Gmail draft."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    email_addr = _get_from_address(client, account)
    message["from"] = email_addr
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    resp = client.request(
        "POST",
        "/gmail/v1/users/me/drafts",
        account=account,
        json={"message": {"raw": raw}},
    )
    return {
        "draft_id": resp["id"],
        "message_id": resp.get("message", {}).get("id", ""),
        "status": "created",
    }


def _gmail_send(
    client: GoogleClient,
    draft_id: str | None = None,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Send a Gmail message or draft."""
    if draft_id:
        resp = client.request(
            "POST",
            "/gmail/v1/users/me/drafts/send",
            account=account,
            json={"id": draft_id},
        )
    else:
        message = MIMEText(body or "")
        message["to"] = to or ""
        message["subject"] = subject or ""
        email_addr = _get_from_address(client, account)
        message["from"] = email_addr
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        resp = client.request(
            "POST",
            "/gmail/v1/users/me/messages/send",
            account=account,
            json={"raw": raw},
        )
    return {"message_id": resp.get("id", ""), "status": "sent"}


def _gmail_archive(
    client: GoogleClient,
    message_id: str,
    account: str | None = None,
) -> dict[str, Any]:
    """Archive a Gmail message (remove INBOX label)."""
    client.request(
        "POST",
        f"/gmail/v1/users/me/messages/{message_id}/modify",
        account=account,
        json={"removeLabelIds": ["INBOX"]},
    )
    return {"message_id": message_id, "status": "archived"}


def _gmail_label(
    client: GoogleClient,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Add or remove Gmail labels from a message."""
    body: dict[str, list[str]] = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    client.request(
        "POST",
        f"/gmail/v1/users/me/messages/{message_id}/modify",
        account=account,
        json=body,
    )
    return {
        "message_id": message_id,
        "labels_added": add_labels or [],
        "labels_removed": remove_labels or [],
        "status": "updated",
    }


def _gmail_labels(
    client: GoogleClient,
    account: str | None = None,
) -> dict[str, Any]:
    """List available Gmail labels."""
    resp = client.request("GET", "/gmail/v1/users/me/labels", account=account)
    return {"labels": resp.get("labels", [])}


# --- Write operation tool entry points ---


async def email_draft(args: dict[str, Any]) -> dict[str, Any]:
    """Create a Gmail draft message."""
    result = _gmail_draft(
        _get_google(),
        args["to"],
        args["subject"],
        args["body"],
        in_reply_to=args.get("in_reply_to"),
        account=args.get("account"),
    )
    return make_tool_response(result)


async def email_send(args: dict[str, Any]) -> dict[str, Any]:
    """Send an email or draft. REQUIRES USER CONFIRMATION."""
    result = _gmail_send(
        _get_google(),
        draft_id=args.get("draft_id"),
        to=args.get("to"),
        subject=args.get("subject"),
        body=args.get("body"),
        account=args.get("account"),
    )
    return make_tool_response(result)


async def email_archive(args: dict[str, Any]) -> dict[str, Any]:
    """Archive a message. Gmail: removes INBOX label. REQUIRES CONFIRMATION."""
    provider = args.get("provider", "gmail")
    if provider == "gmail":
        result = _gmail_archive(_get_google(), args["message_id"], account=args.get("account"))
    else:
        result = {"error": f"Archive not implemented for {provider}"}
    return make_tool_response(result)


async def email_label(args: dict[str, Any]) -> dict[str, Any]:
    """Add or remove Gmail labels from a message."""
    result = _gmail_label(
        _get_google(),
        args["message_id"],
        add_labels=args.get("add_labels"),
        remove_labels=args.get("remove_labels"),
        account=args.get("account"),
    )
    return make_tool_response(result)


async def email_labels(args: dict[str, Any]) -> dict[str, Any]:
    """List available Gmail labels."""
    result = _gmail_labels(_get_google(), account=args.get("account"))
    return make_tool_response(result)
