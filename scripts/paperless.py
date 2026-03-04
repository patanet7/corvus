#!/usr/bin/env python3
"""Paperless-ngx CLI — called by the docs agent via Bash tool.

Usage:
    python paperless.py search "<query>" [--limit N] [--tag TAG]
    python paperless.py get <doc_id>
    python paperless.py tags
    python paperless.py tag <doc_id> <tag_name>
"""

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _base_url() -> str:
    """Return the Paperless-ngx base URL from environment."""
    url = os.environ.get("PAPERLESS_URL", "http://localhost:8010")
    return url.rstrip("/")


def _api_token() -> str:
    """Return the Paperless-ngx API token from environment."""
    token = os.environ.get("PAPERLESS_API_TOKEN", "")
    if not token:
        print(
            json.dumps({"error": "PAPERLESS_API_TOKEN not set"}),
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _api_request(
    path: str,
    *,
    method: str = "GET",
    params: dict[str, str] | None = None,
    body: dict | None = None,
) -> dict:
    """Make an authenticated request to the Paperless-ngx API."""
    base = _base_url()
    url = f"{base}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers = {
        "Authorization": f"Token {_api_token()}",
        "Accept": "application/json; version=2",
    }

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()

    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            if not raw:
                return {}
            result: dict[str, Any] = json.loads(raw)
            return result
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()
        except Exception:
            pass
        print(
            json.dumps(
                {
                    "error": f"HTTP {e.code}: {e.reason}",
                    "detail": error_body,
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    except URLError as e:
        print(
            json.dumps({"error": f"Connection failed: {e.reason}"}),
            file=sys.stderr,
        )
        sys.exit(1)


def _resolve_tag_id(tag_name: str, tags_list: list[dict] | None = None) -> int:
    """Resolve a tag name to its integer ID. Fetches all tags if not provided."""
    if tags_list is None:
        resp = _api_request("/api/tags/", params={"page_size": "1000"})
        tags_list = resp.get("results", [])

    for tag in tags_list:
        if tag["name"].lower() == tag_name.lower():
            return int(tag["id"])

    print(
        json.dumps({"error": f"Tag not found: {tag_name}"}),
        file=sys.stderr,
    )
    sys.exit(1)


def cmd_search(args: argparse.Namespace) -> None:
    """Search documents and print JSON array of results."""
    params: dict[str, str] = {
        "query": args.query,
        "page_size": str(args.limit),
    }
    if args.tag:
        # Resolve tag name to ID for filtering
        tag_id = _resolve_tag_id(args.tag)
        params["tags__id__in"] = str(tag_id)

    resp = _api_request("/api/documents/", params=params)
    results = resp.get("results", [])

    output = []
    for doc in results:
        item: dict = {
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
            item["content"] = doc["content"][:500]

        output.append(item)

    print(json.dumps(output, indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    """Get a single document's metadata and content."""
    resp = _api_request(f"/api/documents/{args.doc_id}/")

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
    print(json.dumps(output, indent=2))


def cmd_tags(args: argparse.Namespace) -> None:
    """List all tags and print as JSON array."""
    resp = _api_request("/api/tags/", params={"page_size": "1000"})
    results = resp.get("results", [])

    output = [
        {
            "id": tag["id"],
            "name": tag["name"],
            "color": tag.get("colour", tag.get("color", "")),
            "document_count": tag.get("document_count", 0),
        }
        for tag in results
    ]
    print(json.dumps(output, indent=2))


def cmd_tag(args: argparse.Namespace) -> None:
    """Add a tag to a document via bulk_edit endpoint."""
    tag_id = _resolve_tag_id(args.tag_name)

    body = {
        "documents": [args.doc_id],
        "method": "add_tag",
        "parameters": {"tag": tag_id},
    }
    _api_request("/api/documents/bulk_edit/", method="POST", body=body)

    print(
        json.dumps(
            {
                "status": "tagged",
                "document_id": args.doc_id,
                "tag_name": args.tag_name,
                "tag_id": tag_id,
            }
        )
    )


def main() -> None:
    """Parse arguments and dispatch to subcommand handler."""
    parser = argparse.ArgumentParser(description="Paperless-ngx CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search documents by query")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.add_argument("--tag", default=None, help="Filter by tag name")

    p_get = sub.add_parser("get", help="Get document metadata and content")
    p_get.add_argument("doc_id", type=int, help="Document ID")

    sub.add_parser("tags", help="List all tags")

    p_tag = sub.add_parser("tag", help="Add a tag to a document")
    p_tag.add_argument("doc_id", type=int, help="Document ID")
    p_tag.add_argument("tag_name", help="Tag name to add")

    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "tags":
        cmd_tags(args)
    elif args.command == "tag":
        cmd_tag(args)


if __name__ == "__main__":
    main()
