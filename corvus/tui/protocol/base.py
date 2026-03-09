"""Abstract gateway protocol for the Corvus TUI.

Defines the interface that any gateway backend (WebSocket, HTTP, local
in-process) must implement so the TUI can remain transport-agnostic.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from corvus.tui.protocol.events import ProtocolEvent

# ---------------------------------------------------------------------------
# Session data containers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SessionSummary:
    """Lightweight session metadata returned by list_sessions."""

    session_id: str
    agent_name: str = ""
    summary: str = ""
    started_at: datetime | None = None
    message_count: int = 0
    agents_used: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SessionDetail(SessionSummary):
    """Full session detail including message history."""

    messages: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract gateway protocol
# ---------------------------------------------------------------------------

class GatewayProtocol(ABC):
    """Transport-agnostic interface between the TUI and the Corvus gateway.

    Implementations handle connection lifecycle, message sending, and event
    streaming.  The TUI consumes ``ProtocolEvent`` objects via ``on_event``
    callbacks or async iteration.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the gateway."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly disconnect from the gateway."""

    @abstractmethod
    async def send_message(
        self,
        text: str,
        *,
        session_id: str | None = None,
        requested_agent: str | None = None,
    ) -> None:
        """Send a user message to the gateway.

        Parameters
        ----------
        text:
            The user's chat message.
        session_id:
            Optional session to send into.  If ``None`` the gateway creates
            or resumes a default session.
        requested_agent:
            If set, bypass router classification and send directly to this
            agent.  ``None`` lets the router decide.
        """

    @abstractmethod
    async def respond_confirm(self, tool_id: str, approved: bool) -> None:
        """Respond to a tool confirmation request.

        Parameters
        ----------
        tool_id:
            The ``tool_id`` from the ``ConfirmRequest`` event.
        approved:
            Whether the user approved the tool call.
        """

    @abstractmethod
    async def cancel_run(self, run_id: str) -> None:
        """Request cancellation of an in-progress agent run."""

    @abstractmethod
    async def list_sessions(self) -> list[SessionSummary]:
        """Return summaries of all available sessions."""

    @abstractmethod
    async def resume_session(self, session_id: str) -> SessionDetail:
        """Load full detail for a session to resume it."""

    @abstractmethod
    async def list_agents(self) -> list[dict[str, Any]]:
        """Return metadata for all available agents."""

    @abstractmethod
    async def list_models(self) -> list[dict[str, Any]]:
        """Return metadata for all available models."""

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def memory_search(self, query: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories by query for the given agent."""

    @abstractmethod
    async def memory_list(self, agent_name: str, limit: int = 20) -> list[dict[str, Any]]:
        """List recent memories for the given agent."""

    @abstractmethod
    async def memory_save(self, content: str, agent_name: str) -> str:
        """Save a new memory. Returns the record ID."""

    @abstractmethod
    async def memory_forget(self, record_id: str, agent_name: str) -> bool:
        """Soft-delete a memory by ID. Returns True if deleted."""

    # ------------------------------------------------------------------
    # Tool queries
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_agent_tools(self, agent_name: str) -> list[dict[str, Any]]:
        """Return tool definitions for a specific agent."""

    @abstractmethod
    def on_event(
        self,
        callback: Callable[[ProtocolEvent], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async callback to receive protocol events.

        Parameters
        ----------
        callback:
            Async function called with each ``ProtocolEvent`` as it arrives.
        """
