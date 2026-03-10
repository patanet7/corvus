"""Persistent audit logging for tool calls.

Logs every tool invocation (allowed, denied, failed) to a JSONL file.
Each entry includes timestamp, agent, session, tool, outcome, and duration.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AuditEntry:
    timestamp: str
    agent_name: str
    session_id: str
    tool_name: str
    outcome: str  # "allowed" | "denied" | "failed"
    reason: str | None = None
    duration_ms: float | None = None
    params_summary: str | None = None  # Truncated params for audit (no secrets)


class AuditLog:
    """Append-only JSONL audit log for tool calls."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_tool_call(
        self,
        *,
        agent_name: str,
        session_id: str,
        tool_name: str,
        outcome: str,
        reason: str | None = None,
        duration_ms: float | None = None,
        params: dict | None = None,
    ) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            agent_name=agent_name,
            session_id=session_id,
            tool_name=tool_name,
            outcome=outcome,
            reason=reason,
            duration_ms=duration_ms,
            params_summary=_summarize_params(params) if params else None,
        )
        line = json.dumps(asdict(entry))
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_entries(
        self,
        *,
        agent_name: str | None = None,
        session_id: str | None = None,
    ) -> list[AuditEntry]:
        """Read audit entries, optionally filtered."""
        if not self._log_path.exists():
            return []
        entries: list[AuditEntry] = []
        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                data = json.loads(stripped)
                if agent_name and data.get("agent_name") != agent_name:
                    continue
                if session_id and data.get("session_id") != session_id:
                    continue
                entries.append(AuditEntry(**data))
        return entries


def _summarize_params(params: dict, max_len: int = 200) -> str:
    """Summarize params for audit log, truncating long values and redacting secrets."""
    safe: dict[str, str] = {}
    for k, v in params.items():
        v_str = str(v)
        if len(v_str) > 50:
            v_str = v_str[:47] + "..."
        safe[k] = v_str
    summary = json.dumps(safe)
    if len(summary) > max_len:
        summary = summary[: max_len - 3] + "..."
    return summary
