"""ACP session state tracking for Corvus.

Manages in-memory state for ACP agent sessions — tracking process PIDs,
session IDs, and lifecycle status.
"""

import structlog
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = structlog.get_logger(__name__)


@dataclass
class AcpSessionState:
    """Represents the state of a single ACP agent session."""

    corvus_run_id: str
    corvus_session_id: str
    acp_agent: str
    parent_agent: str
    process_pid: int
    acp_session_id: str | None = None
    status: str = "uninitialized"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_prompt_at: datetime | None = None
    total_turns: int = 0


class AcpSessionTracker:
    """In-memory tracker for ACP agent session lifecycle.

    Keyed by corvus_run_id. Provides create/get/update/remove operations
    and filtering by corvus_session_id.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AcpSessionState] = {}

    def create(
        self,
        *,
        corvus_run_id: str,
        corvus_session_id: str,
        acp_agent: str,
        parent_agent: str,
        process_pid: int,
    ) -> AcpSessionState:
        """Create and register a new ACP session state."""
        state = AcpSessionState(
            corvus_run_id=corvus_run_id,
            corvus_session_id=corvus_session_id,
            acp_agent=acp_agent,
            parent_agent=parent_agent,
            process_pid=process_pid,
        )
        self._sessions[corvus_run_id] = state
        logger.info(
            "acp_session_created",
            run_id=corvus_run_id,
            agent=acp_agent,
            pid=process_pid,
        )
        return state

    def get(self, corvus_run_id: str) -> AcpSessionState | None:
        """Get session state by corvus_run_id, or None if not found."""
        return self._sessions.get(corvus_run_id)

    def update_status(self, corvus_run_id: str, status: str) -> None:
        """Update the status of an existing session."""
        state = self._sessions.get(corvus_run_id)
        if state is None:
            logger.warning("acp_session_update_status_unknown", run_id=corvus_run_id)
            return
        state.status = status
        logger.info("acp_session_status_updated", run_id=corvus_run_id, status=status)

    def set_acp_session_id(
        self, corvus_run_id: str, acp_session_id: str
    ) -> None:
        """Set the ACP-level session ID on an existing session."""
        state = self._sessions.get(corvus_run_id)
        if state is None:
            logger.warning("acp_session_set_id_unknown", run_id=corvus_run_id)
            return
        state.acp_session_id = acp_session_id
        logger.info("acp_session_id_set", run_id=corvus_run_id, acp_session_id=acp_session_id)

    def remove(self, corvus_run_id: str) -> None:
        """Remove a session from tracking."""
        removed = self._sessions.pop(corvus_run_id, None)
        if removed:
            logger.info("acp_session_removed", run_id=corvus_run_id)
        else:
            logger.warning("acp_session_remove_unknown", run_id=corvus_run_id)

    def list_by_session(
        self, corvus_session_id: str
    ) -> list[AcpSessionState]:
        """Return all ACP sessions belonging to a given corvus_session_id."""
        return [
            state
            for state in self._sessions.values()
            if state.corvus_session_id == corvus_session_id
        ]
