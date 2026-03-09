"""Session lifecycle management — summary building from audit trail.

Builds structured session summaries from hook-captured audit data.
No LLM call needed — summaries are deterministic from audit entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from corvus.security.audit import AuditEntry


@dataclass
class ToolCallSummary:
    tool_name: str
    call_count: int
    success_count: int
    denied_count: int
    failed_count: int


@dataclass
class SessionSummary:
    agent_name: str
    session_id: str
    started_at: str
    ended_at: str
    tools_used: list[ToolCallSummary]
    total_calls: int
    total_denied: int
    total_failed: int
    mutations: list[str]  # tool names that mutated state
    outcome: str  # "success" | "partial" | "failed"


def build_session_summary(
    *,
    agent_name: str,
    session_id: str,
    started_at: datetime,
    ended_at: datetime,
    audit_entries: list[AuditEntry],
    mutation_tools: set[str] | None = None,
) -> SessionSummary:
    """Build a SessionSummary from audit entries.

    Args:
        agent_name: Name of the agent
        session_id: Session identifier
        started_at: Session start time
        ended_at: Session end time
        audit_entries: Filtered audit entries for this session
        mutation_tools: Set of tool names that are mutations (for tracking)
    """
    mutation_tools = mutation_tools or set()

    # Aggregate per-tool stats
    tool_stats: dict[str, dict[str, int]] = {}
    mutations_performed: list[str] = []

    for entry in audit_entries:
        if entry.tool_name not in tool_stats:
            tool_stats[entry.tool_name] = {
                "total": 0,
                "allowed": 0,
                "denied": 0,
                "failed": 0,
            }
        stats = tool_stats[entry.tool_name]
        stats["total"] += 1
        if entry.outcome == "allowed":
            stats["allowed"] += 1
            if (
                entry.tool_name in mutation_tools
                and entry.tool_name not in mutations_performed
            ):
                mutations_performed.append(entry.tool_name)
        elif entry.outcome == "denied":
            stats["denied"] += 1
        elif entry.outcome == "failed":
            stats["failed"] += 1

    tools_used = [
        ToolCallSummary(
            tool_name=name,
            call_count=s["total"],
            success_count=s["allowed"],
            denied_count=s["denied"],
            failed_count=s["failed"],
        )
        for name, s in sorted(tool_stats.items())
    ]

    total_calls = sum(s["total"] for s in tool_stats.values())
    total_denied = sum(s["denied"] for s in tool_stats.values())
    total_failed = sum(s["failed"] for s in tool_stats.values())
    total_success = sum(s["allowed"] for s in tool_stats.values())

    # Determine outcome
    if total_calls == 0:
        outcome = "success"  # No tool calls = pure conversation
    elif total_failed > total_success:
        outcome = "failed"
    elif total_failed > 0 or total_denied > 0:
        outcome = "partial"
    else:
        outcome = "success"

    return SessionSummary(
        agent_name=agent_name,
        session_id=session_id,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        tools_used=tools_used,
        total_calls=total_calls,
        total_denied=total_denied,
        total_failed=total_failed,
        mutations=mutations_performed,
        outcome=outcome,
    )
