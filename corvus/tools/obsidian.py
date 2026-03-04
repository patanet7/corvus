"""Obsidian vault tools — direct functions for note management.

Tools:
    obsidian_search — Search vault notes by query
    obsidian_read   — Read a note (content + frontmatter)
    obsidian_write  — Create or overwrite a note
    obsidian_append — Append content to a note

Configuration:
    Call configure(base_url, api_key) before using any tool.

All outputs are sanitized via claw.sanitize.sanitize() to prevent
credential leakage. All paths are validated via sanitize_path() to
block traversal attacks.
"""

from typing import Any
from urllib.parse import quote

import requests

from corvus.sanitize import sanitize, sanitize_path
from corvus.tools.response import make_error_response, make_tool_response

# Module-level configuration set via configure()
_base_url: str | None = None
_api_key: str | None = None
_allowed_prefixes: list[str] | None = None


def configure(
    base_url: str,
    api_key: str,
    allowed_prefixes: list[str] | None = None,
) -> None:
    """Set the Obsidian Local REST API base URL and authentication token.

    Args:
        base_url: Base URL (e.g., "http://127.0.0.1:27124").
        api_key: Bearer token for the Obsidian REST API.
        allowed_prefixes: If set, only paths starting with one of these
            prefixes are permitted. None means unrestricted (default).
    """
    global _base_url, _api_key, _allowed_prefixes  # noqa: PLW0603
    _base_url = base_url.rstrip("/")
    _api_key = api_key
    _allowed_prefixes = allowed_prefixes


def _get_config() -> tuple[str, str]:
    """Return (base_url, api_key) or raise if not configured."""
    if _base_url is None or _api_key is None:
        raise RuntimeError("Obsidian tools not configured. Call gateway.tools.obsidian.configure(url, token) first.")
    return _base_url, _api_key


def _check_path_allowed(path: str) -> str | None:
    """Check if path is within allowed prefixes. Returns error message or None."""
    if _allowed_prefixes is None:
        return None
    for prefix in _allowed_prefixes:
        if path.startswith(prefix):
            return None
    return f"Path '{path}' is not allowed. Permitted prefixes: {_allowed_prefixes}"


def _obsidian_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    data: str | None = None,
    content_type: str | None = None,
    accept: str | None = None,
) -> requests.Response:
    """Make an authenticated request to the Obsidian Local REST API.

    Args:
        method: HTTP method.
        path: URL path (appended to base_url).
        params: Query parameters.
        data: Request body as string.
        content_type: Content-Type header value.
        accept: Accept header value.

    Returns:
        Raw Response object for callers to inspect status/body.
    """
    url, token = _get_config()
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept

    return requests.request(
        method,
        f"{url}{path}",
        headers=headers,
        params=params,
        data=data.encode("utf-8") if data else None,
        timeout=10,
        verify=False,
    )


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def obsidian_search(query: str, context_length: int = 100) -> dict[str, Any]:
    """Search vault notes by query string.

    Args:
        query: Search query text. Must not be empty.
        context_length: Characters of context around each match.

    Returns:
        Tool response with results array (filename, score, matches).
    """
    if not query or not query.strip():
        return make_error_response("query must not be empty")

    try:
        _get_config()
    except RuntimeError as exc:
        return make_error_response(str(exc))

    try:
        encoded_query = quote(query, safe="")
        resp = _obsidian_request(
            "POST",
            f"/search/simple/?query={encoded_query}&contextLength={context_length}",
        )

        if resp.status_code == 401:
            return make_error_response("Unauthorized: invalid API key")

        resp.raise_for_status()

        raw_results: list[dict[str, Any]] = resp.json()

        # Sanitize match context strings to prevent credential leakage
        sanitized_results: list[dict[str, Any]] = []
        for item in raw_results:
            sanitized_matches = []
            for match in item.get("matches", []):
                sanitized_matches.append(
                    {
                        "context": sanitize(match.get("context", "")),
                        "match": match.get("match", {}),
                    }
                )
            sanitized_results.append(
                {
                    "filename": item["filename"],
                    "score": item.get("score", 0),
                    "matches": sanitized_matches,
                }
            )

        # Filter results by allowed prefixes
        if _allowed_prefixes is not None:
            sanitized_results = [
                r for r in sanitized_results if any(r["filename"].startswith(p) for p in _allowed_prefixes)
            ]

        return make_tool_response({"results": sanitized_results})
    except requests.exceptions.ConnectionError:
        return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
    except requests.exceptions.HTTPError as exc:
        return make_error_response(f"Obsidian API error: {exc.response.status_code}")


def obsidian_read(path: str) -> dict[str, Any]:
    """Read a note from the vault (content + frontmatter + metadata).

    Args:
        path: Relative vault path (e.g., "journal/2026-02-27.md").

    Returns:
        Tool response with content, frontmatter, path, stat, and tags.
    """
    try:
        clean_path = sanitize_path(path)
    except ValueError as exc:
        return make_error_response(f"Invalid path: {exc}")

    prefix_error = _check_path_allowed(clean_path)
    if prefix_error:
        return make_error_response(prefix_error)

    try:
        _get_config()
    except RuntimeError as exc:
        return make_error_response(str(exc))

    try:
        encoded_path = quote(clean_path, safe="/")
        resp = _obsidian_request(
            "GET",
            f"/vault/{encoded_path}",
            accept="application/vnd.olrapi.note+json",
        )

        if resp.status_code == 401:
            return make_error_response("Unauthorized: invalid API key")

        if resp.status_code == 404:
            return make_error_response(f"Note not found: {clean_path}")

        resp.raise_for_status()
        note_data: dict[str, Any] = resp.json()

        # Sanitize content to prevent credential leakage
        note_data["content"] = sanitize(note_data.get("content", ""))

        return make_tool_response(note_data)
    except requests.exceptions.ConnectionError:
        return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
    except requests.exceptions.HTTPError as exc:
        return make_error_response(f"Obsidian API error: {exc.response.status_code}")


def obsidian_write(path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a note in the vault.

    Checks whether the note already exists to report "created" vs "updated".

    Args:
        path: Relative vault path (e.g., "notes/new-note.md").
        content: Full markdown content to write. Must not be empty.

    Returns:
        Tool response with status ("created" or "updated") and path.
    """
    try:
        clean_path = sanitize_path(path)
    except ValueError as exc:
        return make_error_response(f"Invalid path: {exc}")

    prefix_error = _check_path_allowed(clean_path)
    if prefix_error:
        return make_error_response(prefix_error)

    if not content:
        return make_error_response("content must not be empty")

    try:
        _get_config()
    except RuntimeError as exc:
        return make_error_response(str(exc))

    try:
        encoded_path = quote(clean_path, safe="/")

        # Check existence to determine create vs update
        check_resp = _obsidian_request("GET", f"/vault/{encoded_path}")

        if check_resp.status_code == 401:
            return make_error_response("Unauthorized: invalid API key")

        exists = check_resp.status_code == 200

        resp = _obsidian_request(
            "PUT",
            f"/vault/{encoded_path}",
            content_type="text/markdown",
            data=content,
        )
        resp.raise_for_status()

        status = "updated" if exists else "created"
        return make_tool_response({"status": status, "path": clean_path})
    except requests.exceptions.ConnectionError:
        return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
    except requests.exceptions.HTTPError as exc:
        return make_error_response(f"Obsidian API error: {exc.response.status_code}")


def obsidian_append(path: str, content: str) -> dict[str, Any]:
    """Append content to an existing note (or create if it doesn't exist).

    Args:
        path: Relative vault path (e.g., "journal/2026-02-27.md").
        content: Markdown content to append. Must not be empty.

    Returns:
        Tool response with status and path.
    """
    try:
        clean_path = sanitize_path(path)
    except ValueError as exc:
        return make_error_response(f"Invalid path: {exc}")

    prefix_error = _check_path_allowed(clean_path)
    if prefix_error:
        return make_error_response(prefix_error)

    if not content:
        return make_error_response("content must not be empty")

    try:
        _get_config()
    except RuntimeError as exc:
        return make_error_response(str(exc))

    try:
        encoded_path = quote(clean_path, safe="/")
        resp = _obsidian_request(
            "POST",
            f"/vault/{encoded_path}",
            content_type="text/markdown",
            data=content,
        )

        if resp.status_code == 401:
            return make_error_response("Unauthorized: invalid API key")

        resp.raise_for_status()

        return make_tool_response({"status": "ok", "path": clean_path})
    except requests.exceptions.ConnectionError:
        return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
    except requests.exceptions.HTTPError as exc:
        return make_error_response(f"Obsidian API error: {exc.response.status_code}")


# ---------------------------------------------------------------------------
# Instance-based client for per-agent MCP servers
# ---------------------------------------------------------------------------


class ObsidianClient:
    """Instance-based Obsidian client with per-instance config.

    Use this for per-agent MCP servers where each agent needs
    different allowed_prefixes. Methods are named obsidian_* so
    create_sdk_mcp_server derives correct tool names.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        allowed_prefixes: list[str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._allowed_prefixes = allowed_prefixes

    @property
    def allowed_prefixes(self) -> list[str] | None:
        """Read-only access to allowed prefixes for testing."""
        return self._allowed_prefixes

    def _check_path_allowed(self, path: str) -> str | None:
        """Check if path is within allowed prefixes. Returns error message or None."""
        if self._allowed_prefixes is None:
            return None
        for prefix in self._allowed_prefixes:
            if path.startswith(prefix):
                return None
        return f"Path '{path}' is not allowed. Permitted prefixes: {self._allowed_prefixes}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: str | None = None,
        content_type: str | None = None,
        accept: str | None = None,
    ) -> requests.Response:
        """Make authenticated request using this instance's config."""
        headers: dict[str, str] = {"Authorization": f"Bearer {self._api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        if accept:
            headers["Accept"] = accept
        return requests.request(
            method,
            f"{self._base_url}{path}",
            headers=headers,
            params=params,
            data=data.encode("utf-8") if data else None,
            timeout=10,
            verify=False,
        )

    def obsidian_search(self, query: str, context_length: int = 100) -> dict[str, Any]:
        """Search vault notes — instance-based version."""
        if not query or not query.strip():
            return make_error_response("query must not be empty")
        try:
            encoded_query = quote(query, safe="")
            resp = self._request(
                "POST",
                f"/search/simple/?query={encoded_query}&contextLength={context_length}",
            )
            if resp.status_code == 401:
                return make_error_response("Unauthorized: invalid API key")
            resp.raise_for_status()
            raw_results: list[dict[str, Any]] = resp.json()
            sanitized_results: list[dict[str, Any]] = []
            for item in raw_results:
                sanitized_matches = []
                for match in item.get("matches", []):
                    sanitized_matches.append(
                        {
                            "context": sanitize(match.get("context", "")),
                            "match": match.get("match", {}),
                        }
                    )
                sanitized_results.append(
                    {
                        "filename": item["filename"],
                        "score": item.get("score", 0),
                        "matches": sanitized_matches,
                    }
                )
            if self._allowed_prefixes is not None:
                sanitized_results = [
                    r for r in sanitized_results if any(r["filename"].startswith(p) for p in self._allowed_prefixes)
                ]
            return make_tool_response({"results": sanitized_results})
        except requests.exceptions.ConnectionError:
            return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
        except requests.exceptions.HTTPError as exc:
            return make_error_response(f"Obsidian API error: {exc.response.status_code}")

    def obsidian_read(self, path: str) -> dict[str, Any]:
        """Read a vault note — instance-based version."""
        try:
            clean_path = sanitize_path(path)
        except ValueError as exc:
            return make_error_response(f"Invalid path: {exc}")
        prefix_error = self._check_path_allowed(clean_path)
        if prefix_error:
            return make_error_response(prefix_error)
        try:
            encoded_path = quote(clean_path, safe="/")
            resp = self._request(
                "GET",
                f"/vault/{encoded_path}",
                accept="application/vnd.olrapi.note+json",
            )
            if resp.status_code == 401:
                return make_error_response("Unauthorized: invalid API key")
            if resp.status_code == 404:
                return make_error_response(f"Note not found: {clean_path}")
            resp.raise_for_status()
            note_data: dict[str, Any] = resp.json()
            note_data["content"] = sanitize(note_data.get("content", ""))
            return make_tool_response(note_data)
        except requests.exceptions.ConnectionError:
            return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
        except requests.exceptions.HTTPError as exc:
            return make_error_response(f"Obsidian API error: {exc.response.status_code}")

    def obsidian_write(self, path: str, content: str) -> dict[str, Any]:
        """Write a vault note — instance-based version."""
        try:
            clean_path = sanitize_path(path)
        except ValueError as exc:
            return make_error_response(f"Invalid path: {exc}")
        if not content:
            return make_error_response("content must not be empty")
        prefix_error = self._check_path_allowed(clean_path)
        if prefix_error:
            return make_error_response(prefix_error)
        try:
            encoded_path = quote(clean_path, safe="/")
            check_resp = self._request("GET", f"/vault/{encoded_path}")
            if check_resp.status_code == 401:
                return make_error_response("Unauthorized: invalid API key")
            exists = check_resp.status_code == 200
            resp = self._request(
                "PUT",
                f"/vault/{encoded_path}",
                content_type="text/markdown",
                data=content,
            )
            resp.raise_for_status()
            status = "updated" if exists else "created"
            return make_tool_response({"status": status, "path": clean_path})
        except requests.exceptions.ConnectionError:
            return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
        except requests.exceptions.HTTPError as exc:
            return make_error_response(f"Obsidian API error: {exc.response.status_code}")

    def obsidian_append(self, path: str, content: str) -> dict[str, Any]:
        """Append to a vault note — instance-based version."""
        try:
            clean_path = sanitize_path(path)
        except ValueError as exc:
            return make_error_response(f"Invalid path: {exc}")
        if not content:
            return make_error_response("content must not be empty")
        prefix_error = self._check_path_allowed(clean_path)
        if prefix_error:
            return make_error_response(prefix_error)
        try:
            encoded_path = quote(clean_path, safe="/")
            resp = self._request(
                "POST",
                f"/vault/{encoded_path}",
                content_type="text/markdown",
                data=content,
            )
            if resp.status_code == 401:
                return make_error_response("Unauthorized: invalid API key")
            resp.raise_for_status()
            return make_tool_response({"status": "ok", "path": clean_path})
        except requests.exceptions.ConnectionError:
            return make_error_response("Obsidian REST API is unreachable. Is the plugin running?")
        except requests.exceptions.HTTPError as exc:
            return make_error_response(f"Obsidian API error: {exc.response.status_code}")
