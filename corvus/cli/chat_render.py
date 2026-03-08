"""ANSI terminal formatting for corvus chat CLI."""

from __future__ import annotations

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"

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


def render_welcome(agents: list[tuple[str, str]]) -> str:
    """Render welcome screen with available agents."""
    lines = [
        f"\n  {_BOLD}Corvus Chat{_RESET}",
        f"  {_DIM}Select an agent to launch{_RESET}\n",
        f"  {_BOLD}Available agents:{_RESET}",
    ]
    for name, desc in agents:
        color = _agent_color(name)
        lines.append(f"    {color}{name:12s}{_RESET} {_DIM}{desc[:60]}{_RESET}")
    lines.append("")
    return "\n".join(lines)
