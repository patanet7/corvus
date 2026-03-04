#!/usr/bin/env python3
"""Email inbox management CLI — Gmail (Google API) + Yahoo (IMAP).

Usage:
    python inbox.py gmail-search "<query>" [--limit N] [--label LABEL]
    python inbox.py gmail-labels
    python inbox.py gmail-unread [--limit N]
    python inbox.py gmail-bulk-label <label> --query "<query>"
    python inbox.py yahoo-search "<query>" [--limit N] [--folder FOLDER]
    python inbox.py yahoo-unread [--limit N]
    python inbox.py yahoo-folders
    python inbox.py triage [--provider gmail|yahoo|all]
    python inbox.py cleanup --provider <provider> --older-than 30d [--dry-run]

All output is JSON to stdout, errors to stderr.
Credentials come from env vars — NEVER from .env files.

Env vars:
    GMAIL_CREDENTIALS  — path to Google OAuth credentials JSON
    GMAIL_TOKEN        — path to stored OAuth token JSON
    YAHOO_EMAIL        — Yahoo email address
    YAHOO_APP_PASSWORD — Yahoo app password for IMAP
"""

import argparse
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import ssl
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(msg: str, code: int = 1) -> None:
    """Print JSON error to stderr and exit."""
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


def _output(data: Any) -> None:
    """Print JSON result to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _decode_header(raw: str | None) -> str:
    """Decode a MIME-encoded email header to plain text."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _parse_age(age_str: str) -> timedelta:
    """Parse an age string like '30d', '2w', '6h' into a timedelta."""
    match = re.match(r"^(\d+)([dhwm])$", age_str.strip())
    if not match:
        _error(f"Invalid age format: {age_str!r}. Use <number><d|h|w|m> (e.g., 30d, 2w)")
        raise SystemExit(1)  # unreachable, helps mypy
    value, unit = int(match.group(1)), match.group(2)
    if unit == "d":
        return timedelta(days=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit == "m":
        return timedelta(days=value * 30)
    return timedelta(days=value)


# ---------------------------------------------------------------------------
# Triage categories — keyword-based classification
# ---------------------------------------------------------------------------

TRIAGE_RULES: list[dict[str, Any]] = [
    {
        "category": "action",
        "description": "Requires your action or response",
        "patterns": [
            r"(?i)\baction required\b",
            r"(?i)\bplease respond\b",
            r"(?i)\bplease review\b",
            r"(?i)\bfollow up\b",
            r"(?i)\bdeadline\b",
            r"(?i)\bdue date\b",
            r"(?i)\brequest\b",
            r"(?i)\bapproval needed\b",
            r"(?i)\brsvp\b",
            r"(?i)\bconfirm\b",
        ],
    },
    {
        "category": "delegate",
        "description": "Can be forwarded or delegated",
        "patterns": [
            r"(?i)\bfyi\b",
            r"(?i)\bfor your information\b",
            r"(?i)\bfyi only\b",
            r"(?i)\bno action needed\b",
        ],
    },
    {
        "category": "archive",
        "description": "Informational, can be archived",
        "patterns": [
            r"(?i)\bnewsletter\b",
            r"(?i)\bdigest\b",
            r"(?i)\bweekly update\b",
            r"(?i)\bmonthly report\b",
            r"(?i)\bnotification\b",
            r"(?i)\balert\b",
            r"(?i)\breceipt\b",
            r"(?i)\bconfirmation\b",
            r"(?i)\bno.?reply\b",
        ],
    },
    {
        "category": "delete",
        "description": "Likely spam or promotional",
        "patterns": [
            r"(?i)\bunsubscribe\b",
            r"(?i)\bpromotion\b",
            r"(?i)\bspecial offer\b",
            r"(?i)\blimited time\b",
            r"(?i)\bdiscount\b",
            r"(?i)\bfree trial\b",
            r"(?i)\bclick here\b",
            r"(?i)\bact now\b",
        ],
    },
]


def _categorize_message(subject: str, sender: str, snippet: str = "") -> str:
    """Categorize an email based on subject, sender, and snippet."""
    text = f"{subject} {sender} {snippet}"
    for rule in TRIAGE_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, text):
                return str(rule["category"])
    return "review"  # default: needs human review


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------


def _get_gmail_service() -> Any:
    """Build and return a Gmail API service client."""
    creds_path = os.environ.get("GMAIL_CREDENTIALS", "")
    token_path = os.environ.get("GMAIL_TOKEN", "")

    if not creds_path:
        _error("GMAIL_CREDENTIALS env var is not set (path to credentials JSON)")
    if not os.path.isfile(creds_path):
        _error(f"Gmail credentials file not found: {creds_path}")

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.labels",
    ]

    creds = None
    if token_path and os.path.isfile(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        if token_path:
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _gmail_message_to_dict(msg: dict[str, Any]) -> dict[str, Any]:
    """Extract useful fields from a Gmail API message resource."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("subject", "(no subject)"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "labels": msg.get("labelIds", []),
    }


# ---------------------------------------------------------------------------
# Gmail commands
# ---------------------------------------------------------------------------


def cmd_gmail_search(args: argparse.Namespace) -> None:
    """Search Gmail messages."""
    service = _get_gmail_service()
    query = args.query
    if args.label:
        query = f"label:{args.label} {query}"

    results = service.users().messages().list(userId="me", q=query, maxResults=args.limit).execute()

    messages = results.get("messages", [])
    if not messages:
        _output({"count": 0, "messages": []})
        return

    detailed: list[dict[str, Any]] = []
    for msg_ref in messages:
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
        detailed.append(_gmail_message_to_dict(msg))

    _output({"count": len(detailed), "messages": detailed})


def cmd_gmail_labels(args: argparse.Namespace) -> None:
    """List Gmail labels."""
    service = _get_gmail_service()
    results = service.users().labels().list(userId="me").execute()
    labels = [{"id": lbl["id"], "name": lbl["name"], "type": lbl.get("type", "")} for lbl in results.get("labels", [])]
    _output({"count": len(labels), "labels": labels})


def cmd_gmail_unread(args: argparse.Namespace) -> None:
    """List unread Gmail messages."""
    service = _get_gmail_service()
    results = service.users().messages().list(userId="me", q="is:unread", maxResults=args.limit).execute()

    messages = results.get("messages", [])
    if not messages:
        _output({"count": 0, "messages": []})
        return

    detailed: list[dict[str, Any]] = []
    for msg_ref in messages:
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
        detailed.append(_gmail_message_to_dict(msg))

    _output({"count": len(detailed), "messages": detailed})


def cmd_gmail_bulk_label(args: argparse.Namespace) -> None:
    """Apply a label to all messages matching a query."""
    service = _get_gmail_service()

    # Resolve label ID from name
    all_labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label_map = {lbl["name"].lower(): lbl["id"] for lbl in all_labels}
    label_id = label_map.get(args.label.lower())

    if not label_id:
        # Create the label if it doesn't exist
        new_label = (
            service.users()
            .labels()
            .create(
                userId="me",
                body={"name": args.label, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            )
            .execute()
        )
        label_id = new_label["id"]

    results = service.users().messages().list(userId="me", q=args.query, maxResults=500).execute()

    messages = results.get("messages", [])
    if not messages:
        _output({"count": 0, "label": args.label, "applied": False})
        return

    msg_ids = [m["id"] for m in messages]
    service.users().messages().batchModify(
        userId="me",
        body={"ids": msg_ids, "addLabelIds": [label_id]},
    ).execute()

    _output({"count": len(msg_ids), "label": args.label, "label_id": label_id, "applied": True})


# ---------------------------------------------------------------------------
# Yahoo IMAP helpers
# ---------------------------------------------------------------------------


def _get_yahoo_imap() -> imaplib.IMAP4_SSL:
    """Connect and authenticate to Yahoo IMAP."""
    yahoo_email = os.environ.get("YAHOO_EMAIL", "")
    yahoo_password = os.environ.get("YAHOO_APP_PASSWORD", "")

    if not yahoo_email:
        _error("YAHOO_EMAIL env var is not set")
    if not yahoo_password:
        _error("YAHOO_APP_PASSWORD env var is not set")

    context = ssl.create_default_context()
    try:
        conn = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993, ssl_context=context)
        conn.login(yahoo_email, yahoo_password)
    except imaplib.IMAP4.error as e:
        _error(f"Yahoo IMAP login failed: {e}")
    except (ConnectionRefusedError, OSError) as e:
        _error(f"Yahoo IMAP connection failed: {e}")

    return conn


def _parse_imap_message(msg_data: bytes) -> dict[str, str]:
    """Parse raw IMAP message bytes into a dict."""
    msg = email.message_from_bytes(msg_data)
    return {
        "subject": _decode_header(msg.get("Subject")),
        "from": _decode_header(msg.get("From")),
        "to": _decode_header(msg.get("To")),
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
    }


def _imap_search_and_fetch(
    conn: imaplib.IMAP4_SSL,
    folder: str,
    criteria: str,
    limit: int,
) -> list[dict[str, str]]:
    """Search a folder and fetch message headers."""
    status, _ = conn.select(folder, readonly=True)
    if status != "OK":
        _error(f"Cannot select folder: {folder}")

    status, msg_nums = conn.search(None, criteria)
    if status != "OK":
        return []

    ids = msg_nums[0].split()
    if not ids:
        return []

    # Take the most recent N messages (last in list = most recent)
    ids = ids[-limit:]
    ids.reverse()

    messages: list[dict[str, str]] = []
    for msg_id in ids:
        status, data = conn.fetch(msg_id, "(RFC822.HEADER)")
        if status == "OK" and data and data[0] and isinstance(data[0], tuple):
            parsed = _parse_imap_message(data[0][1])
            parsed["uid"] = msg_id.decode()
            parsed["folder"] = folder
            messages.append(parsed)

    return messages


# ---------------------------------------------------------------------------
# Yahoo commands
# ---------------------------------------------------------------------------


def cmd_yahoo_search(args: argparse.Namespace) -> None:
    """Search Yahoo Mail via IMAP."""
    conn = _get_yahoo_imap()
    try:
        folder = args.folder or "INBOX"
        # IMAP SEARCH with SUBJECT criterion
        criteria = f'(SUBJECT "{args.query}")'
        messages = _imap_search_and_fetch(conn, folder, criteria, args.limit)
        _output({"count": len(messages), "messages": messages, "provider": "yahoo"})
    finally:
        conn.logout()


def cmd_yahoo_unread(args: argparse.Namespace) -> None:
    """List unread Yahoo Mail messages."""
    conn = _get_yahoo_imap()
    try:
        messages = _imap_search_and_fetch(conn, "INBOX", "(UNSEEN)", args.limit)
        _output({"count": len(messages), "messages": messages, "provider": "yahoo"})
    finally:
        conn.logout()


def cmd_yahoo_folders(args: argparse.Namespace) -> None:
    """List Yahoo Mail folders."""
    conn = _get_yahoo_imap()
    try:
        status, folder_list = conn.list()
        if status != "OK":
            _error("Failed to list Yahoo folders")

        folders: list[dict[str, str]] = []
        for item in folder_list:
            if isinstance(item, bytes):
                decoded = item.decode("utf-8", errors="replace")
                # Parse IMAP LIST response: (\\flags) "delimiter" "name"
                match = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+"?([^"]*)"?', decoded)
                if match:
                    folders.append(
                        {
                            "flags": match.group(1),
                            "delimiter": match.group(2),
                            "name": match.group(3).strip('"'),
                        }
                    )

        _output({"count": len(folders), "folders": folders, "provider": "yahoo"})
    finally:
        conn.logout()


# ---------------------------------------------------------------------------
# Cross-provider: triage
# ---------------------------------------------------------------------------


def cmd_triage(args: argparse.Namespace) -> None:
    """Triage unread messages across one or both providers."""
    provider = args.provider
    results: dict[str, Any] = {"action": [], "delegate": [], "archive": [], "delete": [], "review": []}
    errors: list[str] = []

    if provider in ("gmail", "all"):
        try:
            service = _get_gmail_service()
            resp = service.users().messages().list(userId="me", q="is:unread", maxResults=50).execute()
            for msg_ref in resp.get("messages", []):
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From"],
                    )
                    .execute()
                )
                info = _gmail_message_to_dict(msg)
                category = _categorize_message(info["subject"], info["from"], info["snippet"])
                info["provider"] = "gmail"
                results[category].append(info)
        except Exception as e:
            errors.append(f"Gmail error: {e}")

    if provider in ("yahoo", "all"):
        try:
            conn = _get_yahoo_imap()
            try:
                messages = _imap_search_and_fetch(conn, "INBOX", "(UNSEEN)", 50)
                for msg in messages:
                    category = _categorize_message(msg["subject"], msg["from"])
                    msg["provider"] = "yahoo"
                    results[category].append(msg)
            finally:
                conn.logout()
        except SystemExit:
            raise
        except Exception as e:
            errors.append(f"Yahoo error: {e}")

    summary = {cat: len(msgs) for cat, msgs in results.items()}
    _output(
        {
            "triage": results,
            "summary": summary,
            "total": sum(summary.values()),
            "errors": errors,
        }
    )


# ---------------------------------------------------------------------------
# Cross-provider: cleanup
# ---------------------------------------------------------------------------


def cmd_cleanup(args: argparse.Namespace) -> None:
    """Bulk cleanup old messages."""
    cutoff = _parse_age(args.older_than)
    cutoff_date = datetime.now(UTC) - cutoff
    dry_run = args.dry_run

    if args.provider == "gmail":
        service = _get_gmail_service()
        date_str = cutoff_date.strftime("%Y/%m/%d")
        query = f"before:{date_str}"
        resp = service.users().messages().list(userId="me", q=query, maxResults=500).execute()

        messages = resp.get("messages", [])
        count = len(messages)

        if not dry_run and messages:
            msg_ids = [m["id"] for m in messages]
            service.users().messages().batchModify(
                userId="me",
                body={"ids": msg_ids, "removeLabelIds": ["INBOX"]},
            ).execute()

        _output(
            {
                "provider": "gmail",
                "older_than": args.older_than,
                "cutoff_date": cutoff_date.isoformat(),
                "messages_found": count,
                "action": "archived" if not dry_run else "dry_run",
                "dry_run": dry_run,
            }
        )

    elif args.provider == "yahoo":
        conn = _get_yahoo_imap()
        try:
            date_str = cutoff_date.strftime("%d-%b-%Y")
            criteria = f"(BEFORE {date_str})"

            status, _ = conn.select("INBOX", readonly=dry_run)
            if status != "OK":
                _error("Cannot select Yahoo INBOX")

            status, msg_nums = conn.search(None, criteria)
            ids = msg_nums[0].split() if status == "OK" and msg_nums[0] else []
            count = len(ids)

            if not dry_run and ids:
                for msg_id in ids:
                    conn.store(msg_id, "+FLAGS", "\\Deleted")
                conn.expunge()

            _output(
                {
                    "provider": "yahoo",
                    "older_than": args.older_than,
                    "cutoff_date": cutoff_date.isoformat(),
                    "messages_found": count,
                    "action": "deleted" if not dry_run else "dry_run",
                    "dry_run": dry_run,
                }
            )
        finally:
            conn.logout()
    else:
        _error(f"Unknown provider: {args.provider}. Use gmail or yahoo.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Email inbox management CLI (Gmail + Yahoo)",
        prog="inbox.py",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # gmail-search
    p = sub.add_parser("gmail-search", help="Search Gmail messages")
    p.add_argument("query", help="Gmail search query")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--label", help="Filter by label name")

    # gmail-labels
    sub.add_parser("gmail-labels", help="List Gmail labels")

    # gmail-unread
    p = sub.add_parser("gmail-unread", help="List unread Gmail messages")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    # gmail-bulk-label
    p = sub.add_parser("gmail-bulk-label", help="Bulk label Gmail messages")
    p.add_argument("label", help="Label to apply")
    p.add_argument("--query", required=True, help="Gmail search query to match messages")

    # yahoo-search
    p = sub.add_parser("yahoo-search", help="Search Yahoo Mail")
    p.add_argument("query", help="Search term (matched against subject)")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--folder", default=None, help="Folder to search (default: INBOX)")

    # yahoo-unread
    p = sub.add_parser("yahoo-unread", help="List unread Yahoo messages")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    # yahoo-folders
    sub.add_parser("yahoo-folders", help="List Yahoo folders")

    # triage
    p = sub.add_parser("triage", help="Categorize unread messages")
    p.add_argument(
        "--provider",
        default="all",
        choices=["gmail", "yahoo", "all"],
        help="Provider to triage (default: all)",
    )

    # cleanup
    p = sub.add_parser("cleanup", help="Bulk cleanup old messages")
    p.add_argument("--provider", required=True, choices=["gmail", "yahoo"], help="Provider")
    p.add_argument("--older-than", required=True, help="Age cutoff (e.g., 30d, 2w, 6m)")
    p.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    return parser


def main() -> None:
    """Parse arguments and dispatch to subcommand handler."""
    parser = build_parser()
    args = parser.parse_args()

    dispatch: dict[str, Any] = {
        "gmail-search": cmd_gmail_search,
        "gmail-labels": cmd_gmail_labels,
        "gmail-unread": cmd_gmail_unread,
        "gmail-bulk-label": cmd_gmail_bulk_label,
        "yahoo-search": cmd_yahoo_search,
        "yahoo-unread": cmd_yahoo_unread,
        "yahoo-folders": cmd_yahoo_folders,
        "triage": cmd_triage,
        "cleanup": cmd_cleanup,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        _error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
