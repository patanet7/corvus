"""SDKClientManager — persistent SDK client lifecycle management.

The sole interface between Corvus and ClaudeSDKClient. No other module
should import or instantiate ClaudeSDKClient directly.

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

log = logging.getLogger(__name__)


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


@dataclass
class ClientInfo:
    """Snapshot of a ManagedClient for status reporting."""

    session_id: str
    agent_name: str
    sdk_session_id: str | None
    active_run: bool
    turn_count: int
    total_tokens: int
    total_cost_usd: float
    idle_seconds: float
    team_name: str | None


class SDKClientManager:
    """Central manager for all SDK client lifecycles.

    All SDK access goes through this class. It manages per-session pools,
    idle eviction, and provides methods for querying, interrupting, and
    tearing down clients.
    """

    def __init__(self, runtime: Any, *, idle_timeout: float = 600.0) -> None:
        self._runtime = runtime
        self._pools: dict[str, AgentClientPool] = {}
        self._idle_timeout = idle_timeout
        self._eviction_task: asyncio.Task[None] | None = None

    # ── Pool management ──────────────────────────────────────────────

    def _get_pool(self, session_id: str) -> AgentClientPool:
        """Lazy-create and return the AgentClientPool for a session."""
        pool = self._pools.get(session_id)
        if pool is None:
            pool = AgentClientPool()
            self._pools[session_id] = pool
        return pool

    def _get_existing(self, session_id: str, agent_name: str) -> ManagedClient | None:
        """Get an existing client, updating last_activity. Returns None if not found."""
        pool = self._pools.get(session_id)
        if pool is None:
            return None
        mc = pool.get(agent_name)
        if mc is not None:
            mc.last_activity = time.monotonic()
        return mc

    def release(self, session_id: str, agent_name: str) -> None:
        """Mark a client as inactive (no longer running a turn)."""
        pool = self._pools.get(session_id)
        if pool is None:
            return
        mc = pool.get(agent_name)
        if mc is not None:
            mc.active_run = False
            mc.last_activity = time.monotonic()

    # ── Collection (for teardown/eviction) ───────────────────────────

    def _collect_session_clients(self, session_id: str) -> list[ManagedClient]:
        """Pop an entire session pool and return all its clients."""
        pool = self._pools.pop(session_id, None)
        if pool is None:
            return []
        return pool.list_all()

    def _collect_all_idle(self) -> list[ManagedClient]:
        """Collect idle clients from all pools, cleaning up empty pools."""
        evicted: list[ManagedClient] = []
        empty_sessions: list[str] = []
        for session_id, pool in self._pools.items():
            evicted.extend(pool.collect_idle(timeout=self._idle_timeout))
            if len(pool) == 0:
                empty_sessions.append(session_id)
        for session_id in empty_sessions:
            del self._pools[session_id]
        return evicted

    # ── Status reporting ─────────────────────────────────────────────

    def list_active_clients(self) -> list[ClientInfo]:
        """Return a snapshot of all active clients across all sessions."""
        now = time.monotonic()
        result: list[ClientInfo] = []
        for _session_id, pool in self._pools.items():
            for mc in pool.list_all():
                result.append(
                    ClientInfo(
                        session_id=mc.session_id,
                        agent_name=mc.agent_name,
                        sdk_session_id=mc.sdk_session_id,
                        active_run=mc.active_run,
                        turn_count=mc.turn_count,
                        total_tokens=mc.total_tokens,
                        total_cost_usd=mc.total_cost_usd,
                        idle_seconds=now - mc.last_activity,
                        team_name=mc.team_name,
                    )
                )
        return result

    # ── Async SDK operations (stubs for Task 2, implemented in later tasks) ──

    async def get_or_create(
        self,
        session_id: str,
        agent_name: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient:
        """Return existing client or create a new one.

        options_builder is called only when a new client must be created.
        """
        existing = self._get_existing(session_id, agent_name)
        if existing is not None:
            return existing
        raise NotImplementedError("Full get_or_create implemented in Task 5")

    async def query(
        self,
        session_id: str,
        agent_name: str,
        prompt: str | AsyncIterable[dict[str, Any]],
    ) -> ManagedClient:
        """Send a prompt to a client and return the ManagedClient (caller streams from it)."""
        raise NotImplementedError("Implemented in Task 5")

    async def receive_response(self, mc: ManagedClient) -> AsyncIterable[Any]:
        """Yield stream events from a running client."""
        raise NotImplementedError("Implemented in Task 5")

    async def interrupt(self, session_id: str, agent_name: str) -> bool:
        """Interrupt an active run. Returns True if interrupted."""
        raise NotImplementedError("Implemented in Task 5")

    async def set_model(self, session_id: str, agent_name: str, model: str) -> None:
        """Change the model for an existing client."""
        raise NotImplementedError("Implemented in Task 5")

    async def set_permission_mode(
        self, session_id: str, agent_name: str, mode: str
    ) -> None:
        """Change the permission mode for an existing client."""
        raise NotImplementedError("Implemented in Task 5")

    async def resume_sdk_session(
        self, session_id: str, agent_name: str, sdk_session_id: str
    ) -> ManagedClient:
        """Resume a previously persisted SDK session."""
        raise NotImplementedError("Implemented in Task 5")

    async def get_or_resume(
        self,
        session_id: str,
        agent_name: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient:
        """Try resume first (if SDK session ID stored), fall back to fresh."""
        raise NotImplementedError("Implemented in Task 5")

    async def fork_session(
        self, source_session_id: str, target_session_id: str, agent_name: str
    ) -> ManagedClient:
        """Fork a client from one session into a new session."""
        raise NotImplementedError("Implemented in Task 8")

    async def rewind_files(
        self, session_id: str, agent_name: str, checkpoint_uuid: str
    ) -> bool:
        """Rewind file state to a previous checkpoint."""
        raise NotImplementedError("Implemented in Task 8")

    async def get_mcp_status(self, session_id: str, agent_name: str) -> dict[str, Any]:
        """Get MCP server status for a client."""
        raise NotImplementedError("Implemented in Task 7")

    async def add_mcp_server(
        self, session_id: str, agent_name: str, server_config: dict[str, Any]
    ) -> None:
        """Add an MCP server to a running client."""
        raise NotImplementedError("Implemented in Task 7")

    async def remove_mcp_server(
        self, session_id: str, agent_name: str, server_name: str
    ) -> None:
        """Remove an MCP server from a running client."""
        raise NotImplementedError("Implemented in Task 7")

    async def get_server_info(self, session_id: str, agent_name: str) -> dict[str, Any]:
        """Get server info for a client."""
        raise NotImplementedError("Implemented in Task 7")

    async def teardown_session(self, session_id: str) -> int:
        """Tear down all clients in a session. Returns count of clients torn down."""
        clients = self._collect_session_clients(session_id)
        for mc in clients:
            if mc.client is not None:
                try:
                    await mc.client.disconnect()
                except Exception:
                    log.warning(
                        "Error disconnecting client %s/%s",
                        mc.session_id,
                        mc.agent_name,
                        exc_info=True,
                    )
        return len(clients)

    async def teardown_all(self) -> int:
        """Tear down every client across all sessions and stop eviction. Returns total count."""
        await self.stop_eviction_loop()
        all_session_ids = list(self._pools.keys())
        total = 0
        for session_id in all_session_ids:
            total += await self.teardown_session(session_id)
        return total

    async def evict_idle(self) -> int:
        """Evict all idle clients. Returns count of evicted clients."""
        evicted = self._collect_all_idle()
        for mc in evicted:
            if mc.client is not None:
                try:
                    await mc.client.disconnect()
                except Exception:
                    log.warning(
                        "Error disconnecting idle client %s/%s",
                        mc.session_id,
                        mc.agent_name,
                        exc_info=True,
                    )
        return len(evicted)

    # ── Eviction loop ────────────────────────────────────────────────

    async def _eviction_loop(self) -> None:
        """Background loop that periodically evicts idle clients."""
        while True:
            try:
                await asyncio.sleep(self._idle_timeout / 2)
                count = await self.evict_idle()
                if count > 0:
                    log.info("Evicted %d idle client(s)", count)
            except asyncio.CancelledError:
                break
            except Exception:
                log.warning("Error in eviction loop", exc_info=True)

    def start_eviction_loop(self) -> None:
        """Start the background eviction loop."""
        if self._eviction_task is None or self._eviction_task.done():
            self._eviction_task = asyncio.create_task(self._eviction_loop())

    async def stop_eviction_loop(self) -> None:
        """Stop the background eviction loop."""
        if self._eviction_task is not None and not self._eviction_task.done():
            self._eviction_task.cancel()
            try:
                await self._eviction_task
            except asyncio.CancelledError:
                pass
            self._eviction_task = None
