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
from pathlib import Path
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


@dataclass
class TeamContext:
    """Metadata for an active agent team."""

    team_name: str
    session_id: str
    members: dict[str, ManagedClient]
    inbox_dir: Path
    task_dir: Path
    created_at: float = field(default_factory=time.monotonic)
    inbox_monitor_task: asyncio.Task[None] | None = field(default=None, repr=False)


@dataclass
class TeamMessage:
    """A message between team members."""

    from_agent: str
    to_agent: str | None  # None = broadcast
    text: str
    summary: str
    timestamp: str
    read: bool
    message_type: str  # "message" | "broadcast" | "shutdown_request" | etc.


@dataclass
class TeamTask:
    """A task in the shared team task list."""

    id: str
    subject: str
    description: str
    status: str  # "pending" | "in_progress" | "completed"
    owner: str | None
    blocked_by: list[str] = field(default_factory=list)


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

    def set_runtime(self, runtime: Any) -> None:
        """Set runtime back-reference after GatewayRuntime construction."""
        self._runtime = runtime

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

    # ── Async SDK operations ────────────────────────────────────────

    async def _create_client(
        self,
        session_id: str,
        agent_name: str,
        options: ClaudeAgentOptions,
    ) -> ManagedClient:
        """Create a new ClaudeSDKClient, connect it, and register in the pool."""
        client = ClaudeSDKClient(options=options)
        try:
            await client.connect()
        except Exception:
            log.error(
                "SDK client connect failed for %s/%s — check API key and network",
                session_id,
                agent_name,
                exc_info=True,
            )
            raise
        mc = ManagedClient(
            client=client,
            session_id=session_id,
            agent_name=agent_name,
            options_snapshot=options,
            max_turns=options.max_turns,
            max_budget_usd=options.max_budget_usd,
            fallback_model=options.fallback_model,
            checkpointing_enabled=bool(options.enable_file_checkpointing),
            effort=options.effort,
        )
        pool = self._get_pool(session_id)
        pool.add(mc)
        log.info("Created SDK client for %s/%s", session_id, agent_name)
        return mc

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
        options = options_builder()
        return await self._create_client(session_id, agent_name, options)

    async def query(
        self,
        session_id: str,
        agent_name: str,
        prompt: str | AsyncIterable[dict[str, Any]],
    ) -> ManagedClient:
        """Send a prompt to a client and return the ManagedClient (caller streams from it)."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            log.error("No active client for %s/%s — was get_or_create called?", session_id, agent_name)
            raise RuntimeError(f"No active client for {session_id}/{agent_name}")
        mc.active_run = True
        try:
            await mc.client.query(prompt, session_id=session_id)
        except Exception:
            mc.active_run = False
            log.error(
                "SDK query failed for %s/%s — prompt length=%d",
                session_id,
                agent_name,
                len(prompt) if isinstance(prompt, str) else -1,
                exc_info=True,
            )
            raise
        return mc

    async def interrupt(self, session_id: str, agent_name: str) -> bool:
        """Interrupt an active run. Returns True if interrupted."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None or not mc.active_run:
            return False
        try:
            mc.client.interrupt()
            mc.active_run = False
            log.info("Interrupted client %s/%s", session_id, agent_name)
            return True
        except Exception:
            log.warning("Failed to interrupt %s/%s", session_id, agent_name, exc_info=True)
            return False

    async def set_model(self, session_id: str, agent_name: str, model: str) -> None:
        """Change the model for an existing client."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            raise RuntimeError(f"No active client for {session_id}/{agent_name}")
        await mc.client.set_model(model)

    async def set_permission_mode(
        self, session_id: str, agent_name: str, mode: str
    ) -> None:
        """Change the permission mode for an existing client."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            raise RuntimeError(f"No active client for {session_id}/{agent_name}")
        await mc.client.set_permission_mode(mode)

    async def resume_sdk_session(
        self, session_id: str, agent_name: str, sdk_session_id: str
    ) -> ManagedClient:
        """Resume a previously persisted SDK session."""
        existing = self._get_existing(session_id, agent_name)
        if existing is not None:
            return existing
        options = ClaudeAgentOptions(resume=sdk_session_id)
        mc = await self._create_client(session_id, agent_name, options)
        mc.sdk_session_id = sdk_session_id
        log.info("Resumed SDK session %s for %s/%s", sdk_session_id, session_id, agent_name)
        return mc

    async def get_or_resume(
        self,
        session_id: str,
        agent_name: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient:
        """Try resume first (if SDK session ID stored), fall back to fresh."""
        existing = self._get_existing(session_id, agent_name)
        if existing is not None:
            return existing
        # Try to find a stored SDK session ID for resume
        if self._runtime is not None and hasattr(self._runtime, "session_mgr"):
            stored_id = self._runtime.session_mgr.get_sdk_session_id(session_id, agent_name)
            if stored_id:
                try:
                    return await self.resume_sdk_session(session_id, agent_name, stored_id)
                except Exception:
                    log.warning(
                        "Failed to resume SDK session %s for %s/%s, creating fresh",
                        stored_id, session_id, agent_name, exc_info=True,
                    )
        options = options_builder()
        return await self._create_client(session_id, agent_name, options)

    async def fork_session(
        self, source_session_id: str, target_session_id: str, agent_name: str
    ) -> ManagedClient:
        """Fork a client from one session into a new session."""
        source = self._get_existing(source_session_id, agent_name)
        if source is None or source.sdk_session_id is None:
            raise RuntimeError(
                f"Cannot fork: no client or SDK session for {source_session_id}/{agent_name}"
            )
        options = ClaudeAgentOptions(
            resume=source.sdk_session_id,
            fork_session=True,
        )
        mc = await self._create_client(target_session_id, agent_name, options)
        log.info(
            "Forked SDK session from %s to %s for agent %s",
            source_session_id, target_session_id, agent_name,
        )
        return mc

    async def rewind_files(
        self, session_id: str, agent_name: str, checkpoint_uuid: str
    ) -> bool:
        """Rewind file state to a previous checkpoint."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            return False
        try:
            mc.client.rewind_files(checkpoint_uuid)
            log.info("Rewound files for %s/%s to checkpoint %s", session_id, agent_name, checkpoint_uuid)
            return True
        except Exception:
            log.warning(
                "Failed to rewind files for %s/%s", session_id, agent_name, exc_info=True,
            )
            return False

    async def get_mcp_status(self, session_id: str, agent_name: str) -> dict[str, Any]:
        """Get MCP server status for a client."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            return {}
        return mc.client.get_mcp_status()

    async def add_mcp_server(
        self, session_id: str, agent_name: str, server_config: dict[str, Any]
    ) -> None:
        """Add an MCP server to a running client.

        Note: ClaudeSDKClient does not have a direct add_mcp_server method.
        MCP servers are configured via ClaudeAgentOptions at creation time.
        This method is a placeholder for future SDK support.
        """
        log.warning("add_mcp_server not yet supported by SDK — config at creation time instead")

    async def remove_mcp_server(
        self, session_id: str, agent_name: str, server_name: str
    ) -> None:
        """Remove an MCP server from a running client.

        Note: ClaudeSDKClient does not have a direct remove_mcp_server method.
        This method is a placeholder for future SDK support.
        """
        log.warning("remove_mcp_server not yet supported by SDK")

    async def get_server_info(self, session_id: str, agent_name: str) -> dict[str, Any]:
        """Get server info for a client."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None or mc.client is None:
            return {}
        result = mc.client.get_server_info()
        return result if result is not None else {}

    async def teardown_session(self, session_id: str) -> int:
        """Tear down all clients in a session. Returns count of clients torn down."""
        clients = self._collect_session_clients(session_id)
        for mc in clients:
            if mc.client is not None:
                try:
                    await mc.client.disconnect()
                except RuntimeError as exc:
                    # anyio cancel scope errors are expected when teardown happens
                    # across different tasks (e.g. server shutdown vs client task)
                    if "cancel scope" in str(exc):
                        log.debug(
                            "Cancel scope mismatch during disconnect %s/%s (safe to ignore)",
                            mc.session_id,
                            mc.agent_name,
                        )
                    else:
                        log.warning(
                            "Error disconnecting client %s/%s: %s",
                            mc.session_id,
                            mc.agent_name,
                            exc,
                            exc_info=True,
                        )
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
