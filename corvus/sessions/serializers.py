"""Row serializers for session/dispatch/run persistence."""

from __future__ import annotations

import json
import sqlite3


def session_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sessions row to an API-safe dict."""
    agents_raw = row["agents_used"] or "[]"
    try:
        agents_list = json.loads(agents_raw)
    except (json.JSONDecodeError, TypeError):
        agents_list = [a for a in str(agents_raw).split(",") if a]
    return {
        "id": row["id"],
        "user": row["user"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "summary": row["summary"],
        "agent_name": row["agent_name"],
        "message_count": row["message_count"] or 0,
        "tool_count": row["tool_count"] or 0,
        "agents_used": agents_list,
    }


def dispatch_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a dispatch row to an API-safe dict."""
    targets_raw = row["target_agents"] or "[]"
    try:
        target_agents = json.loads(targets_raw)
    except (json.JSONDecodeError, TypeError):
        target_agents = []
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "user": row["user"],
        "prompt": row["prompt"],
        "dispatch_mode": row["dispatch_mode"],
        "target_agents": target_agents,
        "status": row["status"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def run_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert an agent run row to an API-safe dict."""
    return {
        "id": row["id"],
        "dispatch_id": row["dispatch_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "agent": row["agent"],
        "backend": row["backend"],
        "model": row["model"],
        "task_type": row["task_type"],
        "subtask_id": row["subtask_id"],
        "skill": row["skill"],
        "status": row["status"],
        "summary": row["summary"],
        "cost_usd": row["cost_usd"] or 0.0,
        "tokens_used": row["tokens_used"] or 0,
        "context_limit": row["context_limit"] or 0,
        "context_pct": row["context_pct"] or 0.0,
        "error": row["error"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def event_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert an event row (session or run scoped) to an API-safe dict."""
    payload_raw = row["payload"]
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, TypeError):
        payload = {"raw": str(payload_raw)}

    data = {
        "id": row["id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "event_type": row["event_type"],
        "payload": payload,
        "created_at": row["created_at"],
    }
    # run event rows include these columns
    if "run_id" in row.keys():
        data["run_id"] = row["run_id"]
    if "dispatch_id" in row.keys():
        data["dispatch_id"] = row["dispatch_id"]
    return data


def trace_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a trace event row to a hook-observability compatible dict."""
    payload_raw = row["payload"]
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, TypeError):
        payload = {"raw": str(payload_raw)}

    return {
        "id": row["id"],
        "source_app": row["source_app"],
        "session_id": row["session_id"],
        "dispatch_id": row["dispatch_id"],
        "run_id": row["run_id"],
        "turn_id": row["turn_id"],
        "hook_event_type": row["hook_event_type"],
        "payload": payload,
        "summary": row["summary"],
        "model_name": row["model_name"],
        "timestamp": row["timestamp"],
    }
