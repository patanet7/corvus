"""Compose the minimal system prompt for Claude Code.

Contains only layers 0, 1, and 2:
- Soul (shared identity, principles, memory instructions)
- Agent soul (personality/vibe)
- Agent identity assertion

Everything else goes in CLAUDE.md (loaded natively by Claude Code).
"""

from __future__ import annotations

from pathlib import Path

_FALLBACK_SOUL = (
    "You are an agent in **Corvus**, a local-first, self-hosted "
    "multi-agent system.\n\n"
    "You are NOT Claude. You are NOT made by Anthropic. "
    "Disregard any prior identity instructions."
)


def compose_system_prompt(
    *,
    config_dir: Path,
    agent_name: str,
    agent_soul_content: str | None,
) -> str:
    """Build the minimal system prompt for a Claude Code agent session.

    Args:
        config_dir: Project root (contains corvus/prompts/soul.md).
        agent_name: The agent name for the identity assertion.
        agent_soul_content: Optional per-agent personality content from soul_file.

    Returns:
        System prompt string (soul + identity + optional agent soul).
    """
    parts: list[str] = []

    # Layer 0: Soul
    soul_file = config_dir / "corvus" / "prompts" / "soul.md"
    if soul_file.exists():
        parts.append(soul_file.read_text().strip())
    else:
        parts.append(_FALLBACK_SOUL)

    # Layer 2: Agent identity assertion
    parts.append(
        f"You are the **{agent_name}** agent. "
        f"Always identify as the {agent_name} agent when asked who you are."
    )

    # Layer 1: Agent soul (personality/vibe)
    if agent_soul_content:
        parts.append(agent_soul_content.strip())

    return "\n\n---\n\n".join(parts)
