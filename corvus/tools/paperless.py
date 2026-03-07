"""Paperless-ngx tools — direct functions for document management.

Tools:
    paperless_search    — Search documents by query with optional tag filter
    paperless_read      — Read single document by ID
    paperless_tags      — List all tags
    paperless_tag       — Add tag to document (CONFIRM-GATED)
    paperless_bulk_edit — Batch tag/correspondent changes (CONFIRM-GATED)

Configuration:
    Call configure(paperless_url, paperless_token) before using any tool.

All outputs are sanitized via corvus.sanitize.sanitize() to prevent
credential leakage.
"""

from typing import Any

import requests

from corvus.tools.response import make_error_response, make_tool_response

# Module-level configuration set via configure()
_paperless_url: str | None = None
_paperless_token: str | None = None


def configure(paperless_url: str, paperless_token: str) -> None:
    """Set the Paperless-ngx API base URL and authentication token.

    Args:
        paperless_url: Paperless-ngx base URL (e.g., "http://paperless-host:8010").
        paperless_token: API token for the Paperless-ngx REST API.
    """
    global _paperless_url, _paperless_token  # noqa: PLW0603
    _paperless_url = paperless_url.rstrip("/")
    _paperless_token = paperless_token


def _get_config() -> tuple[str, str]:
    """Return (url, token) or raise if not configured."""
    if _paperless_url is None or _paperless_token is None:
        raise RuntimeError("Paperless tools not configured. Call corvus.tools.paperless.configure(url, token) first.")
    return _paperless_url, _paperless_token


def _paperless_request(
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict | list:
    """Make an authenticated request to the Paperless-ngx REST API.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: URL path (appended to base URL).
        params: Query parameters.
        data: JSON body for POST/PATCH requests.

    Returns:
        Parsed JSON response.
    """
    url, token = _get_config()
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json; version=2",
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


def _format_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Format a Paperless document dict into a clean summary."""
    item: dict[str, Any] = {
        "id": doc["id"],
        "title": doc["title"],
        "created": doc.get("created", ""),
        "tags": doc.get("tags", []),
        "correspondent": doc.get("correspondent"),
        "document_type": doc.get("document_type"),
    }
    # Include search hit metadata if available
    search_hit = doc.get("__search_hit__")
    if search_hit:
        item["score"] = search_hit.get("score")
        item["highlights"] = search_hit.get("highlights", "")
    # Include content snippet if present
    if doc.get("content"):
        item["content_snippet"] = doc["content"][:500]
    return item


def _resolve_tag_id(tag_name: str) -> int | None:
    """Resolve a tag name to its integer ID. Returns None if not found."""
    resp = _paperless_request("GET", "/api/tags/", params={"page_size": "1000"})
    results = resp.get("results", []) if isinstance(resp, dict) else []
    for tag in results:
        if tag["name"].lower() == tag_name.lower():
            return int(tag["id"])
    return None


# ---------------------------------------------------------------------------
# Tool functions — sync, keyword arguments (matches ha.py / drive.py pattern)
# ---------------------------------------------------------------------------


def paperless_search(
    query: str,
    tag: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search documents by query with optional tag filter.

    Args:
        query: Search query string.
        tag: Optional tag name to filter by.
        limit: Max results (default 10).

    Returns:
        Tool response with count and documents array.
    """
    if not query or not query.strip():
        return make_error_response("query must not be empty")

    try:
        params: dict[str, str] = {
            "query": query,
            "page_size": str(limit),
        }
        if tag:
            tag_id = _resolve_tag_id(tag)
            if tag_id is None:
                return make_error_response(f"Tag not found: {tag}")
            params["tags__id__in"] = str(tag_id)

        resp = _paperless_request("GET", "/api/documents/", params=params)
        results = resp.get("results", []) if isinstance(resp, dict) else []
        documents = [_format_document(doc) for doc in results]
        return make_tool_response({"count": len(documents), "documents": documents})
    except requests.exceptions.ConnectionError:
        return make_error_response("Paperless-ngx is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Paperless API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def paperless_read(id: int) -> dict[str, Any]:
    """Read a single document by ID.

    Args:
        id: Document ID.

    Returns:
        Tool response with full document metadata and content.
    """
    try:
        resp = _paperless_request("GET", f"/api/documents/{id}/")
        if not isinstance(resp, dict):
            return make_error_response("Unexpected response format")

        output = {
            "id": resp["id"],
            "title": resp["title"],
            "content": resp.get("content", ""),
            "created": resp.get("created", ""),
            "modified": resp.get("modified", ""),
            "added": resp.get("added", ""),
            "tags": resp.get("tags", []),
            "correspondent": resp.get("correspondent"),
            "document_type": resp.get("document_type"),
            "archive_serial_number": resp.get("archive_serial_number"),
            "original_file_name": resp.get("original_file_name", ""),
        }
        return make_tool_response(output)
    except requests.exceptions.ConnectionError:
        return make_error_response("Paperless-ngx is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Paperless API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def paperless_tags() -> dict[str, Any]:
    """List all tags.

    Returns:
        Tool response with tags array.
    """
    try:
        resp = _paperless_request("GET", "/api/tags/", params={"page_size": "1000"})
        results = resp.get("results", []) if isinstance(resp, dict) else []
        tags = [
            {
                "id": tag["id"],
                "name": tag["name"],
                "color": tag.get("colour", tag.get("color", "")),
                "document_count": tag.get("document_count", 0),
            }
            for tag in results
        ]
        return make_tool_response({"tags": tags})
    except requests.exceptions.ConnectionError:
        return make_error_response("Paperless-ngx is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Paperless API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def paperless_tag(id: int, tag: str) -> dict[str, Any]:
    """Add a tag to a document. CONFIRM-GATED.

    Args:
        id: Document ID.
        tag: Tag name to add.

    Returns:
        Tool response confirming the tag was applied.
    """
    try:
        tag_id = _resolve_tag_id(tag)
        if tag_id is None:
            return make_error_response(f"Tag not found: {tag}")

        body = {
            "documents": [id],
            "method": "add_tag",
            "parameters": {"tag": tag_id},
        }
        _paperless_request("POST", "/api/documents/bulk_edit/", data=body)

        return make_tool_response(
            {
                "status": "tagged",
                "document_id": id,
                "tag_name": tag,
                "tag_id": tag_id,
            }
        )
    except requests.exceptions.ConnectionError:
        return make_error_response("Paperless-ngx is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Paperless API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))


def paperless_bulk_edit(
    documents: list[int],
    method: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Batch tag/correspondent changes on multiple documents. CONFIRM-GATED.

    Args:
        documents: List of document IDs.
        method: Bulk edit method (e.g., "add_tag", "remove_tag",
                "set_correspondent", "set_document_type").
        parameters: Method-specific parameters.
            For add_tag/remove_tag: {"tag": <tag_id>}
            For set_correspondent: {"correspondent": <id>}
            For set_document_type: {"document_type": <id>}

    Returns:
        Tool response confirming the bulk edit.
    """
    if not documents:
        return make_error_response("documents must be a non-empty list of IDs")

    try:
        body = {
            "documents": documents,
            "method": method,
            "parameters": parameters,
        }
        _paperless_request("POST", "/api/documents/bulk_edit/", data=body)

        return make_tool_response(
            {
                "status": "ok",
                "method": method,
                "document_count": len(documents),
                "documents": documents,
            }
        )
    except requests.exceptions.ConnectionError:
        return make_error_response("Paperless-ngx is unreachable. Check if the server is online.")
    except requests.exceptions.HTTPError as e:
        return make_error_response(f"Paperless API error: {e.response.status_code} {e.response.reason}")
    except RuntimeError as e:
        return make_error_response(str(e))
