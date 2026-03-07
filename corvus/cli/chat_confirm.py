"""Terminal-native confirm flow for gated tools."""

from __future__ import annotations

from dataclasses import dataclass

from corvus.cli.chat_render import format_confirm_prompt


@dataclass
class ConfirmResponse:
    """Parsed confirm response."""

    action: str  # "allow", "deny", "converse", "note"
    note: str | None = None


def parse_confirm_response(raw: str) -> ConfirmResponse:
    """Parse user's response to a confirm prompt.

    Args:
        raw: The raw string input from the user.

    Returns:
        A ConfirmResponse with the parsed action and optional note.
    """
    text = raw.strip().lower()
    if text in ("y", "yes"):
        return ConfirmResponse(action="allow")
    if text in ("n", "no"):
        return ConfirmResponse(action="deny")
    if text in ("c", "converse"):
        return ConfirmResponse(action="converse")
    if text.startswith("+"):
        return ConfirmResponse(action="note", note=text[1:].strip())
    return ConfirmResponse(action="deny", note=f"Unrecognized input: {raw}")


def terminal_confirm(tool_name: str, tool_input: dict) -> ConfirmResponse:
    """Show confirm prompt in terminal and get user response.

    Args:
        tool_name: Name of the tool requesting confirmation.
        tool_input: Dictionary of tool input parameters to display.

    Returns:
        A ConfirmResponse based on user input.
    """
    print(format_confirm_prompt(tool_name, tool_input))
    try:
        raw = input("  > ")
    except (EOFError, KeyboardInterrupt):
        return ConfirmResponse(action="deny", note="User interrupted")
    return parse_confirm_response(raw)
