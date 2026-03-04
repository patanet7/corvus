"""Google Drive/Docs tools — direct functions for file management.

Tools:
    drive_list             — List/search files (Drive v3)
    drive_read             — Read file metadata + content
    drive_create           — Create a file or Google Doc
    drive_edit             — Edit a Google Doc (insertText, replaceAllText)
    drive_move             — Move a file to a different folder
    drive_delete           — Trash a file (CONFIRM-GATED)
    drive_permanent_delete — Permanently delete a file (CONFIRM-GATED)
    drive_share            — Share a file with a user (CONFIRM-GATED)
    drive_cleanup          — Find/trash old files (CONFIRM-GATED unless dry_run)

Configuration:
    Call configure(google_client) with a GoogleClient instance before use.

NOTE: When claude_agent_sdk is available, decorate tool functions with @tool.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import requests as http_requests

from corvus.google_client import GoogleClient
from corvus.tools.response import make_error_response, make_tool_response

# Module-level configuration set via configure()
_client: GoogleClient | None = None


def configure(client: GoogleClient) -> None:
    """Set the GoogleClient instance for all drive tools.

    Args:
        client: Configured GoogleClient with base_url and auth.
    """
    global _client  # noqa: PLW0603
    _client = client


def _get_client() -> GoogleClient:
    """Return the configured GoogleClient or raise."""
    if _client is None:
        raise RuntimeError("Drive tools not configured. Call gateway.tools.drive.configure(client) first.")
    return _client


def _request_text(method: str, path: str, account: str | None = None, **kwargs: Any) -> str:
    """Make an authenticated request that returns plain text (for exports)."""
    client = _get_client()
    token = client._get_token(account)
    url = f"{client._base_url}{path}" if client._base_url else path
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_requests.request(method, url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return str(resp.text)


# --- Tool functions ---


def drive_list(
    account: str | None = None,
    query: str | None = None,
    folder_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List or search files in Google Drive.

    Args:
        account: Google account name. Uses default if None.
        query: Drive search query (e.g., "name contains 'report'").
        folder_id: Restrict to files in this folder.
        limit: Maximum number of files to return.

    Returns:
        Tool response with files array.
    """
    try:
        client = _get_client()
        params: dict[str, Any] = {"pageSize": limit}

        q_parts = []
        if query:
            q_parts.append(query)
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if q_parts:
            params["q"] = " and ".join(q_parts)

        data = client.request("GET", "/drive/v3/files", account=account, params=params)
        files = data.get("files", [])
        return make_tool_response(
            {
                "count": len(files),
                "files": files,
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_read(
    file_id: str,
    account: str | None = None,
) -> dict[str, Any]:
    """Read file metadata and content from Google Drive.

    Google Docs → exported as plain text.
    Google Sheets → exported as CSV.
    Other files → metadata only.

    Args:
        file_id: Drive file ID.
        account: Google account name.

    Returns:
        Tool response with metadata and optional content.
    """
    try:
        client = _get_client()

        # Get metadata
        metadata = client.request("GET", f"/drive/v3/files/{file_id}", account=account)

        result: dict[str, Any] = {"metadata": metadata}

        mime = metadata.get("mimeType", "")

        # Export Google Docs as plain text
        if "document" in mime:
            content = _request_text(
                "GET",
                f"/drive/v3/files/{file_id}/export",
                account=account,
                params={"mimeType": "text/plain"},
            )
            result["content"] = content
            result["export_format"] = "text/plain"

        # Export Google Sheets as CSV
        elif "spreadsheet" in mime:
            content = _request_text(
                "GET",
                f"/drive/v3/files/{file_id}/export",
                account=account,
                params={"mimeType": "text/csv"},
            )
            result["content"] = content
            result["export_format"] = "text/csv"

        return make_tool_response(result)
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_create(
    name: str,
    account: str | None = None,
    mime_type: str | None = None,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Create a file or Google Doc in Drive.

    Args:
        name: File name.
        account: Google account name.
        mime_type: MIME type. Defaults to Google Doc if not specified.
        folder_id: Parent folder ID.

    Returns:
        Tool response with the created file metadata.
    """
    try:
        client = _get_client()
        body: dict[str, Any] = {
            "name": name,
            "mimeType": mime_type or "application/vnd.google-apps.document",
        }
        if folder_id:
            body["parents"] = [folder_id]

        result = client.request("POST", "/drive/v3/files", account=account, json=body)
        return make_tool_response(result)
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_edit(
    file_id: str,
    account: str | None = None,
    insertions: list[dict[str, Any]] | None = None,
    replacements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Edit a Google Doc using batchUpdate.

    Args:
        file_id: Document ID.
        account: Google account name.
        insertions: List of {"index": int, "text": str} to insert.
        replacements: List of {"old": str, "new": str, "match_case": bool} to replace.

    Returns:
        Tool response confirming the edit.
    """
    try:
        client = _get_client()
        requests_list: list[dict[str, Any]] = []

        if insertions:
            for ins in insertions:
                requests_list.append(
                    {
                        "insertText": {
                            "location": {"index": ins["index"]},
                            "text": ins["text"],
                        },
                    }
                )

        if replacements:
            for rep in replacements:
                requests_list.append(
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": rep["old"],
                                "matchCase": rep.get("match_case", True),
                            },
                            "replaceText": rep["new"],
                        },
                    }
                )

        if not requests_list:
            return make_error_response("No insertions or replacements provided.")

        result = client.request(
            "POST",
            f"/v1/documents/{file_id}:batchUpdate",
            account=account,
            json={"requests": requests_list},
        )
        return make_tool_response(
            {
                "status": "ok",
                "documentId": result.get("documentId", file_id),
                "changes_applied": len(requests_list),
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Docs API error: {e.response.status_code} {e.response.text}")


def drive_move(
    file_id: str,
    folder_id: str,
    account: str | None = None,
) -> dict[str, Any]:
    """Move a file to a different folder.

    Args:
        file_id: File to move.
        folder_id: Destination folder ID.
        account: Google account name.

    Returns:
        Tool response confirming the move.
    """
    try:
        client = _get_client()
        result = client.request(
            "PATCH",
            f"/drive/v3/files/{file_id}",
            account=account,
            params={"addParents": folder_id, "removeParents": "root"},
        )
        return make_tool_response(
            {
                "status": "ok",
                "file_id": result.get("id", file_id),
                "moved_to": folder_id,
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_delete(
    file_id: str,
    account: str | None = None,
) -> dict[str, Any]:
    """Move a file to trash. CONFIRM-GATED.

    Args:
        file_id: File to trash.
        account: Google account name.

    Returns:
        Tool response confirming the trash.
    """
    try:
        client = _get_client()
        client.request(
            "PATCH",
            f"/drive/v3/files/{file_id}",
            account=account,
            json={"trashed": True},
        )
        return make_tool_response(
            {
                "status": "ok",
                "file_id": file_id,
                "trashed": True,
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_permanent_delete(
    file_id: str,
    account: str | None = None,
) -> dict[str, Any]:
    """Permanently delete a file. CONFIRM-GATED.

    Args:
        file_id: File to permanently delete.
        account: Google account name.

    Returns:
        Tool response confirming the deletion.
    """
    try:
        client = _get_client()
        token = client._get_token(account)
        url = f"{client._base_url}/drive/v3/files/{file_id}" if client._base_url else f"/drive/v3/files/{file_id}"
        resp = http_requests.delete(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return make_tool_response(
            {
                "status": "ok",
                "file_id": file_id,
                "permanently_deleted": True,
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_share(
    file_id: str,
    email: str,
    role: str = "reader",
    account: str | None = None,
) -> dict[str, Any]:
    """Share a file with a user. CONFIRM-GATED.

    Args:
        file_id: File to share.
        email: Email of the user to share with.
        role: Permission role ("reader", "writer", "commenter").
        account: Google account name.

    Returns:
        Tool response confirming the share.
    """
    try:
        client = _get_client()
        result = client.request(
            "POST",
            f"/drive/v3/files/{file_id}/permissions",
            account=account,
            json={"type": "user", "role": role, "emailAddress": email},
        )
        return make_tool_response(
            {
                "status": "ok",
                "file_id": file_id,
                "shared_with": email,
                "role": result.get("role", role),
                "permission_id": result.get("id"),
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")


def drive_cleanup(
    account: str | None = None,
    older_than: int | None = None,
    query: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Find and trash old files matching criteria. CONFIRM-GATED (unless dry_run).

    Args:
        account: Google account name.
        older_than: Trash files older than this many days.
        query: Additional Drive query filter.
        dry_run: If True, only list matching files without trashing.

    Returns:
        Tool response with matched files and action taken.
    """
    try:
        client = _get_client()

        q_parts: list[str] = []
        if older_than is not None:
            cutoff = datetime.now(tz=UTC) - timedelta(days=older_than)
            q_parts.append(f"modifiedTime < '{cutoff.strftime('%Y-%m-%dT%H:%M:%S')}'")
        if query:
            q_parts.append(query)

        params: dict[str, Any] = {"pageSize": 100}
        if q_parts:
            params["q"] = " and ".join(q_parts)

        data = client.request("GET", "/drive/v3/files", account=account, params=params)
        files = data.get("files", [])

        if dry_run:
            return make_tool_response(
                {
                    "status": "dry_run",
                    "matched_count": len(files),
                    "files": [{"id": f["id"], "name": f["name"], "modifiedTime": f.get("modifiedTime")} for f in files],
                }
            )

        trashed_ids: list[str] = []
        for f in files:
            client.request(
                "PATCH",
                f"/drive/v3/files/{f['id']}",
                account=account,
                json={"trashed": True},
            )
            trashed_ids.append(f["id"])

        return make_tool_response(
            {
                "status": "ok",
                "trashed_count": len(trashed_ids),
                "trashed_ids": trashed_ids,
            }
        )
    except http_requests.exceptions.ConnectionError:
        return make_error_response("Google Drive API is unreachable.")
    except http_requests.exceptions.HTTPError as e:
        return make_error_response(f"Drive API error: {e.response.status_code} {e.response.text}")
