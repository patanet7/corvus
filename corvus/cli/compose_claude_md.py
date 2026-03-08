"""Compose CLAUDE.md content for agent workspaces.

Generates the project-level CLAUDE.md that Claude Code loads natively.
Contains: domain instructions (layer 3), sibling agents (layer 4),
and memory context (layer 5).
"""

from __future__ import annotations

from pathlib import Path


def compose_claude_md(
    *,
    spec: object,
    config_dir: Path,
    siblings: list[tuple[str, str]],
    memory_lines: list[str],
    memory_domain: str,
) -> str:
    """Compose CLAUDE.md content for an agent workspace.

    Args:
        spec: AgentSpec object with .name, .prompt() method.
        config_dir: Config directory for resolving prompt files.
        siblings: List of (name, description) tuples for other agents.
        memory_lines: Pre-formatted memory seed lines.
        memory_domain: The agent's memory domain name.

    Returns:
        Full CLAUDE.md content as a string.
    """
    sections: list[str] = []

    # Section 1: Agent prompt (domain instructions)
    try:
        prompt_content = spec.prompt(config_dir=config_dir)  # type: ignore[attr-defined]
        if prompt_content:
            sections.append(f"# {spec.name.title()} Agent\n\n{prompt_content}")  # type: ignore[attr-defined]
    except (FileNotFoundError, AttributeError):
        sections.append(f"# {spec.name.title()} Agent")  # type: ignore[attr-defined]

    # Section 2: Sibling agents
    if siblings:
        lines = ["# Other Agents\n"]
        lines.append(
            "If a question falls outside your domain, tell the user "
            "which of these agents can help:\n"
        )
        for name, description in siblings:
            lines.append(f"- **{name}**: {description.strip()}")
        sections.append("\n".join(lines))

    # Section 3: Memory context
    mem_lines = ["# Memory Context\n"]
    mem_lines.append(
        f"Your memory domain is **{memory_domain}**."
    )
    if memory_lines:
        mem_lines.append(
            "These are your most relevant recent and evergreen memories:\n"
        )
        mem_lines.extend(memory_lines)
    else:
        mem_lines.append("No memories seeded yet. Use memory tools to build context.")
    sections.append("\n".join(mem_lines))

    return "\n\n---\n\n".join(sections) + "\n"
