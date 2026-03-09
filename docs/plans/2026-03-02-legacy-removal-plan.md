# Phase 4 Task 13: Full Legacy Removal & Hub Alignment

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all legacy code paths (agent_config, agents_legacy, providers.registry, USE_AGENTS_HUB feature flag) so the hub architecture is the only code path.

**Architecture:** The AgentsHub (YAML-driven agent specs + CapabilitiesRegistry + MemoryHub) becomes the sole system. server.py loses ~500 lines of old code. The supervisor migrates from ToolProviderRegistry to CapabilitiesRegistry. All legacy test files that only exercise deleted modules are removed; source-contract tests are updated to verify the new wiring.

**Tech Stack:** Python 3.11+, FastAPI, claude_agent_sdk, SQLite (FTS5), pytest

**Branch:** `feature/agents-hub-architecture` (continue on current branch)

---

## Pre-flight: Current State

- `corvus/hooks.py` has been partially edited: `CONFIRM_GATED_TOOLS` set + its import removed, `create_hooks()` defaults to `set()`.
- `corvus/agents/hub.py` line 19 imports `CONFIRM_GATED_TOOLS` from `corvus.hooks` — **this is broken** and will cause `ImportError` at startup.
- All 2099 tests were passing before the hooks.py edit; the edit broke hub.py's import.

---

## Sub-phase A: Fix Immediate Breakage

### Task 1: Fix hub.py broken import of CONFIRM_GATED_TOOLS

**Files:**
- Modify: `corvus/agents/hub.py:19,158`

**Step 1: Remove the broken import**

In `corvus/agents/hub.py`, remove line 19:
```python
from corvus.hooks import CONFIRM_GATED_TOOLS
```

**Step 2: Update get_confirm_gated_tools() to start from empty set**

Change line 158 from:
```python
gated: set[str] = set(CONFIRM_GATED_TOOLS)
```
to:
```python
gated: set[str] = set()
```

Also update the docstring for `get_confirm_gated_tools()` — remove the reference to "CONFIRM_GATED_TOOLS baseline". The new docstring should say:

```python
def get_confirm_gated_tools(self) -> set[str]:
    """Derive confirm-gated tool names from all enabled agent specs.

    Aggregates confirm_gated entries from all enabled agent YAML specs.
    YAML specs are the single source of truth for which tools require
    user confirmation before execution.

    YAML specs use short dotted names (e.g. "obsidian.write"). These are
    expanded to the full MCP tool name format used by the SDK hooks:
    ``mcp__{server}_{agent}__{tool}`` for per-agent servers, or
    ``mcp__{server}__{tool}`` for shared servers.
    """
```

**Step 3: Run tests to verify the fix**

Run: `mise run test 2>&1 | tail -5`
Expected: All tests pass (some may fail due to other broken imports — that's expected, we fix them in later tasks)

**Step 4: Commit**

```bash
git add corvus/agents/hub.py
git commit -m "fix: remove broken CONFIRM_GATED_TOOLS import from hub.py

Hub now aggregates gated tools purely from YAML specs — no hardcoded
baseline. The old CONFIRM_GATED_TOOLS set was removed from hooks.py
in the prior edit; this commit fixes the dangling import."
```

---

## Sub-phase B: Remove agent_config.py Dependencies

### Task 2: Remove agent_config imports from memory/hub.py

**Files:**
- Modify: `corvus/memory/hub.py:19-20,55-56`

**Step 1: Remove the two agent_config imports at lines 19-20**

Remove:
```python
from corvus.agent_config import get_memory_access as _default_get_memory_access
from corvus.agent_config import get_readable_private_domains as _default_get_readable_domains
```

**Step 2: Change the `__init__` defaults to inline safe fallbacks**

The current code (around line 55) does:
```python
self._get_memory_access = get_memory_access_fn or _default_get_memory_access
self._get_readable_domains = get_readable_domains_fn or _default_get_readable_domains
```

Change to:
```python
def _safe_memory_access(agent_name: str) -> dict[str, Any]:
    """Safe default: shared domain, read-only, no cross-domain access."""
    return {
        "own_domain": "shared",
        "can_read_shared": True,
        "can_write": False,
        "readable_domains": None,
    }

def _safe_readable_domains(agent_name: str) -> list[str]:
    """Safe default: own domain only."""
    return ["shared"]
```

Then in `__init__`:
```python
self._get_memory_access = get_memory_access_fn or _safe_memory_access
self._get_readable_domains = get_readable_domains_fn or _safe_readable_domains
```

Place the two safe-default functions as module-level helpers (above the class) or as static methods of MemoryHub.

**Step 3: Run memory tests**

Run: `mise run test -- tests/memory/ -v 2>&1 | tail -20`
Expected: All memory tests pass. MemoryHub is always rewired via `set_resolvers()` in production, so these defaults only matter for tests and graceful fallback.

**Step 4: Commit**

```bash
git add corvus/memory/hub.py
git commit -m "refactor: remove agent_config dependency from MemoryHub

Replace legacy agent_config imports with inline safe defaults (shared
domain, read-only). In production, AgentsHub always calls set_resolvers()
to wire YAML-based lookups."
```

---

### Task 3: Remove agent_config import from memory/toolkit.py

**Files:**
- Modify: `corvus/memory/toolkit.py:17,53-54`

**Step 1: Remove the import at line 17**

Remove:
```python
from corvus.agent_config import get_memory_access
```

**Step 2: Change the own_domain fallback**

The current code (around line 53) does:
```python
if own_domain is None:
    own_domain = get_memory_access(agent_name)["own_domain"]
```

Change to:
```python
if own_domain is None:
    own_domain = "shared"
```

In the hub path, `build_mcp_servers()` always passes `own_domain` explicitly from the YAML spec. This fallback only fires if someone calls `create_memory_toolkit()` without specifying `own_domain`.

**Step 3: Run toolkit tests**

Run: `mise run test -- tests/memory/ -v 2>&1 | tail -20`
Expected: All pass.

**Step 4: Commit**

```bash
git add corvus/memory/toolkit.py
git commit -m "refactor: remove agent_config dependency from memory toolkit

Default own_domain to 'shared' when not explicitly provided. Hub always
passes own_domain from YAML spec via build_mcp_servers()."
```

---

### Task 4: Remove agents_legacy import from session.py

**Files:**
- Modify: `corvus/session.py:41-71`

**Step 1: Replace `_build_valid_domains()` with a static set**

Replace the entire function (lines 41-71) with:
```python
# Static domain set — matches agent YAML specs in config/agents/.
# "general" excluded: cross-domain queries get tagged by actual domain.
VALID_DOMAINS = {
    "personal",
    "work",
    "homelab",
    "finance",
    "email",
    "docs",
    "music",
    "home",
    "shared",
}
```

This removes the `from corvus.agents_legacy import build_agents` call entirely.

**Step 2: Run session tests**

Run: `mise run test -- tests/gateway/test_session.py -v 2>&1 | tail -20`
Expected: All pass.

**Step 3: Commit**

```bash
git add corvus/session.py
git commit -m "refactor: replace agents_legacy import in session.py with static domain set

Domain set matches agent YAML specs. No more runtime dependency on
agents_legacy.build_agents()."
```

---

## Sub-phase C: Migrate Supervisor to CapabilitiesRegistry

### Task 5: Refactor supervisor.py to use CapabilitiesRegistry

**Files:**
- Modify: `corvus/supervisor.py`

The supervisor currently depends on `ToolProviderRegistry` for:
1. `registry.health_check_all()` → `dict[str, HealthStatus]`
2. `registry.get(name)` → `ProviderConfig | None` → `.restart`

CapabilitiesRegistry provides:
1. `list_available()` → `list[str]` + `health(name)` → `ModuleHealth`
2. `get_module(name)` → `ToolModuleEntry | None` → `.restart`

**Step 1: Update the import**

Change:
```python
from corvus.providers.registry import ToolProviderRegistry
```
to:
```python
from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth
```

**Step 2: Update `__init__` type annotation**

Change:
```python
def __init__(
    self,
    registry: ToolProviderRegistry,
    ...
```
to:
```python
def __init__(
    self,
    registry: CapabilitiesRegistry,
    ...
```

**Step 3: Rewrite `heartbeat()` method**

Change from calling `self.registry.health_check_all()` to iterating modules:

```python
async def heartbeat(self) -> dict[str, Any]:
    """Run health checks on all registered modules and auto-restart unhealthy ones."""
    mcp_status: dict[str, dict[str, Any]] = {}

    for module_name in self.registry.list_available():
        health: ModuleHealth = self.registry.health(module_name)
        mcp_status[module_name] = {
            "status": health.status,
            "detail": health.detail,
        }
        if health.status == "unhealthy":
            await self._try_restart(module_name, mcp_status)

    await self.emitter.emit("heartbeat", mcp_status=mcp_status)
    return mcp_status
```

**Step 4: Rewrite `_try_restart()` and `restart_provider()`**

Change from `self.registry.get(name) → ProviderConfig → config.restart` to:

```python
async def _try_restart(self, name: str, mcp_status: dict) -> None:
    """Attempt to restart an unhealthy module (capped at MAX_RESTART_ATTEMPTS)."""
    count = self._restart_counts.get(name, 0)
    if count >= MAX_RESTART_ATTEMPTS:
        mcp_status[name]["status"] = "degraded"
        mcp_status[name]["detail"] = f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) exceeded"
        return
    entry = self.registry.get_module(name)
    if entry is None or entry.restart is None:
        return
    try:
        self._restart_counts[name] = count + 1
        await entry.restart()
        mcp_status[name]["status"] = "restarting"
        logger.info("Restarted module %s (attempt %d)", name, count + 1)
    except Exception:
        logger.exception("Failed to restart module %s", name)

async def restart_provider(self, name: str) -> None:
    """Manually restart a module. Resets restart counter."""
    entry = self.registry.get_module(name)
    if entry is None:
        raise KeyError(f"Module '{name}' not found")
    if entry.restart is None:
        raise KeyError(f"Module '{name}' has no restart callable")
    self._restart_counts[name] = 0
    await entry.restart()
```

**Step 5: Run supervisor tests**

Run: `mise run test -- tests/gateway/test_supervisor.py -v 2>&1 | tail -20`
Expected: FAIL — tests still import from `corvus.providers.registry`. We fix test files in Sub-phase G.

**Step 6: Commit**

```bash
git add corvus/supervisor.py
git commit -m "refactor: migrate supervisor from ToolProviderRegistry to CapabilitiesRegistry

Supervisor now uses CapabilitiesRegistry.health() and .get_module()
instead of ToolProviderRegistry.health_check_all() and .get().
Tests updated in Sub-phase G."
```

---

## Sub-phase D: Clean server.py

This is the biggest change. We remove ~400 lines of legacy code and make the hub the only path.

### Task 6: Remove legacy imports from server.py

**Files:**
- Modify: `corvus/server.py:1-141` (imports section)

**Step 1: Remove these imports entirely**

```python
# DELETE these lines:
from corvus.agents_legacy import build_agents                    # line 36
from corvus.providers.registry import HealthStatus, ProviderConfig, ToolProviderRegistry  # line 62
from corvus.tools.drive import configure as configure_drive      # lines 69-82 (all drive imports)
from corvus.tools.email import configure as configure_email      # lines 83-94 (all email imports)
from corvus.tools.firefly import configure as configure_firefly  # lines 95-104 (all firefly imports)
from corvus.tools.ha import configure as configure_ha            # lines 105-112 (all ha imports)
from corvus.tools.obsidian import ObsidianClient                 # lines 113-118 (all obsidian imports)
from corvus.tools.paperless import configure as configure_paperless  # lines 119-128 (all paperless imports)
from corvus.yahoo_client import YahooClient                      # line 140
from scripts.common.memory_engine import init_db               # line 141
```

Also remove unused config imports that were only used by the old path:
```python
# Remove from the config import line (keep the ones still used):
FIREFLY_API_TOKEN, FIREFLY_URL, HA_TOKEN, HA_URL, PAPERLESS_API_TOKEN, PAPERLESS_URL
```
(Verify which config values are still used in the hub path before removing.)

**Step 2: Move the hub imports from the conditional block to top-level**

The current code at lines 249-252 does conditional imports inside `if USE_AGENTS_HUB:`. Move these to the top-level import section:

```python
from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry
```

Remove the `if TYPE_CHECKING:` guard for `AgentsHub` (line 21-22) since it's now a real import.

**Step 3: Commit (imports only)**

```bash
git add corvus/server.py
git commit -m "refactor: remove legacy imports from server.py

Remove all direct tool imports (email, drive, ha, paperless, firefly,
obsidian), agents_legacy, providers.registry, YahooClient, init_db.
Move hub imports from conditional block to top-level."
```

---

### Task 7: Remove feature flag and legacy infrastructure from server.py

**Files:**
- Modify: `corvus/server.py` (lines 154-243 region)

**Step 1: Delete `parse_feature_flag` function and `USE_AGENTS_HUB` variable**

Remove:
```python
def parse_feature_flag(value: str) -> bool:
    """Parse a feature flag string into a boolean. Used by USE_AGENTS_HUB."""
    return value.lower() in ("1", "true", "yes")

USE_AGENTS_HUB = parse_feature_flag(os.environ.get("USE_AGENTS_HUB", ""))
```

**Step 2: Delete legacy provider infrastructure**

Remove entirely:
```python
async def _make_health(name: str) -> HealthStatus: ...
_PROVIDER_DEFS: list[tuple[str, str, list[str]]] = [...]
def _no_tools(_cfg: Any) -> list: ...
def _register_providers(registry: ToolProviderRegistry) -> None: ...
```

**Step 3: Delete `provider_registry` and `_register_providers` call**

Remove from the module-level init:
```python
provider_registry = ToolProviderRegistry()
_register_providers(provider_registry)
```

**Step 4: Update supervisor init to use CapabilitiesRegistry**

Change:
```python
supervisor = AgentSupervisor(registry=provider_registry, emitter=emitter)
```
to:
```python
# supervisor is initialized after _capabilities_registry is created (below)
```

Then move the supervisor creation to AFTER the CapabilitiesRegistry is initialized.

**Step 5: Make hub initialization unconditional**

Remove the `if USE_AGENTS_HUB:` guard. The hub init block becomes the only path:

```python
# --- Hub initialization (always on) ---
_agent_registry = AgentRegistry(config_dir=Path("config/agents"))
_agent_registry.load()
logger.info("AgentRegistry loaded %d agents", len(_agent_registry.list_all()))

_capabilities_registry = CapabilitiesRegistry()
for module_def in TOOL_MODULE_DEFS:
    _capabilities_registry.register(module_def.name, module_def)
logger.info("CapabilitiesRegistry loaded %d modules", len(_capabilities_registry.list_available()))

# Supervisor uses CapabilitiesRegistry for health checks
supervisor = AgentSupervisor(registry=_capabilities_registry, emitter=emitter)

# Two-phase MemoryHub init
_memory_hub = MemoryHub(MemoryConfig(primary_db_path=MEMORY_DB))
_agents_hub = AgentsHub(
    registry=_agent_registry,
    capabilities=_capabilities_registry,
    memory_hub=_memory_hub,
    model_router=model_router,
    emitter=emitter,
    config_dir=Path(__file__).resolve().parent.parent,
)
_memory_hub.set_resolvers(
    get_memory_access_fn=_agents_hub.get_memory_access,
    get_readable_domains_fn=_agents_hub.get_readable_private_domains,
)

# Startup validation
_hub_errors = _memory_hub.validate_ready()
if _hub_errors:
    for err in _hub_errors:
        logger.error("Startup validation FAILED: %s", err)
    raise RuntimeError(f"AgentsHub startup validation failed: {'; '.join(_hub_errors)}")
logger.info("AgentsHub initialized and validated")

# Wire REST API
from corvus.api.agents import configure as configure_agents_api
from corvus.api.agents import router as agents_router
configure_agents_api(_agents_hub, _capabilities_registry)

# Router with registry
router_agent = RouterAgent(registry=_agent_registry)
```

Remove the `else: router_agent = RouterAgent()` fallback.

**Step 6: Commit**

```bash
git add corvus/server.py
git commit -m "refactor: remove feature flag and legacy provider infrastructure

USE_AGENTS_HUB removed — hub is now the only code path.
ToolProviderRegistry, _register_providers, _make_health, _PROVIDER_DEFS
all deleted. Supervisor wired to CapabilitiesRegistry."
```

---

### Task 8: Remove old build_options() and legacy helpers from server.py

**Files:**
- Modify: `corvus/server.py` (lines 366-606 region)

**Step 1: Delete `_legacy_memory_hub` and dual-path `get_memory_hub()`**

Replace with a simple function:
```python
def get_memory_hub() -> MemoryHub:
    """Return the active MemoryHub instance."""
    return _memory_hub
```

**Step 2: Delete the entire `build_options()` function** (lines 436-605)

This is ~170 lines of monolithic tool MCP server construction. All of this is replaced by `_build_options_hub()`.

**Step 3: Rename `_build_options_hub` to `build_options`**

Change `def _build_options_hub(user: str, websocket=None)` to `def build_options(user: str, websocket=None)`.

Update its docstring to remove the "hub-driven" qualifier — it's now the only implementation.

Remove the `if _agents_hub is None: raise RuntimeError(...)` guard since `_agents_hub` is always initialized (no more feature flag).

**Step 4: Remove the `if USE_AGENTS_HUB:` in websocket_chat**

In the WebSocket handler, change:
```python
if USE_AGENTS_HUB:
    options = _build_options_hub(user, websocket=websocket)
else:
    options = build_options(user, websocket=websocket)
```
to:
```python
options = build_options(user, websocket=websocket)
```

**Step 5: Remove `if USE_AGENTS_HUB:` from the `app.include_router` call**

Change:
```python
if USE_AGENTS_HUB:
    app.include_router(agents_router)
```
to:
```python
app.include_router(agents_router)
```

**Step 6: Update `_ensure_dirs()` — remove `init_db` call**

Remove the `init_db` call from `_ensure_dirs()`:
```python
def _ensure_dirs() -> None:
    """Create all required directories for local dev / first run."""
    for d in (MEMORY_DB.parent, MEMORY_DIR, WORKSPACE_DIR, EVENTS_LOG.parent):
        d.mkdir(parents=True, exist_ok=True)
```

The MemoryHub's FTS5Backend creates its own schema; the old `init_db` was for the MemoryEngine (chunks/files/meta tables).

Also remove `import sqlite3 as _sqlite3` if no longer used.

**Step 7: Commit**

```bash
git add corvus/server.py
git commit -m "refactor: delete old build_options() and legacy helpers

Removed ~200 lines: monolithic tool MCP construction, _legacy_memory_hub,
init_db wiring, feature flag conditionals. _build_options_hub renamed to
build_options. Hub is the sole code path."
```

---

## Sub-phase E: Update webhooks.py

### Task 9: Verify webhooks.py works with renamed build_options

**Files:**
- Modify: `corvus/webhooks.py:119` (if needed)

**Step 1: Verify the import**

`webhooks.py` line 119 does:
```python
from corvus.server import build_options
```

Since we renamed `_build_options_hub` to `build_options`, this import already works. The old `build_options` was replaced by the hub version with the same name. **No change needed.**

**Step 2: Run webhook tests**

Run: `mise run test -- tests/gateway/test_webhooks.py -v 2>&1 | tail -10`
Expected: Pass (if SDK is available) or skip (if not).

**Step 3: Commit** (only if changes were needed)

---

## Sub-phase F: Delete Legacy Source Files

### Task 10: Delete legacy modules

**Files:**
- Delete: `corvus/agent_config.py`
- Delete: `corvus/agents_legacy.py`
- Delete: `corvus/providers/registry.py`
- Delete: `corvus/providers/__init__.py`
- Delete: `scripts/memory_search.py`

**Step 1: Verify no remaining imports**

Run these checks to confirm all imports have been removed:
```bash
grep -r "from corvus.agent_config import" corvus/ --include="*.py"
grep -r "from corvus.agents_legacy import" corvus/ --include="*.py"
grep -r "from corvus.providers.registry import" corvus/ --include="*.py"
grep -r "from corvus.providers import" corvus/ --include="*.py"
```

Expected: No matches (test files may still have them — those are fixed in Sub-phase G).

**Step 2: Delete the files**

```bash
rm corvus/agent_config.py
rm corvus/agents_legacy.py
rm corvus/providers/registry.py
rm corvus/providers/__init__.py
rm scripts/memory_search.py
rmdir corvus/providers/  # remove empty directory
```

**Step 3: Commit**

```bash
git add -A corvus/agent_config.py corvus/agents_legacy.py corvus/providers/ scripts/memory_search.py
git commit -m "chore: delete legacy modules

Removed: corvus/agent_config.py, corvus/agents_legacy.py,
corvus/providers/ (registry.py + __init__.py), scripts/memory_search.py.
All functionality moved to hub architecture (AgentSpec YAML, AgentsHub,
CapabilitiesRegistry)."
```

---

## Sub-phase G: Delete and Update Test Files

### Task 11: Delete legacy-only test files

**Files to delete** (100% test deleted legacy modules — no salvageable coverage):
- `tests/contracts/test_agent_config.py` — tests corvus.agent_config
- `tests/gateway/test_agent_isolation.py` — tests agents_legacy.build_agents() + agent_config
- `tests/gateway/test_agent_integration.py` — tests agents_legacy.build_agents() + agent_config
- `tests/gateway/test_agent_prompts.py` — tests prompt loading via build_agents()
- `tests/gateway/test_provider_registration.py` — tests _register_providers + ToolProviderRegistry
- `tests/integration/test_agents_live.py` — tests agents_legacy fleet
- `tests/integration/test_memory_visibility_live.py` — tests agent_config + MemoryEngine
- `tests/scripts/test_memory_search_cli.py` — tests scripts/memory_search.py

**Step 1: Delete the files**

```bash
rm tests/contracts/test_agent_config.py
rm tests/gateway/test_agent_isolation.py
rm tests/gateway/test_agent_integration.py
rm tests/gateway/test_agent_prompts.py
rm tests/gateway/test_provider_registration.py
rm tests/integration/test_agents_live.py
rm tests/integration/test_memory_visibility_live.py
rm tests/scripts/test_memory_search_cli.py
```

**Step 2: Commit**

```bash
git add -A
git commit -m "chore: delete test files for removed legacy modules

Removed 8 test files that exclusively tested deleted modules:
agent_config, agents_legacy.build_agents, ToolProviderRegistry,
_register_providers, memory_search CLI."
```

---

### Task 12: Update test_hooks.py

**Files:**
- Modify: `tests/gateway/test_hooks.py`

**Step 1: Remove `CONFIRM_GATED_TOOLS` from import**

Change:
```python
from corvus.hooks import CONFIRM_GATED_TOOLS, check_bash_safety, check_read_safety, create_hooks
```
to:
```python
from corvus.hooks import check_bash_safety, check_read_safety, create_hooks
```

**Step 2: Delete `TestConfirmGatedTools` class entirely**

This class tested membership in the hardcoded set (e.g., `assert "mcp__email__email_send" in CONFIRM_GATED_TOOLS`). That set no longer exists — tool gating is now tested via YAML specs and hub integration tests.

**Step 3: Keep `TestPreToolUseConfirmGating` — it passes explicit sets**

This class creates its own `confirm_gated` set and passes it to `create_hooks()`. No changes needed — it tests the hook mechanism, not the hardcoded list.

**Step 4: Run hook tests**

Run: `mise run test -- tests/gateway/test_hooks.py -v 2>&1 | tail -20`
Expected: All remaining tests pass.

**Step 5: Commit**

```bash
git add tests/gateway/test_hooks.py
git commit -m "test: remove CONFIRM_GATED_TOOLS assertions from hook tests

Hardcoded gated set removed from hooks.py; tool gating now driven by
YAML specs. Kept hook mechanism tests (TestPreToolUseConfirmGating)
which pass explicit sets."
```

---

### Task 13: Update test_ws_protocol.py

**Files:**
- Modify: `tests/gateway/test_ws_protocol.py`

**Step 1: Remove `CONFIRM_GATED_TOOLS` from import**

Change:
```python
from corvus.hooks import CONFIRM_GATED_TOOLS, create_hooks
```
to:
```python
from corvus.hooks import create_hooks
```

**Step 2: Fix any assertions that reference `CONFIRM_GATED_TOOLS`**

If any test references `CONFIRM_GATED_TOOLS`, replace with a local test set:
```python
_TEST_GATED = {"mcp__test__dangerous_tool"}
```

**Step 3: Run WS protocol tests**

Run: `mise run test -- tests/gateway/test_ws_protocol.py -v 2>&1 | tail -20`
Expected: All pass.

**Step 4: Commit**

```bash
git add tests/gateway/test_ws_protocol.py
git commit -m "test: remove CONFIRM_GATED_TOOLS import from WS protocol tests"
```

---

### Task 14: Update test_hub_switchover.py

**Files:**
- Modify: `tests/gateway/test_hub_switchover.py`

**Step 1: Remove `TestFeatureFlagParsing` class**

This class imports and tests `parse_feature_flag` which is being deleted. Remove the entire class.

**Step 2: Keep `TestRouterAgentWithRegistry`**

This tests the router with a real AgentRegistry — hub-era code. Keep as-is.

**Step 3: Update imports**

Remove `from corvus.server import parse_feature_flag` if present.

**Step 4: Run**

Run: `mise run test -- tests/gateway/test_hub_switchover.py -v 2>&1 | tail -10`
Expected: Pass.

**Step 5: Commit**

```bash
git add tests/gateway/test_hub_switchover.py
git commit -m "test: remove feature flag tests from hub_switchover

parse_feature_flag and USE_AGENTS_HUB removed from server.py.
Kept TestRouterAgentWithRegistry (hub-era)."
```

---

### Task 15: Update test_10b_wiring.py

**Files:**
- Modify: `tests/gateway/test_10b_wiring.py`

This file reads `agents_legacy.py` and `hooks.py` source to check for specific strings. Both are being removed/changed.

**Step 1: Rewrite to check YAML specs + capabilities modules instead**

The test classes `TestPaperlessWiring` and `TestFireflyWiring` currently verify that:
- `server.py` imports tool functions
- `agents_legacy.py` has MCP tool name strings
- `hooks.py` has confirm-gated tool names

Rewrite to verify:
- `config/agents/docs.yaml` has paperless module + confirm_gated entries
- `config/agents/finance.yaml` has firefly module + confirm_gated entries
- `corvus/capabilities/modules.py` defines the tool modules
- `corvus/hooks.py` still has `create_hooks` (mechanism exists)

Replace source-string assertions with YAML content assertions:
```python
import yaml
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent.parent / "config" / "agents"

class TestPaperlessWiring:
    def _load_docs(self):
        return yaml.safe_load((AGENTS_DIR / "docs.yaml").read_text())

    def test_docs_agent_has_paperless_module(self):
        spec = self._load_docs()
        assert "paperless" in spec["tools"]["modules"]

    def test_paperless_tag_confirm_gated(self):
        spec = self._load_docs()
        assert "paperless.tag" in spec["tools"]["confirm_gated"]

    def test_paperless_bulk_edit_confirm_gated(self):
        spec = self._load_docs()
        assert "paperless.bulk_edit" in spec["tools"]["confirm_gated"]

class TestFireflyWiring:
    def _load_finance(self):
        return yaml.safe_load((AGENTS_DIR / "finance.yaml").read_text())

    def test_finance_agent_has_firefly_module(self):
        spec = self._load_finance()
        assert "firefly" in spec["tools"]["modules"]

    def test_firefly_create_transaction_confirm_gated(self):
        spec = self._load_finance()
        assert "firefly.create_transaction" in spec["tools"]["confirm_gated"]

class TestConfirmGateCompleteness:
    def test_read_only_not_gated(self):
        """Read-only tools should not appear in confirm_gated."""
        docs = yaml.safe_load((AGENTS_DIR / "docs.yaml").read_text())
        gated = docs["tools"]["confirm_gated"]
        for ro_tool in ["paperless.search", "paperless.read", "paperless.tags"]:
            assert ro_tool not in gated
```

**Step 2: Remove all references to `agents_legacy.py`**

No `_load()` method should read `agents_legacy.py` anymore.

**Step 3: Run**

Run: `mise run test -- tests/gateway/test_10b_wiring.py -v 2>&1 | tail -20`
Expected: Pass.

**Step 4: Commit**

```bash
git add tests/gateway/test_10b_wiring.py
git commit -m "test: rewrite wiring tests to verify YAML specs instead of legacy source

Tool wiring is now verified via agent YAML specs and capabilities
module definitions, not by reading deleted agents_legacy.py source."
```

---

### Task 16: Update test_server.py source contracts

**Files:**
- Modify: `tests/gateway/test_server.py`

**Step 1: Remove assertion for `init_db` import**

Delete or update:
```python
def test_imports_init_db(self):
    """server.py imports init_db for schema initialization."""
    assert "from scripts.common.memory_engine import init_db" in self.source
```

**Step 2: Remove `test_parse_feature_flag_defined`**

```python
def test_parse_feature_flag_defined(self):
    """parse_feature_flag must be a testable function."""
    assert "def parse_feature_flag" in self.source
```

**Step 3: Update any remaining assertions that reference deleted code**

Check each assertion in `TestServerSourceContracts` and `TestServerSourceContracts` to ensure they match the new server.py. Key ones to update:

- `test_imports_paperless_tools` — keep if server.py still has these imports via capabilities (check)
- `test_imports_firefly_tools` — same
- `test_build_options_hub_wires_mcp_servers` — rename assertion to `build_options` (not `_hub`)

**Step 4: Run**

Run: `mise run test -- tests/gateway/test_server.py -v 2>&1 | tail -20`
Expected: Pass.

**Step 5: Commit**

```bash
git add tests/gateway/test_server.py
git commit -m "test: update server source contracts for hub-only architecture

Removed assertions for init_db import and parse_feature_flag.
Updated wiring assertions to match hub-driven server.py."
```

---

### Task 17: Update supervisor test files

**Files:**
- Modify: `tests/gateway/test_supervisor.py`
- Modify: `tests/integration/test_supervisor_live.py`
- Modify: `tests/gateway/test_10a_integration.py`
- Keep as-is or delete: `tests/gateway/test_provider_registry.py` (see below)

These test files import `HealthStatus`, `ProviderConfig`, `ToolProviderRegistry` from `corvus.providers.registry` which is being deleted.

**Step 1: Decide on `test_provider_registry.py`**

`test_provider_registry.py` tests the `ToolProviderRegistry` class itself. Since that class is being deleted, **delete this file**:
```bash
rm tests/gateway/test_provider_registry.py
```

**Step 2: Rewrite `test_supervisor.py` to use CapabilitiesRegistry**

Replace:
```python
from corvus.providers.registry import HealthStatus, ProviderConfig, ToolProviderRegistry
```
with:
```python
from corvus.capabilities.registry import CapabilitiesRegistry, ModuleHealth, ToolModuleEntry
```

Update all test fixtures that create `ProviderConfig` objects to create `ToolModuleEntry` objects instead. Update assertions that check `HealthStatus` fields to check `ModuleHealth` fields:
- `HealthStatus.status` → `ModuleHealth.status` (same field name)
- `HealthStatus.name` → `ModuleHealth.name` (same)
- `HealthStatus.detail` → `ModuleHealth.detail` (same)
- `HealthStatus.uptime` / `.restarts` → Not in ModuleHealth (remove assertions)

**Step 3: Rewrite `test_supervisor_live.py` similarly**

Same pattern as above — swap provider types for capabilities types.

**Step 4: Update `test_10a_integration.py`**

Replace provider imports with capabilities imports. This file tests the full stack integration (emitter + hooks + supervisor + model_router).

**Step 5: Run all supervisor tests**

Run: `mise run test -- tests/gateway/test_supervisor.py tests/integration/test_supervisor_live.py tests/gateway/test_10a_integration.py -v 2>&1 | tail -30`
Expected: Pass.

**Step 6: Commit**

```bash
git add tests/gateway/test_supervisor.py tests/integration/test_supervisor_live.py tests/gateway/test_10a_integration.py tests/gateway/test_provider_registry.py
git commit -m "test: migrate supervisor tests from ToolProviderRegistry to CapabilitiesRegistry

Rewrote test fixtures to use ToolModuleEntry + ModuleHealth instead of
ProviderConfig + HealthStatus. Deleted test_provider_registry.py."
```

---

### Task 18: Update remaining test files with legacy references

**Files:**
- Modify: `tests/gateway/test_agents.py` — remove `TestBuildAgentsSDK` class (uses `build_agents()`)
- Modify: `tests/gateway/test_session.py` — remove defensive `from corvus.agents_legacy import build_agents` in try/except
- Modify: `tests/gateway/test_credential_wiring.py` — update `test_init_credentials_called_before_register_providers` assertion
- Modify: `tests/scripts/test_email.py` — remove/update source-level assertions reading `agents_legacy.py`

**Step 1: Update test_agents.py**

Delete `TestBuildAgentsSDK` class (lines 310-339) which calls `build_agents()`. Keep the rest of the file (source-level contract tests, agent description checks, etc. that DON'T import agents_legacy).

Check if any other classes in the file reference `agents_legacy` and remove/update them.

**Step 2: Update test_session.py**

Find the try/except block around line 420 that does:
```python
from corvus.agents_legacy import build_agents
agents = build_agents()
domains = {name for name in agents if name != "general"}
```
This should be replaced with a direct reference to the static `VALID_DOMAINS` from `corvus.session`:
```python
from corvus.session import VALID_DOMAINS
```

**Step 3: Update test_credential_wiring.py**

The test `test_init_credentials_called_before_register_providers` checks source ordering of `_init_credentials()` vs `_register_providers(`. Since `_register_providers` is deleted, this test needs updating. Change to verify `_init_credentials()` is called before hub initialization instead.

**Step 4: Update test_email.py**

The `TestEmailSourceContracts` class reads `agents_legacy.py` source. Since that file is deleted, either:
- Rewrite to check YAML specs (e.g., email agent has email module)
- Delete the source-contract tests for email agent wiring

**Step 5: Run all tests**

Run: `mise run test 2>&1 | tail -20`
Expected: Getting close to all passing.

**Step 6: Commit**

```bash
git add tests/
git commit -m "test: update remaining test files for hub-only architecture

Fixed: test_agents.py, test_session.py, test_credential_wiring.py,
test_email.py — removed all agents_legacy and agent_config references."
```

---

## Sub-phase H: Final Validation & Cleanup

### Task 19: Full test suite validation

**Step 1: Run full test suite**

```bash
mise run test 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_legacy_removal_results.log | tail -30
```
Expected: All tests pass (count will be lower than 2099 since we deleted test files).

**Step 2: Run linter**

```bash
mise run lint 2>&1 | tail -20
```
Expected: Clean.

**Step 3: Verify no remaining legacy references in source**

```bash
grep -r "from corvus.agent_config" corvus/ --include="*.py"
grep -r "from corvus.agents_legacy" corvus/ --include="*.py"
grep -r "from corvus.providers" corvus/ --include="*.py"
grep -r "USE_AGENTS_HUB" corvus/ --include="*.py"
grep -r "CONFIRM_GATED_TOOLS" corvus/ --include="*.py"
grep -r "ToolProviderRegistry" corvus/ --include="*.py"
grep -r "build_agents" corvus/ --include="*.py"
```
Expected: No matches for any of these.

**Step 4: Verify no remaining legacy references in tests**

```bash
grep -r "from corvus.agent_config" tests/ --include="*.py"
grep -r "from corvus.agents_legacy" tests/ --include="*.py"
grep -r "from corvus.providers.registry" tests/ --include="*.py"
grep -r "USE_AGENTS_HUB" tests/ --include="*.py"
grep -r "CONFIRM_GATED_TOOLS" tests/ --include="*.py"
```
Expected: No matches.

**Step 5: Commit final state**

```bash
git add -A
git commit -m "chore: verify clean legacy removal — all tests pass, no legacy refs"
```

---

### Task 20: Update YAML confirm_gated if needed

**Pre-check:** The old `CONFIRM_GATED_TOOLS` set contained:
- `mcp__email__email_send` → email.yaml: `email.send` ✅
- `mcp__email__email_archive` → email.yaml: `email.archive` ✅
- `mcp__drive__drive_delete` → docs.yaml: `drive.delete` ✅
- `mcp__drive__drive_permanent_delete` → docs.yaml: `drive.permanent_delete` ✅
- `mcp__drive__drive_share` → docs.yaml: `drive.share` ✅
- `mcp__drive__drive_cleanup` → docs.yaml: `drive.cleanup` ✅
- `mcp__ha__ha_call_service` → home.yaml: `ha.call_service` ✅
- `mcp__paperless__paperless_tag` → docs.yaml: `paperless.tag` ✅
- `mcp__paperless__paperless_bulk_edit` → docs.yaml: `paperless.bulk_edit` ✅
- `mcp__firefly__firefly_create_transaction` → finance.yaml: `firefly.create_transaction` ✅
- obsidian write tools → personal.yaml + homelab.yaml: `obsidian.write`, `obsidian.append` ✅

**Result: All tools covered.** No YAML updates needed. The old hardcoded set is fully represented in the YAML specs.

This is a verification-only task — no code changes unless gaps are found.

---

## Deferred Items (NOT in this plan)

These are explicitly deferred to a subsequent audit pass:

1. **`scripts/common/memory_engine.py`** — Still imported by `scripts/reindex.py`, `scripts/common/vault_writer.py`, and 6+ test files. Removing it requires migrating those scripts to MemoryHub, which is out of scope.

2. **`scripts/memory_search.py` references in prompt files** — `corvus/prompts/*.md` and `.claude/skills/*.md` reference `python /app/scripts/memory_search.py`. These prompts need updating to use the new `memory_search` MCP tool instead. This is a content update, not a code change.

3. **`scripts/common/memory_engine.py` import from agent_config** — The script at line 372 imports `from corvus.agent_config import get_readable_private_domains`. Since we're deleting `agent_config.py`, this import will break. **Must be fixed before deleting agent_config.py** — either inline a default or make `memory_engine.py` handle the ImportError gracefully.

---

## Dependency Order

```
Sub-phase A (Task 1) — fix hub.py import
    ↓
Sub-phase B (Tasks 2-4) — remove agent_config deps [parallel]
    ↓
Sub-phase C (Task 5) — migrate supervisor
    ↓
Sub-phase D (Tasks 6-8) — clean server.py [sequential]
    ↓
Sub-phase E (Task 9) — verify webhooks
    ↓
Sub-phase F (Task 10) — delete legacy files
    ↓
Sub-phase G (Tasks 11-18) — delete/update tests [mostly parallel]
    ↓
Sub-phase H (Tasks 19-20) — validate
```

**Critical path:** A → B → D → F → G → H
**Parallelizable:** Tasks 2, 3, 4 (within B); Tasks 11-18 (within G)

---

## Risk Mitigation

1. **Deferred item 3 is a blocker for Task 10:** `scripts/common/memory_engine.py` imports from `agent_config`. Before deleting `agent_config.py`, either:
   - Fix the import in `memory_engine.py` (add try/except ImportError with fallback)
   - Or delete `memory_engine.py` too (but that cascades to many scripts)
   - **Recommended:** Add a try/except fallback in `memory_engine.py` as a patch step between Tasks 4 and 10.

2. **Source-contract tests are brittle:** Many tests read source files as strings. After this refactor, some assertions become stale. Plan includes explicit updates in Tasks 15-18.

3. **Rollback strategy:** Every sub-phase has its own commit. If something breaks, `git revert` individual commits in reverse order.
