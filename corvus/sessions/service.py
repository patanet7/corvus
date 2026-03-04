"""Transport-agnostic session domain service.

Provides user-scoped access helpers for sessions, dispatches, and runs so API
handlers stay thin and consistent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from corvus.session_manager import SessionManager


class SessionService:
    """Application service wrapping SessionManager with user scoping."""

    def __init__(self, session_mgr: SessionManager) -> None:
        self._session_mgr = session_mgr

    def list_sessions(
        self,
        *,
        user: str,
        agent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self._session_mgr.list(limit=limit, offset=offset, agent_filter=agent, user=user)

    def get_user_session(self, session_id: str, *, user: str) -> dict | None:
        session = self._session_mgr.get(session_id)
        if not session or session.get("user") != user:
            return None
        return session

    def list_user_session_messages(
        self,
        session_id: str,
        *,
        user: str,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[dict] | None:
        if not self.get_user_session(session_id, user=user):
            return None
        return self._session_mgr.list_messages(session_id, limit=limit, offset=offset)

    def list_user_session_events(
        self,
        session_id: str,
        *,
        user: str,
        limit: int = 2000,
        offset: int = 0,
        event_types: list[str] | None = None,
    ) -> list[dict] | None:
        if not self.get_user_session(session_id, user=user):
            return None
        return self._session_mgr.list_events(
            session_id,
            limit=limit,
            offset=offset,
            event_types=event_types,
        )

    def rename_user_session(self, session_id: str, *, user: str, name: str) -> bool:
        if not self.get_user_session(session_id, user=user):
            return False
        self._session_mgr.rename(session_id, name)
        return True

    def delete_user_session(self, session_id: str, *, user: str) -> bool:
        if not self.get_user_session(session_id, user=user):
            return False
        self._session_mgr.delete(session_id)
        return True

    def export_user_session_markdown(self, session_id: str, *, user: str) -> str | None:
        session = self.get_user_session(session_id, user=user)
        if not session:
            return None
        messages = self._session_mgr.list_messages(session_id)
        return self._session_mgr.session_to_markdown(session, messages)

    def get_user_dispatch(self, dispatch_id: str, *, user: str) -> dict | None:
        dispatch = self._session_mgr.get_dispatch(dispatch_id)
        if not dispatch:
            return None
        return dispatch if self.get_user_session(dispatch["session_id"], user=user) else None

    def get_user_run(self, run_id: str, *, user: str) -> dict | None:
        run = self._session_mgr.get_run(run_id)
        if not run:
            return None
        return run if self.get_user_session(run["session_id"], user=user) else None

    def list_user_dispatches(
        self,
        *,
        user: str,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return self._session_mgr.list_dispatches(
            user=user,
            session_id=session_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def list_user_runs(
        self,
        *,
        user: str,
        session_id: str | None = None,
        dispatch_id: str | None = None,
        agent: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return self._session_mgr.list_runs(
            user=user,
            session_id=session_id,
            dispatch_id=dispatch_id,
            agent=agent,
            status=status,
            limit=limit,
            offset=offset,
        )
