"""TUI Session Manager — wraps gateway protocol with agent stack awareness.

Coordinates session lifecycle (create, resume, list) with the AgentStack so
that resuming a session automatically restores the correct agent context.
"""

import uuid

from corvus.tui.core.agent_stack import AgentStack
from corvus.tui.protocol.base import GatewayProtocol, SessionDetail, SessionSummary


class TuiSessionManager:
    """Manages TUI sessions — wraps gateway protocol with agent stack awareness."""

    def __init__(self, gateway: GatewayProtocol, agent_stack: AgentStack) -> None:
        self._gateway = gateway
        self._agent_stack = agent_stack
        self._current_session_id: str | None = None

    @property
    def current_session_id(self) -> str | None:
        """Return the current session ID, or None if no session is active."""
        return self._current_session_id

    async def create(self, agent_name: str) -> str:
        """Create a new session for the given agent. Returns session_id.

        For now, session creation happens implicitly on first message.
        This sets tracking state and pushes the agent onto the stack.
        """
        session_id = str(uuid.uuid4())
        self._current_session_id = session_id
        self._agent_stack.switch(agent_name, session_id=session_id)
        return session_id

    async def resume(self, session_id: str) -> SessionDetail:
        """Resume a session — loads history and restores agent stack.

        Calls the gateway to fetch session detail, sets the current session,
        and switches the agent stack to match the session's agent.
        """
        detail = await self._gateway.resume_session(session_id)
        self._current_session_id = session_id

        # Restore agent stack from session state
        if detail.agent_name:
            self._agent_stack.switch(detail.agent_name, session_id=session_id)

        return detail

    async def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """List recent sessions, capped at *limit*."""
        sessions = await self._gateway.list_sessions()
        return sessions[:limit]

    async def search(self, query: str) -> list[SessionSummary]:
        """Search sessions by query matching summary or agent_name (case-insensitive).

        Args:
            query: Search string to match against session summary and agent_name.

        Returns:
            List of SessionSummary objects whose summary or agent_name contains
            the query string (case-insensitive).
        """
        sessions = await self.list_sessions()
        q = query.lower()
        return [
            s
            for s in sessions
            if q in (s.summary or "").lower() or q in (s.agent_name or "").lower()
        ]

    def format_session_summary(self, session: SessionSummary) -> str:
        """Format a session for display in a list.

        Returns a fixed-width-ish string like:
            ``ab12cd34  2026-03-08 14:30  @work  5 msgs  Fixed the deploy issue``
        """
        ts = (
            session.started_at.strftime("%Y-%m-%d %H:%M")
            if session.started_at
            else "unknown"
        )
        agent = session.agent_name or "unknown"
        msgs = session.message_count
        summary = session.summary[:50] if session.summary else "(no summary)"
        return f"{session.session_id[:8]}  {ts}  @{agent}  {msgs} msgs  {summary}"
