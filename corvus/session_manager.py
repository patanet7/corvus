"""Session/domain persistence facade.

Public API remains stable while internals are split into repository classes
under ``corvus.sessions``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from corvus.sessions.repositories import (
    DispatchRepository,
    RunEventRepository,
    RunRepository,
    SessionEventRepository,
    SessionRepository,
    TraceEventRepository,
)
from corvus.sessions.schema import ensure_schema


class SessionManager:
    """Facade for session, dispatch, run, and replay persistence."""

    _MAX_LIMIT = 500

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

        self._sessions = SessionRepository(self._get_conn, max_limit=self._MAX_LIMIT)
        self._session_events = SessionEventRepository(self._get_conn, max_limit=self._MAX_LIMIT)
        self._dispatches = DispatchRepository(self._get_conn, max_limit=self._MAX_LIMIT)
        self._runs = RunRepository(self._get_conn, max_limit=self._MAX_LIMIT)
        self._run_events = RunEventRepository(self._get_conn, max_limit=self._MAX_LIMIT)
        self._trace_events = TraceEventRepository(self._get_conn, max_limit=self._MAX_LIMIT)

    def _init_schema(self) -> None:
        ensure_schema(self._get_conn())

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def start(
        self,
        session_id: str,
        user: str,
        agent_name: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self._sessions.start(
            session_id,
            user=user,
            agent_name=agent_name,
            started_at=started_at,
        )

    def end(
        self,
        session_id: str,
        ended_at: datetime | None = None,
        summary: str | None = None,
        message_count: int = 0,
        tool_count: int = 0,
        agents_used: list[str] | None = None,
    ) -> None:
        self._sessions.end(
            session_id,
            ended_at=ended_at,
            summary=summary,
            message_count=message_count,
            tool_count=tool_count,
            agents_used=agents_used,
        )

    def get(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_filter: str | None = None,
        user: str | None = None,
    ) -> list[dict]:
        return self._sessions.list(
            limit=limit,
            offset=offset,
            agent_filter=agent_filter,
            user=user,
        )

    def delete(self, session_id: str) -> None:
        self._sessions.delete(session_id)

    def rename(self, session_id: str, name: str) -> None:
        self._sessions.rename(session_id, name)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._sessions.add_message(
            session_id,
            role=role,
            content=content,
            agent=agent,
            model=model,
            created_at=created_at,
        )

    def list_messages(self, session_id: str, limit: int = 2000, offset: int = 0) -> list[dict]:
        return self._sessions.list_messages(session_id, limit=limit, offset=offset)

    def add_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict,
        *,
        turn_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._session_events.add_event(
            session_id,
            event_type=event_type,
            payload=payload,
            turn_id=turn_id,
            created_at=created_at,
        )

    def list_events(
        self,
        session_id: str,
        limit: int = 2000,
        offset: int = 0,
        event_types: list[str] | None = None,
    ) -> list[dict]:
        return self._session_events.list_events(
            session_id,
            limit=limit,
            offset=offset,
            event_types=event_types,
        )

    # ------------------------------------------------------------------
    # Dispatch + Run lifecycle
    # ------------------------------------------------------------------

    def create_dispatch(
        self,
        dispatch_id: str,
        *,
        session_id: str,
        user: str,
        prompt: str,
        dispatch_mode: str,
        target_agents: list[str],
        turn_id: str | None = None,
        status: str = "queued",
        created_at: datetime | None = None,
    ) -> None:
        self._dispatches.create_dispatch(
            dispatch_id,
            session_id=session_id,
            turn_id=turn_id,
            user=user,
            prompt=prompt,
            dispatch_mode=dispatch_mode,
            target_agents=target_agents,
            status=status,
            created_at=created_at,
        )

    def update_dispatch(
        self,
        dispatch_id: str,
        *,
        status: str,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        self._dispatches.update_dispatch(
            dispatch_id,
            status=status,
            error=error,
            completed_at=completed_at,
        )

    def get_dispatch(self, dispatch_id: str) -> dict | None:
        return self._dispatches.get_dispatch(dispatch_id)

    def list_dispatches(
        self,
        *,
        user: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return self._dispatches.list_dispatches(
            user=user,
            session_id=session_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def delete_dispatch(self, dispatch_id: str) -> None:
        self._dispatches.delete_dispatch(dispatch_id)

    def start_agent_run(
        self,
        run_id: str,
        *,
        dispatch_id: str,
        session_id: str,
        agent: str,
        backend: str | None = None,
        model: str | None = None,
        task_type: str | None = None,
        subtask_id: str | None = None,
        skill: str | None = None,
        turn_id: str | None = None,
        status: str = "queued",
        started_at: datetime | None = None,
    ) -> None:
        self._runs.start_agent_run(
            run_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            backend=backend,
            model=model,
            task_type=task_type,
            subtask_id=subtask_id,
            skill=skill,
            status=status,
            started_at=started_at,
        )

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
        self._runs.update_agent_run(
            run_id,
            status=status,
            summary=summary,
            cost_usd=cost_usd,
            tokens_used=tokens_used,
            context_limit=context_limit,
            context_pct=context_pct,
            error=error,
            completed_at=completed_at,
        )

    def get_run(self, run_id: str) -> dict | None:
        return self._runs.get_run(run_id)

    def list_agent_runs(
        self,
        agent: str | None = None,
        *,
        status: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        return self._runs.list_agent_runs(
            agent=agent,
            status=status,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )

    def list_dispatch_runs(
        self,
        dispatch_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return self._runs.list_dispatch_runs(dispatch_id, limit=limit, offset=offset)

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
        return self._runs.list_runs(
            user=user,
            session_id=session_id,
            dispatch_id=dispatch_id,
            agent=agent,
            status=status,
            limit=limit,
            offset=offset,
        )

    def delete_run(self, run_id: str) -> None:
        self._runs.delete_run(run_id)

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
        self._run_events.add_run_event(
            run_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            turn_id=turn_id,
            created_at=created_at,
        )

    def list_run_events(self, run_id: str, limit: int = 2000, offset: int = 0) -> list[dict]:
        return self._run_events.list_run_events(run_id, limit=limit, offset=offset)

    def list_dispatch_events(
        self,
        dispatch_id: str,
        limit: int = 4000,
        offset: int = 0,
        event_types: list[str] | None = None,
    ) -> list[dict]:
        return self._run_events.list_dispatch_events(
            dispatch_id,
            limit=limit,
            offset=offset,
            event_types=event_types,
        )

    # ------------------------------------------------------------------
    # Trace observability
    # ------------------------------------------------------------------

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
        return self._trace_events.add_trace_event(
            source_app=source_app,
            session_id=session_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            turn_id=turn_id,
            hook_event_type=hook_event_type,
            payload=payload,
            summary=summary,
            model_name=model_name,
            timestamp=timestamp,
        )

    def get_trace_event(self, trace_id: int, *, user: str | None = None) -> dict | None:
        return self._trace_events.get_trace_event(trace_id, user=user)

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
        return self._trace_events.list_trace_events(
            user=user,
            source_apps=source_apps,
            session_ids=session_ids,
            dispatch_id=dispatch_id,
            run_id=run_id,
            hook_event_types=hook_event_types,
            limit=limit,
            offset=offset,
        )

    def get_trace_filter_options(self, *, user: str | None = None) -> dict:
        return self._trace_events.get_filter_options(user=user)

    def list_agent_sessions(
        self,
        agent_name: str,
        *,
        user: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self.list(limit=limit, offset=offset, agent_filter=agent_name, user=user)

    # ------------------------------------------------------------------
    # SDK session ID persistence (for session resume)
    # ------------------------------------------------------------------

    def _ensure_sdk_sessions_table(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sdk_sessions (
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                sdk_session_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, agent_name)
            )
        """)
        conn.commit()

    def store_sdk_session_id(self, session_id: str, agent_name: str, sdk_session_id: str) -> None:
        """Store or update the SDK session ID for a session/agent pair."""
        self._ensure_sdk_sessions_table()
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO sdk_sessions (session_id, agent_name, sdk_session_id, updated_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (session_id, agent_name, sdk_session_id),
        )
        conn.commit()

    def get_sdk_session_id(self, session_id: str, agent_name: str) -> str | None:
        """Get the stored SDK session ID for a session/agent pair, or None."""
        self._ensure_sdk_sessions_table()
        conn = self._get_conn()
        row = conn.execute(
            "SELECT sdk_session_id FROM sdk_sessions WHERE session_id = ? AND agent_name = ?",
            (session_id, agent_name),
        ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @staticmethod
    def session_to_markdown(session: dict, messages: list[dict] | None = None) -> str:
        """Export a session dict to Markdown format."""
        title = session.get("summary") or f"Session {session['id'][:8]}"
        agents = session.get("agents_used", [])
        agents_str = ", ".join(agents) if agents else "none"
        lines = [
            f"# {title}",
            "",
            f"**Session ID:** {session['id']}",
            f"**User:** {session['user']}",
            f"**Started:** {session['started_at']}",
            f"**Ended:** {session.get('ended_at') or 'In progress'}",
            f"**Messages:** {session.get('message_count', 0)}",
            f"**Tool calls:** {session.get('tool_count', 0)}",
            f"**Agents:** {agents_str}",
            "",
        ]
        if messages:
            lines.append("## Transcript")
            lines.append("")
            for msg in messages:
                role = str(msg.get("role", "assistant")).strip().title()
                agent = msg.get("agent")
                model = msg.get("model")
                label = role
                if agent:
                    label += f" ({agent})"
                if model:
                    label += f" [{model}]"
                lines.append(f"**{label}:** {msg.get('content', '')}")
                lines.append("")
        return "\n".join(lines)
