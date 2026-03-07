"""ANSI terminal formatting for corvus chat CLI."""

from __future__ import annotations

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"

_AGENT_COLORS = {
    "homelab": "\033[36m",
    "finance": "\033[32m",
    "personal": "\033[35m",
    "work": "\033[34m",
    "email": "\033[33m",
    "docs": "\033[37m",
    "music": "\033[35m",
    "home": "\033[36m",
    "huginn": "\033[31m",
    "general": "\033[37m",
}


def _agent_color(agent: str) -> str:
    return _AGENT_COLORS.get(agent, _CYAN)


def format_agent_name(agent: str) -> str:
    """Format agent name with color for terminal display."""
    color = _agent_color(agent)
    return f"{color}{_BOLD}@{agent}{_RESET}"


def format_tool_call(tool_name: str, tool_input: dict) -> str:
    """Format a tool call for inline display."""
    summary = ""
    if "command" in tool_input:
        summary = str(tool_input["command"])[:120]
    elif "file_path" in tool_input:
        summary = str(tool_input["file_path"])
    elif "pattern" in tool_input:
        summary = str(tool_input["pattern"])
    else:
        keys = list(tool_input.keys())[:3]
        summary = ", ".join(f"{k}=..." for k in keys)
    return f"  {_DIM}[tool:{tool_name}]{_RESET} {summary}"


def format_memory_event(action: str, domain: str, content: str) -> str:
    """Format a memory save/recall event."""
    icon = "+" if action == "save" else "?"
    return f"  {_GREEN}[memory:{icon}]{_RESET} {_DIM}{domain}{_RESET} -- {content[:200]}"


def format_info_line(label: str, value: str) -> str:
    """Format a key-value info line."""
    return f"  {_BOLD}{label}:{_RESET} {value}"


def format_confirm_prompt(tool_name: str, tool_input: dict) -> str:
    """Format a confirm-gated tool prompt."""
    lines = [
        f"\n  {_YELLOW}{_BOLD}! {tool_name}{_RESET}",
    ]
    for k, v in tool_input.items():
        lines.append(f"    {_DIM}{k}:{_RESET} {str(v)[:200]}")
    lines.append(f"\n  {_DIM}[y] approve  [n] deny  [c] converse  [+note] add note:{_RESET} ")
    return "\n".join(lines)


def render_welcome(agents: list[tuple[str, str]]) -> str:
    """Render welcome screen with available agents."""
    lines = [
        f"\n  {_BOLD}Corvus Chat{_RESET}",
        f"  {_DIM}Interactive agent REPL — type /help for commands{_RESET}\n",
        f"  {_BOLD}Available agents:{_RESET}",
    ]
    for name, desc in agents:
        color = _agent_color(name)
        lines.append(f"    {color}{name:12s}{_RESET} {_DIM}{desc[:60]}{_RESET}")
    lines.append("")
    return "\n".join(lines)


def render_info(
    agent: str,
    model: str,
    backend: str,
    session_id: str,
    memory_domain: str | None = None,
) -> str:
    """Render /info output."""
    lines = [
        f"\n  {_BOLD}Session Info{_RESET}",
        format_info_line("Agent", format_agent_name(agent)),
        format_info_line("Model", model),
        format_info_line("Backend", backend),
        format_info_line("Session", session_id),
    ]
    if memory_domain:
        lines.append(format_info_line("Memory Domain", memory_domain))
    lines.append("")
    return "\n".join(lines)
