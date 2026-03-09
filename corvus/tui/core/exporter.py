"""Session export to markdown for the Corvus TUI.

Converts a list of session messages (dicts from SessionDetail.messages)
into a well-formatted markdown document suitable for archiving or sharing.
"""

import json
from datetime import date
from pathlib import Path


def default_export_path() -> Path:
    """Return the default export path: ~/corvus-export-YYYY-MM-DD.md."""
    today = date.today().isoformat()
    return Path.home() / f"corvus-export-{today}.md"


def export_session_to_markdown(messages: list[dict], path: Path) -> Path:
    """Export session messages to a markdown file.

    Args:
        messages: List of message dicts from SessionDetail.messages.
            Each dict may contain: role, content, agent, tool_name,
            tool_calls, parameters, timestamp.
        path: Destination file path for the markdown export.

    Returns:
        The path the file was written to.
    """
    lines: list[str] = []
    lines.append("# Corvus Session Export")
    lines.append("")

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        agent = msg.get("agent", "")
        timestamp = msg.get("timestamp", "")
        tool_name = msg.get("tool_name", "")
        tool_calls = msg.get("tool_calls", [])

        # Build the header line
        if role == "user":
            lines.append("## You")
        elif role == "assistant" and agent:
            lines.append(f"## @{agent}")
        elif role == "tool":
            lines.append(f"### Tool Result: {tool_name}")
        else:
            lines.append(f"## {role}")

        # Timestamp if present
        if timestamp:
            lines.append(f"*{timestamp}*")
            lines.append("")

        # Message content
        if content:
            lines.append(content)
            lines.append("")

        # Tool calls embedded in assistant messages
        if tool_calls:
            for tc in tool_calls:
                tc_name = tc.get("name", "unknown")
                tc_params = tc.get("parameters", {})
                lines.append(f"### Tool: {tc_name}")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(tc_params, indent=2, default=str))
                lines.append("```")
                lines.append("")

    # Write to disk
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
