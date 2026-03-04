"""Shared tool response helpers.

Every tool module returns results in the same envelope:

    {"content": [{"type": "text", "text": "<sanitized JSON>"}]}

These two functions build that envelope for success and error cases.
"""

import json
from typing import Any

from corvus.sanitize import sanitize


def make_tool_response(data: Any) -> dict[str, Any]:
    """Wrap data in the standard tool response format."""
    return {"content": [{"type": "text", "text": sanitize(json.dumps(data))}]}


def make_error_response(error_msg: str) -> dict[str, Any]:
    """Wrap an error message in the standard tool response format."""
    return {"content": [{"type": "text", "text": sanitize(json.dumps({"error": error_msg}))}]}
