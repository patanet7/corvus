# Security, Cleanup & Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the confirm gate to actually block tool execution until user approval, clean personal data for open-source readiness, and add behavioral tests proving hub-driven tool isolation works.

**Architecture:** The confirm gate uses the SDK's `can_use_tool` callback to block gated tools via an `asyncio.Event` that awaits user WebSocket response. Tool modularity tests exercise real `CapabilitiesRegistry.resolve()` and `evaluate_tool_permission()` against real agent YAML specs. Personal data cleanup is a targeted edit to `CLAUDE.md`.

**Tech Stack:** Python 3.11+, FastAPI, claude_agent_sdk, pytest, asyncio

---

## Stream 1: Confirm Gate Wiring (P0 Security)

### Task 1: Write test proving confirm gate is currently broken

**Files:**
- Create: `tests/gateway/test_confirm_gate.py`

**Step 1: Write the test**

```python
"""Behavioral tests for confirm-gating: gated tools must block until user approves."""

import asyncio

import pytest

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.permissions import evaluate_tool_permission, expand_confirm_gated_tools


class TestConfirmGateDecision:
    """Verify permission evaluation marks gated tools as 'confirm' (not 'allow')."""

    @staticmethod
    def _registry() -> CapabilitiesRegistry:
        reg = CapabilitiesRegistry()
        entry = next(m for m in TOOL_MODULE_DEFS if m.name == "paperless")
        reg.register("paperless", entry)
        return reg

    @staticmethod
    def _spec() -> AgentSpec:
        return AgentSpec(
            name="docs",
            description="docs agent",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"paperless": {"enabled": True}},
                confirm_gated=["paperless.tag"],
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )

    def test_gated_tool_decision_is_confirm(self) -> None:
        """A confirm-gated tool should get state='confirm', allowed=True."""
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=self._spec(),
            capabilities=self._registry(),
            tool_name="mcp__paperless_docs__paperless_tag",
        )
        assert decision.state == "confirm"
        assert decision.allowed is True

    def test_non_gated_tool_decision_is_allow(self) -> None:
        """A non-gated tool should get state='allow', allowed=True."""
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=self._spec(),
            capabilities=self._registry(),
            tool_name="mcp__paperless_docs__paperless_search",
        )
        assert decision.state == "allow"
        assert decision.allowed is True


class TestConfirmGateBlocking:
    """Verify that can_use_tool blocks on confirm-gated tools until user responds."""

    @staticmethod
    def _registry() -> CapabilitiesRegistry:
        reg = CapabilitiesRegistry()
        entry = next(m for m in TOOL_MODULE_DEFS if m.name == "paperless")
        reg.register("paperless", entry)
        return reg

    @staticmethod
    def _spec() -> AgentSpec:
        return AgentSpec(
            name="docs",
            description="docs agent",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"paperless": {"enabled": True}},
                confirm_gated=["paperless.tag"],
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )

    @pytest.mark.asyncio
    async def test_gated_tool_blocks_until_approved(self) -> None:
        """can_use_tool must not return Allow immediately for gated tools.

        It should block until user approval arrives via the confirm queue.
        """
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        # Start the permission check — it should block
        task = asyncio.create_task(
            queue.wait_for_confirmation(tool_name, timeout_s=2.0)
        )

        # Simulate brief delay then user approves
        await asyncio.sleep(0.05)
        queue.respond(tool_name, approved=True)

        result = await task
        assert result is True

    @pytest.mark.asyncio
    async def test_gated_tool_denied_by_user(self) -> None:
        """User denies a gated tool — should return False."""
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        task = asyncio.create_task(
            queue.wait_for_confirmation(tool_name, timeout_s=2.0)
        )
        await asyncio.sleep(0.05)
        queue.respond(tool_name, approved=False)

        result = await task
        assert result is False

    @pytest.mark.asyncio
    async def test_gated_tool_times_out(self) -> None:
        """No user response within timeout — should return False (deny)."""
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        result = await queue.wait_for_confirmation(tool_name, timeout_s=0.1)
        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/gateway/test_confirm_gate.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_confirm_gate_results.log | tail -20`
Expected: FAIL — `corvus.gateway.confirm_queue` module not found

**Step 3: Commit test**

```bash
git add tests/gateway/test_confirm_gate.py
git commit -m "test: add failing tests for confirm gate blocking behavior"
```

---

### Task 2: Implement ConfirmQueue

**Files:**
- Create: `corvus/gateway/confirm_queue.py`

**Step 1: Write the ConfirmQueue**

```python
"""Async confirmation queue for gated tool calls.

When a tool is confirm-gated, the runtime blocks execution and sends a
confirm_request to the frontend via WebSocket. The frontend shows a
confirmation dialog. When the user responds, the response is fed into
this queue, unblocking the waiting coroutine.
"""

import asyncio
import logging

logger = logging.getLogger("corvus-gateway")


class ConfirmQueue:
    """Manages pending confirmation requests keyed by tool call ID."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def wait_for_confirmation(
        self,
        call_id: str,
        *,
        timeout_s: float = 60.0,
    ) -> bool:
        """Block until user responds or timeout expires.

        Returns True if approved, False if denied or timed out.
        """
        if call_id in self._pending:
            logger.warning("Duplicate confirm request for call_id=%s", call_id)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[call_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("Confirm gate timed out for call_id=%s", call_id)
            return False
        finally:
            self._pending.pop(call_id, None)

    def respond(self, call_id: str, *, approved: bool) -> None:
        """Deliver user's confirm/deny response to the waiting coroutine."""
        future = self._pending.get(call_id)
        if future is None:
            logger.warning("Confirm response for unknown call_id=%s (expired?)", call_id)
            return
        if future.done():
            logger.warning("Confirm response for already-resolved call_id=%s", call_id)
            return
        future.set_result(approved)

    def cancel_all(self) -> None:
        """Cancel all pending confirmations (e.g., on session close)."""
        for call_id, future in self._pending.items():
            if not future.done():
                future.set_result(False)
                logger.info("Cancelled pending confirm for call_id=%s", call_id)
        self._pending.clear()
```

**Step 2: Run tests to verify they pass**

Run: `uv run python -m pytest tests/gateway/test_confirm_gate.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_confirm_gate_results.log | tail -20`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add corvus/gateway/confirm_queue.py
git commit -m "feat: add ConfirmQueue for async confirm-gate blocking"
```

---

### Task 3: Wire ConfirmQueue into can_use_tool

**Files:**
- Modify: `corvus/gateway/options.py:266-321` — `_build_can_use_tool()`
- Modify: `corvus/gateway/options.py:171-244` — `build_options()`

**Step 1: Add confirm_queue parameter to `_build_can_use_tool`**

In `corvus/gateway/options.py`, update `_build_can_use_tool` to accept and use a `ConfirmQueue`:

```python
from corvus.gateway.confirm_queue import ConfirmQueue

def _build_can_use_tool(
    *,
    runtime: GatewayRuntime,
    agent_name: str | None,
    allow_secret_access: bool,
    ws_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    confirm_queue: ConfirmQueue | None = None,
) -> Callable[...] | None:
```

**Step 2: In the inner `_can_use_tool`, block on confirm state**

Replace the current allow-all-confirmed logic:

```python
        if decision.allowed:
            return PermissionResultAllow()
```

With:

```python
        if decision.allowed and decision.state == "confirm":
            # Gated tool — send confirm request via WS, then block
            call_id = tool_name  # Use tool_name as call_id for correlation
            if ws_callback is not None:
                await ws_callback(
                    {
                        "type": "confirm_request",
                        "tool": tool_name,
                        "params": tool_input,
                        "call_id": call_id,
                        "timeout_s": 60,
                    }
                )
            if confirm_queue is not None:
                approved = await confirm_queue.wait_for_confirmation(call_id)
                if approved:
                    return PermissionResultAllow()
                return PermissionResultDeny(
                    message=f"User denied tool '{tool_name}'.",
                    interrupt=False,
                )
            # No confirm queue — fall through to allow (break-glass / no WS)
            return PermissionResultAllow()
        if decision.allowed:
            return PermissionResultAllow()
```

**Step 3: Pass confirm_queue through build_options**

Add `confirm_queue` parameter to `build_options()` and pass it to `_build_can_use_tool()`.

**Step 4: Commit**

```bash
git add corvus/gateway/options.py
git commit -m "feat: wire ConfirmQueue into can_use_tool for gated tool blocking"
```

---

### Task 4: Wire ConfirmQueue into ChatSession

**Files:**
- Modify: `corvus/gateway/chat_session.py` — add confirm_queue to session, wire confirm_response

**Step 1: Add ConfirmQueue to ChatSession.__init__**

```python
from corvus.gateway.confirm_queue import ConfirmQueue

class ChatSession:
    def __init__(self, ...):
        ...
        self.confirm_queue = ConfirmQueue()
```

**Step 2: Pass confirm_queue when building options**

Where `build_options()` is called in ChatSession (likely in the execute method), pass `confirm_queue=self.confirm_queue`.

**Step 3: Wire the confirm_response message handler**

Replace the TODO at line 1389:

```python
            if msg.get("type") == "confirm_response":
                call_id = msg.get("tool_call_id")
                approved = msg.get("approved", False)
                logger.info("Confirm response: call_id=%s approved=%s", call_id, approved)
                await self.send(
                    {
                        "type": "confirm_response",
                        "tool_call_id": call_id,
                        "approved": bool(approved),
                    },
                    persist=True,
                )
                # Feed response to the waiting can_use_tool coroutine
                self.confirm_queue.respond(call_id, approved=bool(approved))
                continue
```

**Step 4: Cancel pending confirms on session close**

In the session's cleanup/disconnect handler:

```python
self.confirm_queue.cancel_all()
```

**Step 5: Run all tests**

Run: `uv run python -m pytest tests/gateway/ -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_confirm_gate_wiring_results.log | tail -30`
Expected: All pass

**Step 6: Commit**

```bash
git add corvus/gateway/chat_session.py
git commit -m "feat: wire confirm_response to ConfirmQueue in ChatSession

Gated tools now block in can_use_tool until user approves or denies via
WebSocket. Removes the 'TODO: Wire to SDK confirm gate' comment."
```

---

### Task 5: Remove duplicate confirm-gate logic from hooks.py

**Files:**
- Modify: `corvus/hooks.py:107-120`

**Step 1: Remove the confirm-gating block from pre_tool_use**

The `pre_tool_use` hook currently sends a duplicate `confirm_request` and returns `{"decision": "confirm"}`. Since `can_use_tool` now handles confirm-gating (sending the WS message and blocking), remove this from the hook:

```python
        # Confirm-gating is handled by can_use_tool callback (options.py).
        # Hooks only handle security blocks (Bash/Read safety).
```

Delete lines 107-120 (the `if tool_name in gated_tools:` block). Keep the `gated_tools` parameter in `create_hooks` for backward compat but remove its usage in `pre_tool_use`.

**Step 2: Update tests**

Run: `uv run python -m pytest tests/gateway/test_hooks.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_hooks_results.log | tail -20`

Fix any tests that asserted on the old `{"decision": "confirm"}` return.

**Step 3: Commit**

```bash
git add corvus/hooks.py tests/gateway/test_hooks.py
git commit -m "refactor: remove confirm-gate from hooks.py

Confirm-gating now handled exclusively by can_use_tool callback in
options.py via ConfirmQueue. Hooks focus on security blocks only."
```

---

## Stream 2: Personal Data Cleanup

### Task 6: Remove personal data from CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:125-128`

**Step 1: Replace the Forgejo push example**

Replace:
```
GIT_SSH_COMMAND="ssh -o ProxyCommand='ssh -W localhost:2222 patanet7@100.116.213.55'" git push forgejo main
```

With:
```
GIT_SSH_COMMAND="ssh -o ProxyCommand='ssh -W localhost:2222 <user>@<tailscale-ip>'" git push forgejo main
```

**Step 2: Verify no other personal data in tracked files**

Run:
```bash
git grep -n 'patanet7\|absolvbass\|192\.168\.1\.\|100\.116\.\|100\.104\.\|100\.79\.' -- ':!docs/plans/' ':!.venv/'
```

Expected: Only the Storybook mock IP (`192.168.1.45` in `TaskRunCard.stories.ts`) which is fine — it's fake test data.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: remove personal data from CLAUDE.md for open-source readiness"
```

---

## Stream 3: Tool Modularity & Isolation Tests

### Task 7: Test YAML spec → resolved tool set

**Files:**
- Create: `tests/gateway/test_tool_modularity.py`

**Step 1: Write tests that exercise real YAML specs against real CapabilitiesRegistry**

```python
"""Behavioral tests for hub-driven tool modularity.

Exercises the full chain: YAML agent spec → AgentRegistry → CapabilitiesRegistry.resolve()
→ verify each agent gets exactly the tools declared in their spec, no more, no less.

NO mocks. Real YAML files. Real registry instances.
"""

from pathlib import Path

from corvus.agents.registry import AgentRegistry
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry


AGENTS_DIR = Path(__file__).parent.parent.parent / "config" / "agents"


def _full_registry() -> CapabilitiesRegistry:
    """Build a CapabilitiesRegistry with all known tool modules."""
    reg = CapabilitiesRegistry()
    for module_def in TOOL_MODULE_DEFS:
        reg.register(module_def.name, module_def)
    return reg


def _agent_registry() -> AgentRegistry:
    """Load the real agent YAML specs."""
    reg = AgentRegistry(config_dir=AGENTS_DIR)
    reg.load()
    return reg


class TestYAMLSpecToResolvedTools:
    """Each agent's YAML spec should resolve to exactly its declared modules."""

    def test_finance_agent_gets_only_firefly(self) -> None:
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("finance")
        assert spec is not None
        resolved = caps.resolve(spec, skip_modules=frozenset({"memory"}))
        assert "firefly" in resolved.available_modules or "firefly" in resolved.unavailable_modules
        # Finance should NOT have paperless, drive, ha, email, etc.
        for module in ["paperless", "drive", "ha", "email"]:
            assert module not in resolved.available_modules

    def test_docs_agent_gets_paperless_and_drive(self) -> None:
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("docs")
        assert spec is not None
        resolved = caps.resolve(spec, skip_modules=frozenset({"memory"}))
        requested = set(spec.tools.modules.keys()) - {"memory"}
        for module in requested:
            assert module in resolved.available_modules or module in resolved.unavailable_modules
        # Docs should NOT have firefly, ha, email
        for module in ["firefly", "ha", "email"]:
            assert module not in resolved.available_modules

    def test_home_agent_gets_ha(self) -> None:
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("home")
        assert spec is not None
        resolved = caps.resolve(spec, skip_modules=frozenset({"memory"}))
        assert "ha" in resolved.available_modules or "ha" in resolved.unavailable_modules
        for module in ["firefly", "paperless", "drive"]:
            assert module not in resolved.available_modules

    def test_general_agent_has_no_domain_modules(self) -> None:
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("general")
        assert spec is not None
        resolved = caps.resolve(spec, skip_modules=frozenset({"memory"}))
        # General should have no domain-specific modules
        assert len(resolved.available_modules) == 0 or all(
            m in resolved.unavailable_modules for m in resolved.available_modules
        )

    def test_all_agents_load_without_error(self) -> None:
        """Every YAML spec must parse and be resolvable."""
        agents = _agent_registry()
        caps = _full_registry()
        for spec in agents.list_all():
            resolved = caps.resolve(spec, skip_modules=frozenset({"memory"}))
            # Should not raise
            assert isinstance(resolved.available_modules, list)
            assert isinstance(resolved.unavailable_modules, dict)
```

**Step 2: Run tests**

Run: `uv run python -m pytest tests/gateway/test_tool_modularity.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_tool_modularity_results.log | tail -20`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/gateway/test_tool_modularity.py
git commit -m "test: add tool modularity tests — YAML spec to resolved tool set"
```

---

### Task 8: Test confirm-gated expansion per agent

**Files:**
- Modify: `tests/gateway/test_tool_modularity.py`

**Step 1: Add confirm-gated expansion tests**

```python
from corvus.permissions import expand_confirm_gated_tools


class TestConfirmGatedExpansion:
    """Verify confirm_gated short names expand to full MCP tool names."""

    def test_finance_gated_tools(self) -> None:
        agents = _agent_registry()
        spec = agents.get("finance")
        assert spec is not None
        expanded = expand_confirm_gated_tools("finance", spec.tools.confirm_gated)
        assert "firefly.create_transaction" in expanded
        assert "mcp__firefly_finance__firefly_create_transaction" in expanded

    def test_docs_gated_tools(self) -> None:
        agents = _agent_registry()
        spec = agents.get("docs")
        assert spec is not None
        expanded = expand_confirm_gated_tools("docs", spec.tools.confirm_gated)
        assert "paperless.tag" in expanded
        assert "drive.delete" in expanded
        assert "mcp__paperless_docs__paperless_tag" in expanded
        assert "mcp__drive_docs__drive_delete" in expanded

    def test_home_gated_tools(self) -> None:
        agents = _agent_registry()
        spec = agents.get("home")
        assert spec is not None
        expanded = expand_confirm_gated_tools("home", spec.tools.confirm_gated)
        assert "ha.call_service" in expanded
        assert "mcp__ha_home__ha_call_service" in expanded

    def test_general_has_no_gated_tools(self) -> None:
        agents = _agent_registry()
        spec = agents.get("general")
        assert spec is not None
        expanded = expand_confirm_gated_tools("general", spec.tools.confirm_gated)
        assert len(expanded) == 0
```

**Step 2: Run tests**

Run: `uv run python -m pytest tests/gateway/test_tool_modularity.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_confirm_expansion_results.log | tail -20`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/gateway/test_tool_modularity.py
git commit -m "test: add confirm-gated expansion tests per agent YAML spec"
```

---

### Task 9: Test cross-agent tool isolation

**Files:**
- Modify: `tests/gateway/test_tool_modularity.py`

**Step 1: Add cross-agent isolation tests**

```python
from corvus.permissions import evaluate_tool_permission


class TestCrossAgentIsolation:
    """Prove agent A cannot access tools assigned only to agent B."""

    def test_finance_cannot_use_paperless(self) -> None:
        """Finance agent must be denied access to paperless tools."""
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("finance")
        assert spec is not None
        decision = evaluate_tool_permission(
            agent_name="finance",
            spec=spec,
            capabilities=caps,
            tool_name="mcp__paperless_finance__paperless_search",
        )
        assert decision.allowed is False
        assert decision.state == "deny"

    def test_docs_cannot_use_firefly(self) -> None:
        """Docs agent must be denied access to firefly tools."""
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("docs")
        assert spec is not None
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=spec,
            capabilities=caps,
            tool_name="mcp__firefly_docs__firefly_create_transaction",
        )
        assert decision.allowed is False
        assert decision.state == "deny"

    def test_home_cannot_use_drive(self) -> None:
        """Home agent must be denied access to drive tools."""
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("home")
        assert spec is not None
        decision = evaluate_tool_permission(
            agent_name="home",
            spec=spec,
            capabilities=caps,
            tool_name="mcp__drive_home__drive_delete",
        )
        assert decision.allowed is False
        assert decision.state == "deny"

    def test_memory_cross_agent_blocked(self) -> None:
        """Agent A must not access Agent B's memory server."""
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("finance")
        assert spec is not None
        decision = evaluate_tool_permission(
            agent_name="finance",
            spec=spec,
            capabilities=caps,
            tool_name="mcp__memory_docs__memory_search",
        )
        assert decision.allowed is False
        assert decision.state == "deny"
        assert "cross-agent" in decision.reason.lower() or "does not match" in decision.reason.lower()

    def test_agent_can_access_own_memory(self) -> None:
        """Agent must be allowed to access its own memory server."""
        agents = _agent_registry()
        caps = _full_registry()
        spec = agents.get("finance")
        assert spec is not None
        decision = evaluate_tool_permission(
            agent_name="finance",
            spec=spec,
            capabilities=caps,
            tool_name="mcp__memory_finance__memory_search",
        )
        assert decision.allowed is True
```

**Step 2: Run tests**

Run: `uv run python -m pytest tests/gateway/test_tool_modularity.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_isolation_results.log | tail -20`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/gateway/test_tool_modularity.py
git commit -m "test: add cross-agent tool isolation tests

Proves finance can't use paperless, docs can't use firefly, home can't
use drive, and cross-agent memory access is blocked."
```

---

### Task 10: Test prompt layer isolation

**Files:**
- Modify: `tests/gateway/test_tool_modularity.py`

**Step 1: Add prompt isolation tests**

```python
class TestPromptIsolation:
    """Each agent gets its own prompt file, not another agent's."""

    def test_each_agent_has_own_prompt_file(self) -> None:
        agents = _agent_registry()
        for spec in agents.list_all():
            if spec.prompt_file:
                assert spec.name in spec.prompt_file or spec.name == "huginn", (
                    f"Agent '{spec.name}' references prompt file '{spec.prompt_file}' "
                    "which doesn't contain its own name"
                )

    def test_each_agent_has_own_domain(self) -> None:
        agents = _agent_registry()
        domains_seen: dict[str, str] = {}
        for spec in agents.list_all():
            if spec.name in ("general", "huginn"):
                continue  # Router and general don't have own domains
            domain = spec.memory.own_domain
            if domain in domains_seen:
                assert False, (
                    f"Domain '{domain}' claimed by both '{domains_seen[domain]}' "
                    f"and '{spec.name}'"
                )
            domains_seen[domain] = spec.name
```

**Step 2: Run tests**

Run: `uv run python -m pytest tests/gateway/test_tool_modularity.py -v 2>&1 | tee tests/output/gateway/$(date +%Y%m%d_%H%M%S)_test_prompt_isolation_results.log | tail -20`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/gateway/test_tool_modularity.py
git commit -m "test: add prompt and domain isolation tests"
```

---

## Stream 4: Full Test Suite Validation

### Task 11: Run full test suite and save results

**Step 1: Run all gateway tests**

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p tests/output/gateway tests/output/backend
uv run python -m pytest tests/gateway/ -v 2>&1 | tee "tests/output/gateway/${TIMESTAMP}_test_full_gateway_results.log" | tail -30
```

**Step 2: Run all contract tests**

```bash
uv run python -m pytest tests/contracts/ -v 2>&1 | tee "tests/output/backend/${TIMESTAMP}_test_contracts_results.log" | tail -20
```

**Step 3: Fix any failures**

If any tests fail due to the confirm gate changes, fix them. Common issues:
- Tests that assert `{"decision": "confirm"}` return from hooks — update to expect no confirm handling in hooks
- Tests that rely on `gated_tools` being passed to `create_hooks` — keep the parameter but the hook no longer acts on it

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: full test suite validation after confirm gate and isolation work"
```

---

## Verification Checklist

After all tasks are complete, verify:

1. `uv run python -m pytest tests/gateway/test_confirm_gate.py -v` — all confirm gate tests pass
2. `uv run python -m pytest tests/gateway/test_tool_modularity.py -v` — all modularity tests pass
3. `uv run python -m pytest tests/gateway/test_hooks.py -v` — hook tests pass without confirm logic
4. `uv run python -m pytest tests/gateway/test_permissions.py -v` — permission tests still pass
5. `git grep 'patanet7' -- ':!docs/plans/' ':!.venv/'` — no personal data in tracked source
6. `git grep 'TODO.*confirm.*gate' corvus/` — no remaining confirm gate TODOs
7. Each agent YAML spec resolves to exactly its declared modules (no cross-agent leaks)
8. Gated tools block until user approval (not silently allowed)
9. Denied gated tools return `PermissionResultDeny` to the SDK

---

## Dependency Order

```
Stream 1: Confirm Gate
  Task 1 (failing test) → Task 2 (ConfirmQueue) → Task 3 (wire can_use_tool) → Task 4 (wire ChatSession) → Task 5 (cleanup hooks)

Stream 2: Personal Data
  Task 6 (cleanup CLAUDE.md) — independent, can run anytime

Stream 3: Tool Modularity Tests
  Task 7 (YAML→tools) → Task 8 (confirm expansion) → Task 9 (cross-agent isolation) → Task 10 (prompt isolation)
  ↑ independent of Stream 1

Stream 4: Validation
  Task 11 — after Streams 1-3 complete
```

Streams 1-3 are parallelizable. Stream 4 is the final gate.
