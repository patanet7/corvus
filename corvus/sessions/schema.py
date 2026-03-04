"""SQLite schema bootstrap for session/dispatch/run persistence."""

from __future__ import annotations

import sqlite3

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    summary TEXT,
    agent_name TEXT,
    message_count INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    agents_used TEXT DEFAULT '[]'
)
"""

_CREATE_SESSION_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    agent TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

_CREATE_SESSION_MESSAGES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_session_messages_session_created
ON session_messages(session_id, id)
"""

_CREATE_SESSION_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

_CREATE_SESSION_EVENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_session_events_session_created
ON session_events(session_id, id)
"""

_CREATE_DISPATCHES_TABLE = """
CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    user TEXT NOT NULL,
    prompt TEXT NOT NULL,
    dispatch_mode TEXT NOT NULL,
    target_agents TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

_CREATE_DISPATCHES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_dispatches_session_created
ON dispatches(session_id, created_at)
"""

_CREATE_AGENT_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    agent TEXT NOT NULL,
    backend TEXT,
    model TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT,
    cost_usd REAL DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    context_limit INTEGER DEFAULT 0,
    context_pct REAL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

_CREATE_AGENT_RUNS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_started
ON agent_runs(agent, started_at)
"""

_CREATE_AGENT_RUNS_DISPATCH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_dispatch_started
ON agent_runs(dispatch_id, started_at)
"""

_CREATE_RUN_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

_CREATE_RUN_EVENTS_RUN_INDEX = """
CREATE INDEX IF NOT EXISTS idx_run_events_run_created
ON run_events(run_id, id)
"""

_CREATE_RUN_EVENTS_DISPATCH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_run_events_dispatch_created
ON run_events(dispatch_id, id)
"""

_CREATE_TRACE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_app TEXT NOT NULL,
    session_id TEXT NOT NULL,
    dispatch_id TEXT,
    run_id TEXT,
    turn_id TEXT,
    hook_event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    summary TEXT,
    model_name TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(dispatch_id) REFERENCES dispatches(id) ON DELETE SET NULL,
    FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
)
"""

_CREATE_TRACE_EVENTS_SESSION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_trace_events_session_timestamp
ON trace_events(session_id, timestamp)
"""

_CREATE_TRACE_EVENTS_DISPATCH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_trace_events_dispatch_timestamp
ON trace_events(dispatch_id, timestamp)
"""

_CREATE_TRACE_EVENTS_RUN_INDEX = """
CREATE INDEX IF NOT EXISTS idx_trace_events_run_timestamp
ON trace_events(run_id, timestamp)
"""

_CREATE_TRACE_EVENTS_SOURCE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_trace_events_source
ON trace_events(source_app)
"""

_CREATE_TRACE_EVENTS_TYPE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_trace_events_hook_type
ON trace_events(hook_event_type)
"""


def _ensure_agent_runs_columns(conn: sqlite3.Connection) -> None:
    """Backfill optional route metadata columns for existing databases."""
    existing = {str(row["name"]) for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()}
    if "task_type" not in existing:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN task_type TEXT")
    if "subtask_id" not in existing:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN subtask_id TEXT")
    if "skill" not in existing:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN skill TEXT")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create/upgrade all session domain tables and indexes."""
    conn.execute(_CREATE_SESSIONS_TABLE)
    conn.execute(_CREATE_SESSION_MESSAGES_TABLE)
    conn.execute(_CREATE_SESSION_MESSAGES_INDEX)
    conn.execute(_CREATE_SESSION_EVENTS_TABLE)
    conn.execute(_CREATE_SESSION_EVENTS_INDEX)
    conn.execute(_CREATE_DISPATCHES_TABLE)
    conn.execute(_CREATE_DISPATCHES_INDEX)
    conn.execute(_CREATE_AGENT_RUNS_TABLE)
    _ensure_agent_runs_columns(conn)
    conn.execute(_CREATE_AGENT_RUNS_INDEX)
    conn.execute(_CREATE_AGENT_RUNS_DISPATCH_INDEX)
    conn.execute(_CREATE_RUN_EVENTS_TABLE)
    conn.execute(_CREATE_RUN_EVENTS_RUN_INDEX)
    conn.execute(_CREATE_RUN_EVENTS_DISPATCH_INDEX)
    conn.execute(_CREATE_TRACE_EVENTS_TABLE)
    conn.execute(_CREATE_TRACE_EVENTS_SESSION_INDEX)
    conn.execute(_CREATE_TRACE_EVENTS_DISPATCH_INDEX)
    conn.execute(_CREATE_TRACE_EVENTS_RUN_INDEX)
    conn.execute(_CREATE_TRACE_EVENTS_SOURCE_INDEX)
    conn.execute(_CREATE_TRACE_EVENTS_TYPE_INDEX)
    conn.commit()
