# SDK Integration Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace throwaway ClaudeSDKClient pattern with persistent SDKClientManager service, enabling multi-turn context, token streaming, interrupt, session resume, file checkpointing, dynamic MCP management, and agent team coordination.

**Architecture:** New `SDKClientManager` service on `GatewayRuntime` is the sole interface to `ClaudeSDKClient`. `StreamProcessor` translates SDK `StreamEvent` objects into Corvus protocol events. `run_executor.py` and `background_dispatch.py` stop importing `ClaudeSDKClient` directly and go through the manager. Security stack (`can_use_tool`, hooks, `ConfirmQueue`, audit) is completely unchanged.

**Tech Stack:** Python 3.13, claude-agent-sdk (ClaudeSDKClient, StreamEvent, ClaudeAgentOptions), asyncio, dataclasses, pytest

**Design doc:** `docs/specs/active/2026-03-09-sdk-integration-redesign.md`

---

## Task 1: ManagedClient and AgentClientPool Data Structures

**Files:**
- Create: `corvus/gateway/sdk_client_manager.py`
- Test: `tests/gateway/test_sdk_client_manager.py`

**Step 1: Write the failing test for ManagedClient creation and metric accumulation**

```python
# tests/gateway/test_sdk_client_manager.py
"""Behavioral tests for SDKClientManager — no mocks."""

import time

import pytest

from corvus.gateway.sdk_client_manager import AgentClientPool, ManagedClient


class TestManagedClient:
    def test_initial_metrics_are_zero(self):
        mc = ManagedClient.create_stub(
            session_id="sess-1",
            agent_name="work",
        )
        assert mc.total_tokens == 0
        assert mc.total_cost_usd == 0.0
        assert mc.turn_count == 0
        assert mc.checkpoints == []
        assert mc.sdk_session_id is None
        assert mc.active_run is False
        assert mc.immediate_teardown is False

    def test_accumulate_metrics(self):
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc.accumulate(tokens=1500, cost_usd=0.05, sdk_session_id="sdk-abc")
        assert mc.total_tokens == 1500
        assert mc.total_cost_usd == pytest.approx(0.05)
        assert mc.turn_count == 1
        assert mc.sdk_session_id == "sdk-abc"

        mc.accumulate(tokens=800, cost_usd=0.03, sdk_session_id="sdk-abc")
        assert mc.total_tokens == 2300
        assert mc.total_cost_usd == pytest.approx(0.08)
        assert mc.turn_count == 2

    def test_track_checkpoint(self):
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc.track_checkpoint("msg-uuid-1")
        mc.track_checkpoint("msg-uuid-2")
        assert mc.checkpoints == ["msg-uuid-1", "msg-uuid-2"]


class TestAgentClientPool:
    def test_add_and_get(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        pool.add(mc)
        assert pool.get("work") is mc
        assert pool.get("nonexistent") is None

    def test_remove(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        pool.add(mc)
        removed = pool.remove("work")
        assert removed is mc
        assert pool.get("work") is None

    def test_list_all(self):
        pool = AgentClientPool()
        mc1 = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc2 = ManagedClient.create_stub(session_id="sess-1", agent_name="codex")
        pool.add(mc1)
        pool.add(mc2)
        all_clients = pool.list_all()
        assert len(all_clients) == 2
        names = {c.agent_name for c in all_clients}
        assert names == {"work", "codex"}

    def test_idle_eviction(self):
        pool = AgentClientPool()
        mc_idle = ManagedClient.create_stub(session_id="sess-1", agent_name="idle-agent")
        mc_idle.last_activity = time.monotonic() - 700  # 700s ago
        mc_idle.active_run = False

        mc_active = ManagedClient.create_stub(session_id="sess-1", agent_name="active-agent")
        mc_active.active_run = True
        mc_active.last_activity = time.monotonic() - 700  # old but active

        mc_recent = ManagedClient.create_stub(session_id="sess-1", agent_name="recent-agent")
        mc_recent.last_activity = time.monotonic()  # just used

        pool.add(mc_idle)
        pool.add(mc_active)
        pool.add(mc_recent)

        evicted = pool.collect_idle(timeout=600)
        assert len(evicted) == 1
        assert evicted[0].agent_name == "idle-agent"
        # idle agent removed from pool
        assert pool.get("idle-agent") is None
        # active and recent still there
        assert pool.get("active-agent") is not None
        assert pool.get("recent-agent") is not None

    def test_immediate_teardown_eviction(self):
        pool = AgentClientPool()
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="cron-agent")
        mc.immediate_teardown = True
        mc.active_run = False  # run complete
        pool.add(mc)

        evicted = pool.collect_idle(timeout=600)
        assert len(evicted) == 1
        assert evicted[0].agent_name == "cron-agent"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_sdk_client_manager.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_client_manager_results.log`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.gateway.sdk_client_manager'`

**Step 3: Write minimal implementation**

```python
# corvus/gateway/sdk_client_manager.py
"""SDKClientManager — persistent SDK client lifecycle management.

The sole interface between Corvus and ClaudeSDKClient. No other module
should import or instantiate ClaudeSDKClient directly.

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_sdk_client_manager.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_client_manager_results.log`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/gateway/sdk_client_manager.py tests/gateway/test_sdk_client_manager.py
git commit -m "feat(sdk): add ManagedClient and AgentClientPool data structures"
```

---

## Task 2: SDKClientManager Core — get_or_create, release, teardown

**Files:**
- Modify: `corvus/gateway/sdk_client_manager.py`
- Test: `tests/gateway/test_sdk_client_manager.py`

**Step 1: Write failing tests for SDKClientManager lifecycle**

```python
# Append to tests/gateway/test_sdk_client_manager.py

import asyncio

from corvus.gateway.sdk_client_manager import SDKClientManager


class TestSDKClientManagerLifecycle:
    def test_pool_created_per_session(self):
        mgr = SDKClientManager(runtime=None)
        assert mgr._pools == {}

    def test_get_existing_client(self):
        """If a client already exists for (session, agent), return it."""
        mgr = SDKClientManager(runtime=None)
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mgr._get_pool("sess-1").add(mc)
        result = mgr._get_existing("sess-1", "work")
        assert result is mc
        # last_activity should be updated
        assert result.last_activity >= mc.created_at

    def test_get_existing_returns_none_for_missing(self):
        mgr = SDKClientManager(runtime=None)
        assert mgr._get_existing("sess-1", "work") is None

    def test_release_marks_inactive(self):
        mgr = SDKClientManager(runtime=None)
        mc = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc.active_run = True
        mgr._get_pool("sess-1").add(mc)
        mgr.release("sess-1", "work")
        assert mc.active_run is False

    def test_teardown_session_clears_pool(self):
        mgr = SDKClientManager(runtime=None)
        mc1 = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc2 = ManagedClient.create_stub(session_id="sess-1", agent_name="codex")
        pool = mgr._get_pool("sess-1")
        pool.add(mc1)
        pool.add(mc2)
        teardown_list = mgr._collect_session_clients("sess-1")
        assert len(teardown_list) == 2
        assert "sess-1" not in mgr._pools

    def test_evict_idle_across_all_pools(self):
        mgr = SDKClientManager(runtime=None, idle_timeout=600)
        mc_old = ManagedClient.create_stub(session_id="sess-1", agent_name="old")
        mc_old.last_activity = time.monotonic() - 700
        mgr._get_pool("sess-1").add(mc_old)

        mc_new = ManagedClient.create_stub(session_id="sess-2", agent_name="new")
        mgr._get_pool("sess-2").add(mc_new)

        evicted = mgr._collect_all_idle()
        assert len(evicted) == 1
        assert evicted[0].agent_name == "old"

    def test_list_active_clients(self):
        mgr = SDKClientManager(runtime=None)
        mc1 = ManagedClient.create_stub(session_id="sess-1", agent_name="work")
        mc2 = ManagedClient.create_stub(session_id="sess-2", agent_name="codex")
        mgr._get_pool("sess-1").add(mc1)
        mgr._get_pool("sess-2").add(mc2)
        clients = mgr.list_active_clients()
        assert len(clients) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_sdk_client_manager.py::TestSDKClientManagerLifecycle -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_manager_lifecycle_results.log`
Expected: FAIL — `ImportError: cannot import name 'SDKClientManager'`

**Step 3: Add SDKClientManager to sdk_client_manager.py**

```python
# Append to corvus/gateway/sdk_client_manager.py

import asyncio
import logging

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

logger = logging.getLogger("corvus-gateway.sdk-manager")


@dataclass
class ClientInfo:
    """Summary info for list_active_clients."""
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
    """Sole interface between Corvus and ClaudeSDKClient.

    Manages persistent SDK client pools keyed by (session_id, agent_name).
    All other code goes through this service — never imports ClaudeSDKClient directly.
    """

    def __init__(
        self,
        runtime: Any,  # GatewayRuntime — Any to avoid circular import at init
        *,
        idle_timeout: float = 600.0,
    ) -> None:
        self._runtime = runtime
        self._pools: dict[str, AgentClientPool] = {}
        self._idle_timeout = idle_timeout
        self._eviction_task: asyncio.Task | None = None

    # --- Pool access ---

    def _get_pool(self, session_id: str) -> AgentClientPool:
        if session_id not in self._pools:
            self._pools[session_id] = AgentClientPool()
        return self._pools[session_id]

    def _get_existing(self, session_id: str, agent_name: str) -> ManagedClient | None:
        pool = self._pools.get(session_id)
        if pool is None:
            return None
        mc = pool.get(agent_name)
        if mc is not None:
            mc.last_activity = time.monotonic()
        return mc

    # --- Client lifecycle ---

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

        opts = options_builder()
        # Always inject streaming and checkpointing
        opts.include_partial_messages = True
        opts.enable_file_checkpointing = True

        client = ClaudeSDKClient(options=opts)
        await client.connect()

        mc = ManagedClient(
            client=client,
            session_id=session_id,
            agent_name=agent_name,
            options_snapshot=opts,
            max_turns=opts.max_turns,
            max_budget_usd=opts.max_budget_usd,
            fallback_model=getattr(opts, "fallback_model", None),
            effort=getattr(opts, "effort", None),
        )
        self._get_pool(session_id).add(mc)
        logger.info("Created SDK client session=%s agent=%s", session_id, agent_name)
        return mc

    def release(self, session_id: str, agent_name: str) -> None:
        """Mark client as no longer actively running a query."""
        mc = self._get_existing(session_id, agent_name)
        if mc is not None:
            mc.active_run = False
            mc.last_activity = time.monotonic()

    # --- Conversation ---

    async def query(self, session_id: str, agent_name: str, prompt: str) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is None:
            raise RuntimeError(f"No client for session={session_id} agent={agent_name}")
        mc.active_run = True
        mc.last_activity = time.monotonic()
        await mc.client.query(prompt, session_id=session_id)

    async def receive_response(self, session_id: str, agent_name: str):
        mc = self._get_existing(session_id, agent_name)
        if mc is None:
            raise RuntimeError(f"No client for session={session_id} agent={agent_name}")
        async for message in mc.client.receive_response():
            yield message

    # --- Control ---

    async def interrupt(self, session_id: str, agent_name: str) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            await mc.client.interrupt()

    async def set_model(self, session_id: str, agent_name: str, model: str) -> None:
        """Tear down existing client so next get_or_create uses new model."""
        mc = self._get_existing(session_id, agent_name)
        if mc is None:
            return
        if mc.active_run:
            raise RuntimeError("Cannot switch model during active run")
        if mc.client is not None:
            await mc.client.disconnect()
        pool = self._pools.get(session_id)
        if pool:
            pool.remove(agent_name)
        logger.info("Tore down client for model switch session=%s agent=%s model=%s",
                     session_id, agent_name, model)

    async def set_permission_mode(self, session_id: str, agent_name: str, mode: str) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            await mc.client.set_permission_mode(mode)

    # --- Session persistence ---

    async def resume_sdk_session(
        self,
        session_id: str,
        agent_name: str,
        sdk_session_id: str,
        options_builder: Callable[[], ClaudeAgentOptions],
    ) -> ManagedClient:
        """Resume a previous SDK session by ID."""
        opts = options_builder()
        opts.include_partial_messages = True
        opts.enable_file_checkpointing = True
        opts.resume = sdk_session_id

        client = ClaudeSDKClient(options=opts)
        await client.connect()

        mc = ManagedClient(
            client=client,
            session_id=session_id,
            agent_name=agent_name,
            sdk_session_id=sdk_session_id,
            options_snapshot=opts,
        )
        self._get_pool(session_id).add(mc)
        logger.info("Resumed SDK session=%s agent=%s sdk_session=%s",
                     session_id, agent_name, sdk_session_id)
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

        # Check if Corvus has a stored SDK session ID
        if self._runtime is not None:
            stored_sdk_id = self._runtime.session_mgr.get_sdk_session_id(
                session_id, agent_name,
            )
            if stored_sdk_id:
                try:
                    return await self.resume_sdk_session(
                        session_id, agent_name, stored_sdk_id, options_builder,
                    )
                except Exception:
                    logger.warning(
                        "SDK session resume failed for %s/%s, creating fresh",
                        session_id, agent_name,
                    )

        return await self.get_or_create(session_id, agent_name, options_builder)

    async def fork_session(self, session_id: str, agent_name: str) -> str | None:
        """Fork is handled at options level — return current sdk_session_id for callers."""
        mc = self._get_existing(session_id, agent_name)
        return mc.sdk_session_id if mc else None

    # --- File checkpointing ---

    async def rewind_files(self, session_id: str, agent_name: str, checkpoint_id: str) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            await mc.client.rewind_files(checkpoint_id)

    # --- MCP management ---

    async def get_mcp_status(self, session_id: str, agent_name: str) -> dict:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            return await mc.client.get_mcp_status()
        return {}

    async def add_mcp_server(self, session_id: str, agent_name: str, name: str, config: dict) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            await mc.client.add_mcp_server(name, config)

    async def remove_mcp_server(self, session_id: str, agent_name: str, name: str) -> None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            await mc.client.remove_mcp_server(name)

    # --- Info/diagnostics ---

    async def get_server_info(self, session_id: str, agent_name: str) -> dict | None:
        mc = self._get_existing(session_id, agent_name)
        if mc is not None and mc.client is not None:
            return await mc.client.get_server_info()
        return None

    def list_active_clients(self) -> list[ClientInfo]:
        now = time.monotonic()
        result: list[ClientInfo] = []
        for sid, pool in self._pools.items():
            for mc in pool.list_all():
                result.append(ClientInfo(
                    session_id=mc.session_id,
                    agent_name=mc.agent_name,
                    sdk_session_id=mc.sdk_session_id,
                    active_run=mc.active_run,
                    turn_count=mc.turn_count,
                    total_tokens=mc.total_tokens,
                    total_cost_usd=mc.total_cost_usd,
                    idle_seconds=round(now - mc.last_activity, 1),
                    team_name=mc.team_name,
                ))
        return result

    # --- Teardown ---

    def _collect_session_clients(self, session_id: str) -> list[ManagedClient]:
        pool = self._pools.pop(session_id, None)
        return pool.list_all() if pool else []

    async def teardown_session(self, session_id: str) -> None:
        clients = self._collect_session_clients(session_id)
        for mc in clients:
            if mc.client is not None:
                try:
                    await mc.client.disconnect()
                except Exception:
                    logger.warning("Failed to disconnect client session=%s agent=%s",
                                   session_id, mc.agent_name)
        logger.info("Tore down %d clients for session=%s", len(clients), session_id)

    async def teardown_all(self) -> None:
        all_sessions = list(self._pools.keys())
        for sid in all_sessions:
            await self.teardown_session(sid)
        await self.stop_eviction_loop()

    # --- Idle eviction ---

    def _collect_all_idle(self) -> list[ManagedClient]:
        evicted: list[ManagedClient] = []
        for pool in self._pools.values():
            evicted.extend(pool.collect_idle(timeout=self._idle_timeout))
        # Clean up empty pools
        self._pools = {sid: pool for sid, pool in self._pools.items() if len(pool) > 0}
        return evicted

    async def evict_idle(self) -> int:
        evicted = self._collect_all_idle()
        for mc in evicted:
            if mc.client is not None:
                try:
                    await mc.client.disconnect()
                except Exception:
                    logger.warning("Failed to disconnect idle client agent=%s", mc.agent_name)
        if evicted:
            logger.info("Evicted %d idle SDK clients", len(evicted))
        return len(evicted)

    async def _eviction_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.evict_idle()
            except Exception:
                logger.exception("Idle eviction error")

    async def start_eviction_loop(self, interval: float = 60.0) -> None:
        if self._eviction_task is None:
            self._eviction_task = asyncio.create_task(self._eviction_loop(interval))

    async def stop_eviction_loop(self) -> None:
        if self._eviction_task is not None:
            self._eviction_task.cancel()
            try:
                await self._eviction_task
            except asyncio.CancelledError:
                pass
            self._eviction_task = None
```

Note: The `Callable` import is needed at the top of the file:

```python
from collections.abc import Callable
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_sdk_client_manager.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_manager_lifecycle_results.log`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/gateway/sdk_client_manager.py tests/gateway/test_sdk_client_manager.py
git commit -m "feat(sdk): add SDKClientManager with pool lifecycle management"
```

---

## Task 3: RunContext and RunResult Data Structures

**Files:**
- Create: `corvus/gateway/stream_processor.py`
- Test: `tests/gateway/test_stream_processor.py`

**Step 1: Write the failing test for RunContext and RunResult**

```python
# tests/gateway/test_stream_processor.py
"""Behavioral tests for StreamProcessor — no mocks."""

from corvus.gateway.stream_processor import RunContext, RunResult


class TestRunContext:
    def test_create_with_all_fields(self):
        ctx = RunContext(
            dispatch_id="disp-1",
            run_id="run-1",
            task_id="task-run-1",
            session_id="sess-1",
            turn_id="turn-1",
            agent_name="work",
            model_id="claude-sonnet-4-5",
            route_payload={
                "task_type": "direct",
                "subtask_id": None,
                "skill": None,
                "instruction": "do work",
                "route_index": 0,
            },
        )
        assert ctx.agent_name == "work"
        assert ctx.route_payload["task_type"] == "direct"


class TestRunResult:
    def test_success_result(self):
        result = RunResult(
            status="success",
            tokens_used=1500,
            cost_usd=0.05,
            context_pct=12.5,
            response_text="Hello world",
            sdk_session_id="sdk-abc",
            checkpoints=["msg-1"],
        )
        assert result.status == "success"
        assert result.tokens_used == 1500

    def test_error_result(self):
        result = RunResult(
            status="error",
            tokens_used=0,
            cost_usd=0.0,
            context_pct=0.0,
            response_text="",
            sdk_session_id=None,
            checkpoints=[],
        )
        assert result.status == "error"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_stream_processor.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_stream_processor_results.log`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.gateway.stream_processor'`

**Step 3: Write minimal implementation**

```python
# corvus/gateway/stream_processor.py
"""StreamProcessor — translates SDK stream events into Corvus protocol events.

Handles StreamEvent (token-level), AssistantMessage (complete blocks),
UserMessage (checkpoints), and ResultMessage (final metrics).

Design doc: docs/specs/active/2026-03-09-sdk-integration-redesign.md
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    UserMessage,
)

if TYPE_CHECKING:
    from corvus.gateway.sdk_client_manager import ManagedClient
    from corvus.gateway.session_emitter import SessionEmitter

logger = logging.getLogger("corvus-gateway.stream")


@dataclass
class RunContext:
    """All IDs and metadata a stream processor needs to emit enriched events."""

    dispatch_id: str
    run_id: str
    task_id: str
    session_id: str
    turn_id: str
    agent_name: str
    model_id: str
    route_payload: dict


@dataclass
class RunResult:
    """Outcome of processing a complete response stream."""

    status: str  # "success" | "error" | "interrupted"
    tokens_used: int
    cost_usd: float
    context_pct: float
    response_text: str
    sdk_session_id: str | None
    checkpoints: list[str]


@dataclass
class _ToolUseState:
    """Internal state for tracking an in-progress tool_use block."""

    name: str
    id: str
    input_buffer: str = ""
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_stream_processor.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_stream_processor_results.log`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/gateway/stream_processor.py tests/gateway/test_stream_processor.py
git commit -m "feat(sdk): add RunContext, RunResult, and stream_processor module skeleton"
```

---

## Task 4: StreamProcessor Event Handling

**Files:**
- Modify: `corvus/gateway/stream_processor.py`
- Test: `tests/gateway/test_stream_processor.py`

**Step 1: Write failing tests for StreamEvent handling**

```python
# Append to tests/gateway/test_stream_processor.py

from corvus.gateway.stream_processor import StreamProcessor, _ToolUseState


class TestStreamEventHandling:
    """Test the event dispatch logic using pre-built StreamEvent dicts."""

    def _make_stream_event(self, event_dict: dict, parent_tool_use_id: str | None = None):
        """Build a StreamEvent-like object for testing."""
        return StreamEvent(
            uuid="test-uuid",
            session_id="test-session",
            event=event_dict,
            parent_tool_use_id=parent_tool_use_id,
        )

    def test_text_delta_accumulates(self):
        proc = StreamProcessor._create_for_test()
        event = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello "},
        })
        proc._buffer_stream_event(event)
        assert proc._text_buffer == "Hello "

        event2 = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "world"},
        })
        proc._buffer_stream_event(event2)
        assert proc._text_buffer == "Hello world"

    def test_tool_use_tracking(self):
        proc = StreamProcessor._create_for_test()
        # tool_use start
        start = self._make_stream_event({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Bash", "id": "tool-1"},
        })
        proc._buffer_stream_event(start)
        assert proc._tool_state is not None
        assert proc._tool_state.name == "Bash"

        # tool input delta
        delta = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": '{"command":'},
        })
        proc._buffer_stream_event(delta)
        assert proc._tool_state.input_buffer == '{"command":'

        # tool_use stop
        stop = self._make_stream_event({"type": "content_block_stop"})
        proc._buffer_stream_event(stop)
        assert proc._tool_state is None

    def test_thinking_delta_accumulates(self):
        proc = StreamProcessor._create_for_test()
        start = self._make_stream_event({
            "type": "content_block_start",
            "content_block": {"type": "thinking"},
        })
        proc._buffer_stream_event(start)

        delta = self._make_stream_event({
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "Let me think..."},
        })
        proc._buffer_stream_event(delta)
        assert proc._thinking_buffer == "Let me think..."

    def test_subagent_detection(self):
        proc = StreamProcessor._create_for_test()
        event = self._make_stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "sub"}},
            parent_tool_use_id="parent-tool-1",
        )
        is_sub = event.parent_tool_use_id is not None
        assert is_sub is True

    def test_finalize_result(self):
        proc = StreamProcessor._create_for_test()
        proc._text_buffer = "The answer is 42"
        # Simulate a ResultMessage
        result = proc._build_run_result(
            tokens_input=1000,
            tokens_output=500,
            cost_usd=0.04,
            sdk_session_id="sdk-xyz",
            context_limit=200000,
        )
        assert result.status == "success"
        assert result.tokens_used == 1500
        assert result.cost_usd == 0.04
        assert result.response_text == "The answer is 42"
        assert result.sdk_session_id == "sdk-xyz"
        assert result.context_pct == 0.8  # 1500/200000 * 100
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_stream_processor.py::TestStreamEventHandling -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_stream_events_results.log`
Expected: FAIL — `AttributeError: type object 'StreamProcessor' has no attribute '_create_for_test'`

**Step 3: Add StreamProcessor buffering and finalization methods**

```python
# Append to corvus/gateway/stream_processor.py

class StreamProcessor:
    """Translates SDK stream into Corvus protocol events."""

    def __init__(
        self,
        *,
        emitter: SessionEmitter | None = None,
        managed_client: ManagedClient | None = None,
        context_limit: int = 200000,
    ) -> None:
        self._emitter = emitter
        self._client = managed_client
        self._context_limit = context_limit
        self._text_buffer: str = ""
        self._tool_state: _ToolUseState | None = None
        self._thinking_buffer: str = ""
        self._is_thinking_block: bool = False

    @classmethod
    def _create_for_test(cls) -> StreamProcessor:
        """Create a StreamProcessor without emitter/client for unit testing buffering logic."""
        return cls(emitter=None, managed_client=None)

    def _buffer_stream_event(self, event: StreamEvent) -> dict[str, Any]:
        """Buffer a StreamEvent and return a dict describing what happened.

        This is the pure-logic core that does NOT call emitter. Useful for testing.
        Returns: {"action": "text_delta", "text": "..."} etc.
        """
        raw = event.event
        is_subagent = event.parent_tool_use_id is not None
        event_type = raw.get("type", "")

        if event_type == "content_block_start":
            block = raw.get("content_block", {})
            block_type = block.get("type")
            if block_type == "tool_use":
                self._tool_state = _ToolUseState(
                    name=block.get("name", ""),
                    id=block.get("id", ""),
                )
                return {"action": "tool_start", "tool": self._tool_state.name, "subagent": is_subagent}
            if block_type == "thinking":
                self._is_thinking_block = True
                return {"action": "thinking_start", "subagent": is_subagent}
            if block_type == "text":
                return {"action": "text_start", "subagent": is_subagent}
            return {"action": "block_start", "block_type": block_type}

        if event_type == "content_block_delta":
            delta = raw.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                self._text_buffer += text
                return {"action": "text_delta", "text": text, "subagent": is_subagent}
            if delta_type == "input_json_delta":
                if self._tool_state:
                    self._tool_state.input_buffer += delta.get("partial_json", "")
                return {"action": "tool_input_delta", "subagent": is_subagent}
            if delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                self._thinking_buffer += text
                return {"action": "thinking_delta", "text": text, "subagent": is_subagent}
            return {"action": "unknown_delta", "delta_type": delta_type}

        if event_type == "content_block_stop":
            if self._tool_state:
                tool_name = self._tool_state.name
                tool_input = self._tool_state.input_buffer
                self._tool_state = None
                return {"action": "tool_complete", "tool": tool_name, "input": tool_input}
            if self._is_thinking_block:
                self._is_thinking_block = False
                thinking = self._thinking_buffer
                self._thinking_buffer = ""
                return {"action": "thinking_complete", "text": thinking}
            return {"action": "text_complete"}

        return {"action": "passthrough", "type": event_type}

    def _build_run_result(
        self,
        *,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float,
        sdk_session_id: str | None,
        context_limit: int | None = None,
    ) -> RunResult:
        """Build a RunResult from accumulated state."""
        limit = context_limit or self._context_limit
        tokens_used = tokens_input + tokens_output
        context_pct = round((tokens_used / limit) * 100, 1) if limit > 0 else 0.0
        return RunResult(
            status="success",
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            context_pct=context_pct,
            response_text=self._text_buffer,
            sdk_session_id=sdk_session_id,
            checkpoints=list(self._client.checkpoints) if self._client else [],
        )

    async def process_response(self, ctx: RunContext) -> RunResult:
        """Consume the full response stream, emitting Corvus events as they arrive."""
        if self._client is None or self._client.client is None:
            return RunResult(
                status="error", tokens_used=0, cost_usd=0.0,
                context_pct=0.0, response_text="", sdk_session_id=None, checkpoints=[],
            )

        async for message in self._client.client.receive_response():
            if isinstance(message, StreamEvent):
                action = self._buffer_stream_event(message)
                if self._emitter is not None:
                    await self._emit_action(action, ctx)
            elif isinstance(message, AssistantMessage):
                await self._handle_assistant_message(message, ctx)
            elif isinstance(message, UserMessage):
                if message.uuid:
                    self._client.track_checkpoint(message.uuid)
            elif isinstance(message, ResultMessage):
                usage = getattr(message, "usage", None) or {}
                result = self._build_run_result(
                    tokens_input=int(usage.get("input_tokens", 0)),
                    tokens_output=int(usage.get("output_tokens", 0)),
                    cost_usd=float(getattr(message, "total_cost_usd", 0.0) or 0.0),
                    sdk_session_id=getattr(message, "session_id", None),
                )
                # Update managed client metrics
                self._client.accumulate(
                    tokens=result.tokens_used,
                    cost_usd=result.cost_usd,
                    sdk_session_id=result.sdk_session_id,
                )
                return result

        return RunResult(
            status="error", tokens_used=0, cost_usd=0.0,
            context_pct=0.0, response_text="", sdk_session_id=None, checkpoints=[],
        )

    async def _handle_assistant_message(self, message: AssistantMessage, ctx: RunContext) -> None:
        """Handle complete AssistantMessage — fallback if StreamEvent already handled text."""
        # StreamEvent handles text deltas; this catches any text blocks that
        # StreamEvent missed (e.g., if include_partial_messages is off).
        for block in message.content:
            if isinstance(block, TextBlock) and block.text:
                # Only add to buffer if we didn't already get it via StreamEvent
                if not self._text_buffer.endswith(block.text):
                    self._text_buffer += block.text

    async def _emit_action(self, action: dict[str, Any], ctx: RunContext) -> None:
        """Translate a buffering action into a Corvus emitter event."""
        if self._emitter is None:
            return
        event_type = action.get("action", "")
        payload: dict[str, Any] = {
            "dispatch_id": ctx.dispatch_id,
            "run_id": ctx.run_id,
            "task_id": ctx.task_id,
            "session_id": ctx.session_id,
            "turn_id": ctx.turn_id,
            "agent": ctx.agent_name,
            "model": ctx.model_id,
            **ctx.route_payload,
        }
        if action.get("subagent"):
            payload["subagent"] = True

        if event_type == "text_delta":
            payload["type"] = "text_delta"
            payload["content"] = action["text"]
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "tool_start":
            payload["type"] = "tool_start"
            payload["tool"] = action["tool"]
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "tool_complete":
            payload["type"] = "tool_complete"
            payload["tool"] = action["tool"]
            payload["tool_input"] = action.get("input", "")
            await self._emitter.send(payload, persist=True,
                                      run_id=ctx.run_id, dispatch_id=ctx.dispatch_id, turn_id=ctx.turn_id)
        elif event_type == "thinking_delta":
            payload["type"] = "thinking_delta"
            payload["content"] = action["text"]
            await self._emitter.send(payload)
        elif event_type == "thinking_complete":
            payload["type"] = "thinking_complete"
            await self._emitter.send(payload)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_stream_processor.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_stream_events_results.log`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/gateway/stream_processor.py tests/gateway/test_stream_processor.py
git commit -m "feat(sdk): add StreamProcessor with event buffering and Corvus emission"
```

---

## Task 5: Wire SDKClientManager into GatewayRuntime

**Files:**
- Modify: `corvus/gateway/runtime.py:52-72` (add field to GatewayRuntime)
- Modify: `corvus/gateway/runtime.py:148-245` (add to build_runtime)
- Modify: `corvus/server.py:94-130` (lifespan start/stop)

**Step 1: Add `sdk_client_manager` field to GatewayRuntime**

In `corvus/gateway/runtime.py`, add import at top:
```python
from corvus.gateway.sdk_client_manager import SDKClientManager
```

Add field to `GatewayRuntime` dataclass (after line 72, before `active_connections`):
```python
    sdk_client_manager: SDKClientManager
```

In `build_runtime()` (around line 224), before the `return` statement, add:
```python
    sdk_client_manager = SDKClientManager(runtime=None)  # runtime set after creation
```

And add it to the GatewayRuntime constructor call:
```python
    sdk_client_manager=sdk_client_manager,
```

After the `return` statement, set the runtime back-reference:
```python
    # We need to restructure: build runtime, then set back-reference
```

Actually — because `GatewayRuntime` is a `@dataclass(slots=True)`, we can't set `_runtime` after construction. Instead, pass a sentinel and set it post-construction. Simpler approach: make `SDKClientManager` accept runtime in a `set_runtime()` method:

**Step 2: Add `set_runtime` to SDKClientManager**

In `corvus/gateway/sdk_client_manager.py`, add:
```python
    def set_runtime(self, runtime: Any) -> None:
        """Set runtime back-reference after GatewayRuntime construction."""
        self._runtime = runtime
```

**Step 3: Wire into build_runtime**

At the end of `build_runtime()` in `corvus/gateway/runtime.py`:
```python
    sdk_client_manager = SDKClientManager(runtime=None)

    rt = GatewayRuntime(
        # ... all existing fields ...
        sdk_client_manager=sdk_client_manager,
        active_connections=active_connections,
    )
    sdk_client_manager.set_runtime(rt)
    return rt
```

**Step 4: Wire into server lifespan**

In `corvus/server.py`, in the `lifespan()` function, after scheduler start (line 119):
```python
    await runtime.sdk_client_manager.start_eviction_loop()
    logger.info("SDKClientManager eviction loop started")
```

In the shutdown section (before `await runtime.litellm_manager.stop()`):
```python
    await runtime.sdk_client_manager.teardown_all()
    logger.info("SDKClientManager torn down")
```

**Step 5: Run existing tests to verify no regressions**

Run: `uv run pytest tests/gateway/test_server.py tests/gateway/test_sdk_client_manager.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_runtime_wiring_results.log`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/gateway/runtime.py corvus/gateway/sdk_client_manager.py corvus/server.py
git commit -m "feat(sdk): wire SDKClientManager into GatewayRuntime and server lifespan"
```

---

## Task 6: Update options.py — New SDK Feature Flags

**Files:**
- Modify: `corvus/gateway/options.py:168-243` (build_options)
- Modify: `corvus/gateway/options.py:399-445` (build_backend_options)
- Test: `tests/gateway/test_options_sdk_features.py`

**Step 1: Write failing test**

```python
# tests/gateway/test_options_sdk_features.py
"""Test that build_backend_options injects new SDK features."""

from unittest.mock import MagicMock  # ONLY for creating a fake runtime — NOT for assertions
# Actually — NO MOCKS per project policy. We need a real runtime.
# Use the conftest.py pattern from existing tests.

import pytest

from corvus.gateway.options import build_backend_options


@pytest.fixture
def _minimal_runtime(tmp_path):
    """Build a minimal real runtime for options testing."""
    # Import here to avoid circular issues
    from corvus.gateway.runtime import build_runtime
    # This requires config files to exist — use the test conftest approach
    # For now, test the simpler function that doesn't need full runtime
    pass


class TestSDKFeatureFlags:
    def test_include_partial_messages_flag_exists(self):
        """Verify ClaudeAgentOptions has include_partial_messages field."""
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions()
        assert hasattr(opts, "include_partial_messages")
        opts.include_partial_messages = True
        assert opts.include_partial_messages is True

    def test_enable_file_checkpointing_flag_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions()
        assert hasattr(opts, "enable_file_checkpointing")
        opts.enable_file_checkpointing = True
        assert opts.enable_file_checkpointing is True

    def test_max_turns_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(max_turns=50)
        assert opts.max_turns == 50

    def test_max_budget_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(max_budget_usd=5.0)
        assert opts.max_budget_usd == 5.0

    def test_fallback_model_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(fallback_model="claude-haiku-4-5")
        assert opts.fallback_model == "claude-haiku-4-5"

    def test_effort_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(effort="high")
        assert opts.effort == "high"

    def test_resume_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(resume="session-xyz")
        assert opts.resume == "session-xyz"

    def test_fork_session_field_exists(self):
        from claude_agent_sdk import ClaudeAgentOptions
        opts = ClaudeAgentOptions(fork_session=True)
        assert opts.fork_session is True
```

**Step 2: Run test to verify it passes** (these test SDK capabilities, should pass already)

Run: `uv run pytest tests/gateway/test_options_sdk_features.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_options_sdk_features_results.log`
Expected: All PASS (verifying SDK fields exist)

**Step 3: Commit**

```bash
git add tests/gateway/test_options_sdk_features.py
git commit -m "test(sdk): verify SDK option fields exist for new features"
```

---

## Task 7: Rewire run_executor.py to Use SDKClientManager

**Files:**
- Modify: `corvus/gateway/run_executor.py:15-16` (remove direct SDK imports)
- Modify: `corvus/gateway/run_executor.py:67-78` (add sdk_manager parameter)
- Modify: `corvus/gateway/run_executor.py:279-411` (replace `async with ClaudeSDKClient` block)
- Modify: `corvus/gateway/chat_session.py:193-211` (pass sdk_manager)

This is the **largest single change**. The current code at `run_executor.py:295`:
```python
async with ClaudeSDKClient(options=client_options) as client:
```
becomes:
```python
managed = await sdk_manager.get_or_create(session_id, agent_name, options_builder)
```

**Step 1: Modify run_executor.py imports**

Remove:
```python
from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
```

Add:
```python
from corvus.gateway.sdk_client_manager import SDKClientManager
from corvus.gateway.stream_processor import RunContext, StreamProcessor
```

**Step 2: Add `sdk_manager` parameter to `execute_agent_run`**

At `run_executor.py:67`, add `sdk_manager: SDKClientManager` to the function signature.

**Step 3: Replace the SDK client block**

Replace lines 279-411 (the `build_backend_options` through `receive_response` loop) with:

```python
        def _options_builder() -> ClaudeAgentOptions:
            return build_backend_options(
                runtime=runtime,
                user=user,
                websocket=websocket,
                backend_name=backend_name,
                active_model=active_model,
                agent_name=agent_name,
                ws_callback=_run_hook_ws_callback,
                allow_secret_access=runtime.break_glass.is_active(
                    user=user, session_id=session_id
                ),
                workspace_cwd=workspace_cwd,
                session_id=session_id,
                confirm_queue=confirm_queue,
            )

        managed = await sdk_manager.get_or_create(session_id, agent_name, _options_builder)
        managed.active_run = True

        try:
            await managed.client.set_model(active_model)
        except Exception as exc:
            logger.warning("Failed to set model '%s': %s", active_model, exc)
            # ... error handling stays the same ...

        await emit_phase(turn, run_id=run_id, task_id=task_id, agent=agent_name,
                         route_payload=route_pay, phase="planning", summary="Preparing execution plan")
        await emit_phase(turn, run_id=run_id, task_id=task_id, agent=agent_name,
                         route_payload=route_pay, phase="executing", summary="Agent execution started")

        run_context = RunContext(
            dispatch_id=turn.dispatch_id, run_id=run_id, task_id=task_id,
            session_id=session_id, turn_id=turn.turn_id, agent_name=agent_name,
            model_id=active_model_id, route_payload=route_pay,
        )
        processor = StreamProcessor(
            emitter=emitter, managed_client=managed,
            context_limit=context_limit,
        )

        await sdk_manager.query(session_id, agent_name, run_message)
        result = await processor.process_response(run_context)

        sdk_manager.release(session_id, agent_name)

        # Store SDK session ID for future resume
        if result.sdk_session_id:
            runtime.session_mgr.store_sdk_session_id(
                session_id, agent_name, result.sdk_session_id,
            )

        tokens_used = result.tokens_used
        total_cost = result.cost_usd
        context_pct = result.context_pct
        response_parts = [result.response_text] if result.response_text else []
        assistant_summary = _preview_summary(result.response_text, limit=140) if result.response_text else ""
```

**Step 4: Update ChatSession to pass sdk_manager**

In `corvus/gateway/chat_session.py:193-211`, the `execute_agent_run` method passes `sdk_manager` from `self.runtime.sdk_client_manager`:

```python
    async def execute_agent_run(self, route: TaskRoute, *, route_index: int) -> dict:
        turn = self._current_turn
        assert turn is not None
        return await _execute_run(
            emitter=self.emitter,
            runtime=self.runtime,
            turn=turn,
            route=route,
            route_index=route_index,
            transcript=self.transcript,
            websocket=self.websocket,
            user=self.user,
            confirm_queue=self.confirm_queue,
            sdk_manager=self.runtime.sdk_client_manager,
        )
```

**Step 5: Run existing tests**

Run: `uv run pytest tests/gateway/test_run_executor.py tests/gateway/test_chat_session.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_rewire_executor_results.log`
Expected: PASS (or failures only from tests that create a runtime without sdk_client_manager — fix those)

**Step 6: Commit**

```bash
git add corvus/gateway/run_executor.py corvus/gateway/chat_session.py
git commit -m "feat(sdk): rewire run_executor to use SDKClientManager and StreamProcessor"
```

---

## Task 8: Rewire background_dispatch.py

**Files:**
- Modify: `corvus/gateway/background_dispatch.py:15-16` (remove direct SDK imports)
- Modify: `corvus/gateway/background_dispatch.py:221-459` (_run_route function)

**Step 1: Same pattern as Task 7 but for background dispatch**

Remove:
```python
from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
```

Add:
```python
from corvus.gateway.stream_processor import RunContext, StreamProcessor
```

Replace the `async with ClaudeSDKClient` block (lines 349-384) with `sdk_manager` calls. Key difference: set `managed.immediate_teardown = True` for background dispatches.

```python
        managed = await runtime.sdk_client_manager.get_or_create(
            session_id, route.agent, lambda: client_options,
        )
        managed.immediate_teardown = True
        managed.active_run = True

        run_context = RunContext(
            dispatch_id=dispatch_id, run_id=run_id, task_id=task_id,
            session_id=session_id, turn_id=turn_id, agent_name=route.agent,
            model_id=active_model_id, route_payload=route_payload,
        )
        processor = StreamProcessor(
            emitter=None,  # background dispatch persists events directly
            managed_client=managed,
            context_limit=context_limit,
        )

        await managed.client.set_model(active_model)
        await runtime.sdk_client_manager.query(session_id, route.agent, route_prompt)
        result = await processor.process_response(run_context)
        runtime.sdk_client_manager.release(session_id, route.agent)
```

**Step 2: Run tests**

Run: `uv run pytest tests/gateway/test_dispatch_metrics.py tests/gateway/test_dispatch_orchestrator.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_rewire_dispatch_results.log`
Expected: PASS

**Step 3: Commit**

```bash
git add corvus/gateway/background_dispatch.py
git commit -m "feat(sdk): rewire background_dispatch to use SDKClientManager"
```

---

## Task 9: Wire into TUI InProcessGateway

**Files:**
- Modify: `corvus/tui/protocol/in_process.py:105-198` (send_message)

**Step 1: Update send_message to use sdk_manager**

The TUI's `InProcessGateway.send_message()` currently goes through `ChatSession._execute_dispatch_lifecycle()`, which calls `execute_agent_run()`. Since Task 7 already wired `execute_agent_run` to use `sdk_manager`, this should work automatically.

However, `InProcessGateway.disconnect()` should also call `sdk_manager.teardown_session()`:

```python
    async def disconnect(self) -> None:
        if self._session is not None:
            # Tear down SDK clients for this session
            if self._runtime is not None:
                await self._runtime.sdk_client_manager.teardown_session(self._session.session_id)
            # ... rest of existing cleanup ...
```

**Step 2: Add interrupt support**

```python
    async def cancel_run(self, run_id: str) -> None:
        """Interrupt via SDK client instead of just setting asyncio event."""
        if self._session is not None and self._runtime is not None:
            # Try SDK interrupt first
            agent_name = self._session.transcript.primary_agent()
            if agent_name:
                try:
                    await self._runtime.sdk_client_manager.interrupt(
                        self._session.session_id, agent_name,
                    )
                except Exception:
                    pass
        # Fall back to existing interrupt mechanism
        if self._session is not None and self._session._current_turn is not None:
            self._session._current_turn.dispatch_interrupted.set()
```

**Step 3: Run TUI tests**

Run: `uv run pytest tests/ -k "tui" -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_tui_wiring_results.log`
Expected: PASS

**Step 4: Commit**

```bash
git add corvus/tui/protocol/in_process.py
git commit -m "feat(sdk): wire TUI InProcessGateway to use SDKClientManager for teardown and interrupt"
```

---

## Task 10: Team Foundation — Data Structures and Env Injection

**Files:**
- Modify: `corvus/gateway/sdk_client_manager.py` (add TeamContext, TeamMessage, TeamTask)
- Test: `tests/gateway/test_sdk_team.py`

**Step 1: Write failing tests for team data structures**

```python
# tests/gateway/test_sdk_team.py
"""Team coordination data structure tests."""

from pathlib import Path

from corvus.gateway.sdk_client_manager import TeamContext, TeamMessage, TeamTask


class TestTeamContext:
    def test_create_team_context(self, tmp_path):
        ctx = TeamContext(
            team_name="corvus-team",
            session_id="sess-1",
            members={},
            inbox_dir=tmp_path / "inboxes",
            task_dir=tmp_path / "tasks",
        )
        assert ctx.team_name == "corvus-team"
        assert ctx.members == {}


class TestTeamMessage:
    def test_create_message(self):
        msg = TeamMessage(
            from_agent="codex",
            to_agent="work",
            text="Found 3 security issues",
            summary="Security review results",
            timestamp="2026-03-09T12:00:00Z",
            read=False,
            message_type="message",
        )
        assert msg.from_agent == "codex"
        assert msg.message_type == "message"

    def test_broadcast_message(self):
        msg = TeamMessage(
            from_agent="lead",
            to_agent=None,
            text="Starting review phase",
            summary="Phase start",
            timestamp="2026-03-09T12:00:00Z",
            read=False,
            message_type="broadcast",
        )
        assert msg.to_agent is None


class TestTeamTask:
    def test_create_task(self):
        task = TeamTask(
            id="1",
            subject="Review auth module",
            description="Look for SQL injection and XSS",
            status="pending",
            owner=None,
            blocked_by=[],
        )
        assert task.status == "pending"
        assert task.blocked_by == []

    def test_task_with_dependencies(self):
        task = TeamTask(
            id="2",
            subject="Deploy fixes",
            description="Deploy after review",
            status="pending",
            owner="work",
            blocked_by=["1"],
        )
        assert task.blocked_by == ["1"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_sdk_team.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_team_results.log`
Expected: FAIL — `ImportError: cannot import name 'TeamContext'`

**Step 3: Add team dataclasses to sdk_client_manager.py**

```python
# Add to corvus/gateway/sdk_client_manager.py

from pathlib import Path

@dataclass
class TeamContext:
    """Metadata for an active agent team."""
    team_name: str
    session_id: str
    members: dict[str, ManagedClient]
    inbox_dir: Path
    task_dir: Path
    created_at: float = field(default_factory=time.monotonic)
    inbox_monitor_task: asyncio.Task | None = field(default=None, repr=False)


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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_sdk_team.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_team_results.log`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/gateway/sdk_client_manager.py tests/gateway/test_sdk_team.py
git commit -m "feat(sdk): add team coordination data structures (TeamContext, TeamMessage, TeamTask)"
```

---

## Task 11: Add sdk_session_id Storage to SessionManager

**Files:**
- Modify: `corvus/session_manager.py` (add store/get methods for sdk_session_id)
- Test: `tests/gateway/test_session_manager.py` (add test)

**Step 1: Write failing test**

```python
# Append to tests/gateway/test_session_manager.py or create new test file

def test_store_and_get_sdk_session_id(tmp_path):
    from corvus.session_manager import SessionManager
    db_path = tmp_path / "test.db"
    mgr = SessionManager(db_path=db_path)

    # Store
    mgr.store_sdk_session_id("sess-1", "work", "sdk-abc-123")
    # Get
    result = mgr.get_sdk_session_id("sess-1", "work")
    assert result == "sdk-abc-123"

    # Overwrite
    mgr.store_sdk_session_id("sess-1", "work", "sdk-xyz-789")
    result = mgr.get_sdk_session_id("sess-1", "work")
    assert result == "sdk-xyz-789"

    # Missing
    result = mgr.get_sdk_session_id("sess-1", "nonexistent")
    assert result is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/gateway/test_session_manager.py::test_store_and_get_sdk_session_id -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_session_id_results.log`
Expected: FAIL — `AttributeError: 'SessionManager' object has no attribute 'store_sdk_session_id'`

**Step 3: Add methods to SessionManager**

Add a new table for SDK session mapping and two methods. Check `corvus/session_manager.py` for the existing schema pattern and add:

```python
    def _ensure_sdk_sessions_table(self) -> None:
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS sdk_sessions (
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                sdk_session_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, agent_name)
            )
        """)

    def store_sdk_session_id(self, session_id: str, agent_name: str, sdk_session_id: str) -> None:
        self._ensure_sdk_sessions_table()
        self._db.execute(
            """INSERT OR REPLACE INTO sdk_sessions (session_id, agent_name, sdk_session_id, updated_at)
               VALUES (?, ?, ?, ?)""",
            (session_id, agent_name, sdk_session_id, datetime.now(UTC).isoformat()),
        )

    def get_sdk_session_id(self, session_id: str, agent_name: str) -> str | None:
        self._ensure_sdk_sessions_table()
        row = self._db.execute(
            "SELECT sdk_session_id FROM sdk_sessions WHERE session_id = ? AND agent_name = ?",
            (session_id, agent_name),
        ).fetchone()
        return row[0] if row else None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gateway/test_session_manager.py::test_store_and_get_sdk_session_id -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_session_id_results.log`
Expected: PASS

**Step 5: Commit**

```bash
git add corvus/session_manager.py tests/gateway/test_session_manager.py
git commit -m "feat(sdk): add SDK session ID storage to SessionManager for resume support"
```

---

## Task 12: Update WebSocket chat.py for SDK Interrupt

**Files:**
- Modify: `corvus/api/chat.py:328-331` (interrupt handling)

**Step 1: Wire interrupt through sdk_manager**

In `corvus/api/chat.py`, the interrupt handler currently just emits an event. Add SDK interrupt:

```python
            if msg.get("type") == "interrupt":
                logger.info("User interrupted session %s", self.session_id)
                # Interrupt via SDK client
                agent_name = session.transcript.primary_agent()
                if agent_name:
                    try:
                        await runtime.sdk_client_manager.interrupt(session_id, agent_name)
                    except Exception:
                        logger.warning("SDK interrupt failed for %s/%s", session_id, agent_name)
                await runtime.emitter.emit("session_interrupt", user=user, session_id=session_id)
                continue
```

Note: This is inside `ChatSession.run()` in `chat_session.py`, not directly in `chat.py`. The interrupt is handled at `chat_session.py:328-331`. Update there.

**Step 2: Commit**

```bash
git add corvus/gateway/chat_session.py
git commit -m "feat(sdk): wire interrupt through SDKClientManager in chat session"
```

---

## Task 13: Full Integration Test — Real SDK Subprocess

**Files:**
- Create: `tests/gateway/test_sdk_integration.py`

**Step 1: Write integration test that creates a real SDK client**

```python
# tests/gateway/test_sdk_integration.py
"""Integration tests using real ClaudeSDKClient subprocesses.

These tests require ANTHROPIC_API_KEY to be set and will make real API calls.
Mark with pytest.mark.integration so they can be skipped in CI.
"""

import os

import pytest

from corvus.gateway.sdk_client_manager import ManagedClient, SDKClientManager

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping SDK integration tests",
)


@pytest.mark.asyncio
async def test_persistent_context_across_queries():
    """Two queries to the same client — second should reference first."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    opts = ClaudeAgentOptions(
        allowed_tools=[],
        permission_mode="plan",  # read-only, no tool execution
        max_turns=1,
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Remember this number: 42")
        first_response = ""
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        first_response += block.text

        await client.query("What number did I ask you to remember?")
        second_response = ""
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        second_response += block.text

        assert "42" in second_response, f"Expected '42' in response, got: {second_response}"


@pytest.mark.asyncio
async def test_stream_events_with_partial_messages():
    """Verify StreamEvent objects arrive when include_partial_messages=True."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from claude_agent_sdk.types import StreamEvent

    opts = ClaudeAgentOptions(
        include_partial_messages=True,
        allowed_tools=[],
        permission_mode="plan",
        max_turns=1,
    )
    stream_events_seen = False
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Say hello")
        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                stream_events_seen = True

    assert stream_events_seen, "Expected StreamEvent objects with include_partial_messages=True"


@pytest.mark.asyncio
async def test_sdk_client_manager_lifecycle():
    """Full lifecycle through SDKClientManager."""
    from claude_agent_sdk import ClaudeAgentOptions

    mgr = SDKClientManager(runtime=None)

    def builder():
        return ClaudeAgentOptions(
            allowed_tools=[],
            permission_mode="plan",
            max_turns=1,
        )

    mc = await mgr.get_or_create("test-sess", "test-agent", builder)
    assert mc.client is not None
    assert mc.agent_name == "test-agent"

    # Second call should return same client
    mc2 = await mgr.get_or_create("test-sess", "test-agent", builder)
    assert mc2 is mc

    # Teardown
    await mgr.teardown_session("test-sess")
    assert mgr.list_active_clients() == []
```

**Step 2: Run integration tests**

Run: `uv run pytest tests/gateway/test_sdk_integration.py -v --timeout=60 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_sdk_integration_results.log`
Expected: PASS (or SKIP if no API key)

**Step 3: Commit**

```bash
git add tests/gateway/test_sdk_integration.py
git commit -m "test(sdk): add integration tests for persistent context, streaming, and manager lifecycle"
```

---

## Task 14: Run Full Test Suite and Fix Regressions

**Step 1: Run the full test suite**

Run: `uv run pytest tests/gateway/ -v --timeout=120 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_full_suite_results.log`

**Step 2: Fix any import errors or missing fields**

Common issues to watch for:
- Tests that construct `GatewayRuntime` without `sdk_client_manager` field
- Tests that import `ClaudeSDKClient` from `run_executor` or `background_dispatch`
- Tests that rely on the old `async with ClaudeSDKClient` pattern

**Step 3: Run ruff**

Run: `uv run ruff check corvus/gateway/sdk_client_manager.py corvus/gateway/stream_processor.py corvus/gateway/run_executor.py corvus/gateway/background_dispatch.py --fix`

**Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix(sdk): resolve regressions from SDK integration rewiring"
```

---

## Summary

| Task | Component | New Files | Modified Files |
|------|-----------|-----------|----------------|
| 1 | ManagedClient + AgentClientPool | `sdk_client_manager.py`, `test_sdk_client_manager.py` | — |
| 2 | SDKClientManager core | — | `sdk_client_manager.py`, `test_sdk_client_manager.py` |
| 3 | RunContext + RunResult | `stream_processor.py`, `test_stream_processor.py` | — |
| 4 | StreamProcessor event handling | — | `stream_processor.py`, `test_stream_processor.py` |
| 5 | GatewayRuntime wiring | — | `runtime.py`, `server.py`, `sdk_client_manager.py` |
| 6 | SDK feature flag verification | `test_options_sdk_features.py` | — |
| 7 | Rewire run_executor | — | `run_executor.py`, `chat_session.py` |
| 8 | Rewire background_dispatch | — | `background_dispatch.py` |
| 9 | TUI InProcessGateway | — | `in_process.py` |
| 10 | Team data structures | `test_sdk_team.py` | `sdk_client_manager.py` |
| 11 | SDK session ID storage | — | `session_manager.py`, `test_session_manager.py` |
| 12 | WebSocket interrupt | — | `chat_session.py` |
| 13 | Integration tests | `test_sdk_integration.py` | — |
| 14 | Full suite regression fix | — | Various |
