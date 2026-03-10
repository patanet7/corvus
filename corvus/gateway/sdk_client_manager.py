"""SDKClientManager — persistent SDK client lifecycle management.

The sole interface between Corvus and ClaudeSDKClient. No other module
should import or instantiate ClaudeSDKClient directly.

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient


@dataclass
class ManagedClient:
    """Wraps a ClaudeSDKClient with Corvus metadata and accumulated metrics."""

    client: ClaudeSDKClient | None
    session_id: str
    agent_name: str
    sdk_session_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    active_run: bool = False
    immediate_teardown: bool = False
    options_snapshot: ClaudeAgentOptions | None = None

    # Guardrails
    max_turns: int | None = None
    max_budget_usd: float | None = None
    fallback_model: str | None = None
    checkpointing_enabled: bool = True
    effort: str | None = None

    # Accumulated metrics
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    turn_count: int = 0
    checkpoints: list[str] = field(default_factory=list)

    # Team membership
    team_name: str | None = None

    @classmethod
    def create_stub(cls, *, session_id: str, agent_name: str) -> ManagedClient:
        """Create a ManagedClient without a real SDK client (for tests/pool logic)."""
        return cls(client=None, session_id=session_id, agent_name=agent_name)

    def accumulate(self, *, tokens: int, cost_usd: float, sdk_session_id: str | None) -> None:
        """Update running totals after a completed response stream."""
        self.total_tokens += tokens
        self.total_cost_usd += cost_usd
        self.turn_count += 1
        if sdk_session_id:
            self.sdk_session_id = sdk_session_id
        self.last_activity = time.monotonic()
        self.active_run = False

    def track_checkpoint(self, user_message_uuid: str) -> None:
        """Record a UserMessage UUID for file checkpointing rewind."""
        self.checkpoints.append(user_message_uuid)


class AgentClientPool:
    """Pool of ManagedClient instances keyed by agent_name."""

    def __init__(self) -> None:
        self._clients: dict[str, ManagedClient] = {}

    def get(self, agent_name: str) -> ManagedClient | None:
        return self._clients.get(agent_name)

    def add(self, client: ManagedClient) -> None:
        self._clients[client.agent_name] = client

    def remove(self, agent_name: str) -> ManagedClient | None:
        return self._clients.pop(agent_name, None)

    def list_all(self) -> list[ManagedClient]:
        return list(self._clients.values())

    def collect_idle(self, *, timeout: float) -> list[ManagedClient]:
        """Remove and return clients that are idle beyond timeout or flagged for immediate teardown.

        Does NOT disconnect them — caller is responsible for calling client.disconnect().
        """
        now = time.monotonic()
        evicted: list[ManagedClient] = []
        for name, mc in list(self._clients.items()):
            if mc.active_run:
                continue
            if mc.immediate_teardown or (now - mc.last_activity > timeout):
                del self._clients[name]
                evicted.append(mc)
        return evicted

    def __len__(self) -> int:
        return len(self._clients)
