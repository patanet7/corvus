"""Repository classes for session, dispatch, run, and event persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from corvus.sessions.serializers import (
    dispatch_row_to_dict,
    event_row_to_dict,
    run_row_to_dict,
    session_row_to_dict,
    trace_row_to_dict,
)


class _RepositoryBase:
    """Shared utilities for all repository classes."""

    def __init__(
        self,
        conn_supplier: Callable[[], sqlite3.Connection],
        *,
        max_limit: int,
    ) -> None:
        self._conn_supplier = conn_supplier
        self._max_limit = max_limit

    def _conn(self) -> sqlite3.Connection:
        return self._conn_supplier()

    def _clamp(self, limit: int, multiplier: int = 1) -> int:
        upper = self._max_limit * multiplier
        return min(max(1, limit), upper)


class SessionRepository(_RepositoryBase):
    """CRUD repository for sessions and session messages."""

    def start(
        self,
        session_id: str,
        *,
        user: str,
        agent_name: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        ts = (started_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            "INSERT INTO sessions (id, user, started_at, agent_name) VALUES (?, ?, ?, ?)",
            (session_id, user, ts, agent_name),
        )
        conn.commit()

    def end(
        self,
        session_id: str,
        *,
        ended_at: datetime | None = None,
        summary: str | None = None,
        message_count: int = 0,
        tool_count: int = 0,
        agents_used: list[str] | None = None,
    ) -> None:
        ts = (ended_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """UPDATE sessions
               SET ended_at = ?, summary = ?, message_count = ?,
                   tool_count = ?, agents_used = ?
               WHERE id = ?""",
            (ts, summary, message_count, tool_count, json.dumps(agents_used or []), session_id),
        )
        conn.commit()

    def get(self, session_id: str) -> dict | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return session_row_to_dict(row)

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        agent_filter: str | None = None,
        user: str | None = None,
    ) -> list[dict]:
        limit = self._clamp(limit)
        conn = self._conn()
        sql = "SELECT * FROM sessions"
        conditions: list[str] = []
        params: list[object] = []

        if agent_filter:
            escaped = agent_filter.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("agents_used LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")

        if user:
            conditions.append("user = ?")
            params.append(user)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [session_row_to_dict(row) for row in rows]

    def delete(self, session_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

    def rename(self, session_id: str, name: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", (name, session_id))
        conn.commit()

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        agent: str | None = None,
        model: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        ts = (created_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO session_messages
               (session_id, role, content, agent, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, agent, model, ts),
        )
        conn.commit()

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=20)
        conn = self._conn()
        rows = conn.execute(
            """SELECT id, session_id, role, content, agent, model, created_at
               FROM session_messages
               WHERE session_id = ?
               ORDER BY id ASC
               LIMIT ? OFFSET ?""",
            (session_id, limit, offset),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "agent": row["agent"],
                "model": row["model"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class SessionEventRepository(_RepositoryBase):
    """Repository for session-scoped event stream persistence."""

    def add_event(
        self,
        session_id: str,
        *,
        event_type: str,
        payload: dict,
        turn_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        ts = (created_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO session_events
               (session_id, turn_id, event_type, payload, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, turn_id, event_type, json.dumps(payload), ts),
        )
        conn.commit()

    def list_events(
        self,
        session_id: str,
        *,
        limit: int = 2000,
        offset: int = 0,
        event_types: list[str] | None = None,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=20)
        conn = self._conn()

        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            rows = conn.execute(
                f"""SELECT id, session_id, turn_id, event_type, payload, created_at
                    FROM session_events
                    WHERE session_id = ? AND event_type IN ({placeholders})
                    ORDER BY id ASC
                    LIMIT ? OFFSET ?""",
                (session_id, *event_types, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, session_id, turn_id, event_type, payload, created_at
                   FROM session_events
                   WHERE session_id = ?
                   ORDER BY id ASC
                   LIMIT ? OFFSET ?""",
                (session_id, limit, offset),
            ).fetchall()

        return [event_row_to_dict(row) for row in rows]


class DispatchRepository(_RepositoryBase):
    """Repository for dispatch root lifecycle rows."""

    def create_dispatch(
        self,
        dispatch_id: str,
        *,
        session_id: str,
        turn_id: str | None,
        user: str,
        prompt: str,
        dispatch_mode: str,
        target_agents: list[str],
        status: str = "queued",
        created_at: datetime | None = None,
    ) -> None:
        ts = (created_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO dispatches
               (id, session_id, turn_id, user, prompt, dispatch_mode, target_agents, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dispatch_id,
                session_id,
                turn_id,
                user,
                prompt,
                dispatch_mode,
                json.dumps(target_agents),
                status,
                ts,
            ),
        )
        conn.commit()

    def update_dispatch(
        self,
        dispatch_id: str,
        *,
        status: str,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        ts = completed_at.isoformat() if completed_at else None
        conn = self._conn()
        conn.execute(
            """UPDATE dispatches
               SET status = ?, error = ?, completed_at = COALESCE(?, completed_at)
               WHERE id = ?""",
            (status, error, ts, dispatch_id),
        )
        conn.commit()

    def get_dispatch(self, dispatch_id: str) -> dict | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM dispatches WHERE id = ?", (dispatch_id,)).fetchone()
        if row is None:
            return None
        return dispatch_row_to_dict(row)

    def list_dispatches(
        self,
        *,
        user: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=4)
        conn = self._conn()
        sql = "SELECT * FROM dispatches"
        conditions: list[str] = []
        params: list[object] = []

        if user:
            conditions.append("user = ?")
            params.append(user)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dispatch_row_to_dict(row) for row in rows]

    def delete_dispatch(self, dispatch_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM dispatches WHERE id = ?", (dispatch_id,))
        conn.commit()


class RunRepository(_RepositoryBase):
    """Repository for individual per-agent run rows."""

    def start_agent_run(
        self,
        run_id: str,
        *,
        dispatch_id: str,
        session_id: str,
        turn_id: str | None,
        agent: str,
        backend: str | None = None,
        model: str | None = None,
        task_type: str | None = None,
        subtask_id: str | None = None,
        skill: str | None = None,
        status: str = "queued",
        started_at: datetime | None = None,
    ) -> None:
        ts = (started_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO agent_runs
               (id, dispatch_id, session_id, turn_id, agent, backend, model, status, started_at, task_type, subtask_id, skill)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                dispatch_id,
                session_id,
                turn_id,
                agent,
                backend,
                model,
                status,
                ts,
                task_type,
                subtask_id,
                skill,
            ),
        )
        conn.commit()

    def update_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: str | None = None,
        cost_usd: float | None = None,
        tokens_used: int | None = None,
        context_limit: int | None = None,
        context_pct: float | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        ts = completed_at.isoformat() if completed_at else None
        conn = self._conn()
        conn.execute(
            """UPDATE agent_runs
               SET status = ?,
                   summary = COALESCE(?, summary),
                   cost_usd = COALESCE(?, cost_usd),
                   tokens_used = COALESCE(?, tokens_used),
                   context_limit = COALESCE(?, context_limit),
                   context_pct = COALESCE(?, context_pct),
                   error = COALESCE(?, error),
                   completed_at = COALESCE(?, completed_at)
               WHERE id = ?""",
            (
                status,
                summary,
                cost_usd,
                tokens_used,
                context_limit,
                context_pct,
                error,
                ts,
                run_id,
            ),
        )
        conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        conn = self._conn()
        row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return run_row_to_dict(row)

    def list_agent_runs(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=2)
        conn = self._conn()
        sql = "SELECT * FROM agent_runs"
        conditions: list[str] = []
        params: list[object] = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [run_row_to_dict(row) for row in rows]

    def list_dispatch_runs(
        self,
        dispatch_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=2)
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM agent_runs
               WHERE dispatch_id = ?
               ORDER BY started_at ASC
               LIMIT ? OFFSET ?""",
            (dispatch_id, limit, offset),
        ).fetchall()
        return [run_row_to_dict(row) for row in rows]

    def list_runs(
        self,
        *,
        user: str | None = None,
        session_id: str | None = None,
        dispatch_id: str | None = None,
        agent: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=4)
        conn = self._conn()
        sql = "SELECT r.* FROM agent_runs r JOIN sessions s ON s.id = r.session_id"
        conditions: list[str] = []
        params: list[object] = []

        if user:
            conditions.append("s.user = ?")
            params.append(user)
        if session_id:
            conditions.append("r.session_id = ?")
            params.append(session_id)
        if dispatch_id:
            conditions.append("r.dispatch_id = ?")
            params.append(dispatch_id)
        if agent:
            conditions.append("r.agent = ?")
            params.append(agent)
        if status:
            conditions.append("r.status = ?")
            params.append(status)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY r.started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [run_row_to_dict(row) for row in rows]

    def delete_run(self, run_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM agent_runs WHERE id = ?", (run_id,))
        conn.commit()


class RunEventRepository(_RepositoryBase):
    """Repository for run-scoped and dispatch-scoped replay events."""

    def add_run_event(
        self,
        run_id: str,
        *,
        dispatch_id: str,
        session_id: str,
        event_type: str,
        payload: dict,
        turn_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        ts = (created_at or datetime.now(UTC)).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO run_events
               (run_id, dispatch_id, session_id, turn_id, event_type, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, dispatch_id, session_id, turn_id, event_type, json.dumps(payload), ts),
        )
        conn.commit()

    def list_run_events(self, run_id: str, *, limit: int = 2000, offset: int = 0) -> list[dict]:
        limit = self._clamp(limit, multiplier=20)
        conn = self._conn()
        rows = conn.execute(
            """SELECT id, run_id, dispatch_id, session_id, turn_id, event_type, payload, created_at
               FROM run_events
               WHERE run_id = ?
               ORDER BY id ASC
               LIMIT ? OFFSET ?""",
            (run_id, limit, offset),
        ).fetchall()
        return [event_row_to_dict(row) for row in rows]

    def list_dispatch_events(
        self,
        dispatch_id: str,
        *,
        limit: int = 4000,
        offset: int = 0,
        event_types: list[str] | None = None,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=20)
        conn = self._conn()

        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            rows = conn.execute(
                f"""SELECT id, run_id, dispatch_id, session_id, turn_id, event_type, payload, created_at
                    FROM run_events
                    WHERE dispatch_id = ? AND event_type IN ({placeholders})
                    ORDER BY id ASC
                    LIMIT ? OFFSET ?""",
                (dispatch_id, *event_types, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, run_id, dispatch_id, session_id, turn_id, event_type, payload, created_at
                   FROM run_events
                   WHERE dispatch_id = ?
                   ORDER BY id ASC
                   LIMIT ? OFFSET ?""",
                (dispatch_id, limit, offset),
            ).fetchall()

        return [event_row_to_dict(row) for row in rows]


class TraceEventRepository(_RepositoryBase):
    """Repository for hook-style observability events."""

    def add_trace_event(
        self,
        *,
        source_app: str,
        session_id: str,
        hook_event_type: str,
        payload: dict,
        dispatch_id: str | None = None,
        run_id: str | None = None,
        turn_id: str | None = None,
        summary: str | None = None,
        model_name: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        ts = (timestamp or datetime.now(UTC)).isoformat()
        conn = self._conn()
        cursor = conn.execute(
            """INSERT INTO trace_events
               (source_app, session_id, dispatch_id, run_id, turn_id, hook_event_type, payload, summary, model_name, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_app,
                session_id,
                dispatch_id,
                run_id,
                turn_id,
                hook_event_type,
                json.dumps(payload),
                summary,
                model_name,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute(
            """SELECT id, source_app, session_id, dispatch_id, run_id, turn_id,
                      hook_event_type, payload, summary, model_name, timestamp
               FROM trace_events WHERE id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Trace event insert succeeded but row could not be reloaded")
        return trace_row_to_dict(row)

    def get_trace_event(self, trace_id: int, *, user: str | None = None) -> dict | None:
        conn = self._conn()
        if user:
            row = conn.execute(
                """SELECT t.id, t.source_app, t.session_id, t.dispatch_id, t.run_id, t.turn_id,
                          t.hook_event_type, t.payload, t.summary, t.model_name, t.timestamp
                   FROM trace_events t
                   JOIN sessions s ON s.id = t.session_id
                   WHERE t.id = ? AND s.user = ?""",
                (trace_id, user),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT id, source_app, session_id, dispatch_id, run_id, turn_id,
                          hook_event_type, payload, summary, model_name, timestamp
                   FROM trace_events
                   WHERE id = ?""",
                (trace_id,),
            ).fetchone()
        if row is None:
            return None
        return trace_row_to_dict(row)

    def list_trace_events(
        self,
        *,
        user: str | None = None,
        source_apps: list[str] | None = None,
        session_ids: list[str] | None = None,
        dispatch_id: str | None = None,
        run_id: str | None = None,
        hook_event_types: list[str] | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[dict]:
        limit = self._clamp(limit, multiplier=20)
        conn = self._conn()
        select_cols = (
            "t.id, t.source_app, t.session_id, t.dispatch_id, t.run_id, t.turn_id, "
            "t.hook_event_type, t.payload, t.summary, t.model_name, t.timestamp"
        )
        sql = f"SELECT {select_cols} FROM trace_events t"
        conditions: list[str] = []
        params: list[object] = []

        if user:
            sql += " JOIN sessions s ON s.id = t.session_id"
            conditions.append("s.user = ?")
            params.append(user)

        if source_apps:
            placeholders = ",".join("?" for _ in source_apps)
            conditions.append(f"t.source_app IN ({placeholders})")
            params.extend(source_apps)
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            conditions.append(f"t.session_id IN ({placeholders})")
            params.extend(session_ids)
        if dispatch_id:
            conditions.append("t.dispatch_id = ?")
            params.append(dispatch_id)
        if run_id:
            conditions.append("t.run_id = ?")
            params.append(run_id)
        if hook_event_types:
            placeholders = ",".join("?" for _ in hook_event_types)
            conditions.append(f"t.hook_event_type IN ({placeholders})")
            params.extend(hook_event_types)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY t.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [trace_row_to_dict(row) for row in rows]

    def get_filter_options(self, *, user: str | None = None) -> dict:
        conn = self._conn()
        join = ""
        where = ""
        params: list[object] = []
        if user:
            join = " JOIN sessions s ON s.id = t.session_id "
            where = " WHERE s.user = ? "
            params.append(user)

        source_rows = conn.execute(
            f"SELECT DISTINCT t.source_app FROM trace_events t{join}{where}ORDER BY t.source_app ASC",
            params,
        ).fetchall()
        session_rows = conn.execute(
            f"SELECT DISTINCT t.session_id FROM trace_events t{join}{where}ORDER BY t.session_id DESC LIMIT 300",
            params,
        ).fetchall()
        hook_rows = conn.execute(
            f"SELECT DISTINCT t.hook_event_type FROM trace_events t{join}{where}ORDER BY t.hook_event_type ASC",
            params,
        ).fetchall()

        return {
            "source_apps": [str(row["source_app"]) for row in source_rows],
            "session_ids": [str(row["session_id"]) for row in session_rows],
            "hook_event_types": [str(row["hook_event_type"]) for row in hook_rows],
        }
