# Corvus Hub Architecture — Agents Hub, Capabilities Registry, Memory Cleanup

> **Date:** 2026-03-01
> **Status:** Design approved — ready for implementation planning
> **Scope:** Replace hardcoded agent wiring with config-driven Agents Hub, security-enforced Capabilities Registry, and complete Memory Hub migration.
> **Approach:** Top-down (Approach B) — Agents Hub first, everything flows from the spec.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Design Principles](#2-design-principles)
3. [AgentSpec — Single Source of Truth](#3-agentspec--single-source-of-truth)
4. [AgentRegistry — Loading and Validation](#4-agentregistry--loading-and-validation)
5. [CapabilitiesRegistry — Security-Enforced Tool Resolution](#5-capabilitiesregistry--security-enforced-tool-resolution)
6. [AgentsHub — The Coordinator](#6-agentshub--the-coordinator)
7. [Memory Cleanup — Retire the Old Engine](#7-memory-cleanup--retire-the-old-engine)
8. [REST Endpoints and Server Cleanup](#8-rest-endpoints-and-server-cleanup)
9. [Migration Plan](#9-migration-plan)
10. [Code Deletions](#10-code-deletions)
11. [File Map](#11-file-map)
12. [Deferred from v2](#12-deferred-from-v2)
13. [Architecture Review Amendments](#13-architecture-review-amendments)

---

## 1. Problem Statement

The current Corvus gateway has critical wiring gaps:

1. **Memory identity is hardcoded.** `create_memory_toolkit(hub, agent_name="personal")` in `server.py:451` means every agent writes memories as "personal" regardless of which domain agent is active. Domain isolation for memory is completely broken.

2. **System prompts aren't per-agent.** `build_system_prompt()` injects the same generic memory files for all agents, ignoring the per-agent `.md` prompt files that already exist in `corvus/prompts/`.

3. **Agent definitions are scattered across three files.** `corvus/agents.py` (Python dicts for descriptions/tools), `corvus/agent_config.py` (Obsidian access, memory domains), and `config/models.yaml` (model routing) — no single source of truth.

4. **Old memory engine still active alongside new Hub.** `scripts/common/memory_engine.py` and `corvus/memory/hub.py` both imported by `server.py`, creating a latent schema conflict (two different `memories` table definitions in the same SQLite file).

5. **Tool registration is monolithic.** `server.py` directly imports every tool module, calls `configure()` with hardcoded env vars, and manually builds MCP servers — no registry, no policy enforcement at resolution time.

6. **Everything is hardcoded.** `VALID_AGENTS` set in `router.py`, `CONFIRM_GATED_TOOLS` set in `hooks.py`, tool lists in Python dicts — none of this is config-driven or manageable from the frontend.

---

## 2. Design Principles

1. **Nothing hardcoded.** Agent definitions, tool access, memory domains, model preferences, confirm-gating — all config-driven via YAML specs. Python code reads config, never defines it.

2. **Spec is the single source of truth.** One YAML file per agent defines everything: personality (prompt file), tools, memory domain, model preferences, Obsidian access, confirm-gated tools.

3. **Security enforcement at resolution time.** The CapabilitiesRegistry is the policy boundary — it resolves tools for an agent according to deny-wins rules. Hooks remain for observability/audit, not primary enforcement.

4. **Agents are templates, not singletons.** Multiple instances of the same agent spec can run simultaneously, each with its own session and memory toolkit closure.

5. **Modular and extensible.** Memory backends, tool modules, and agent specs can all be added without touching core code.

6. **Primary always works.** If overlays, optional services, or model backends are unavailable, the system degrades gracefully — FTS5 memory, default models, reduced tool sets.

---

## 3. AgentSpec — Single Source of Truth

Each agent is defined by a YAML file at `config/agents/{name}.yaml`.

### 3.1 YAML Format

```yaml
# config/agents/personal.yaml
name: personal
description: >
  Daily planning, task management, journaling, ADHD support,
  stray thought capture, health tracking, personal reminders
enabled: true

# Model selection
models:
  preferred: null        # null = let router decide
  fallback: null         # null = global fallback from models.yaml
  auto: true             # allow router to override based on task
  complexity: medium     # high | medium | low — guides auto-selection

# Prompt — points to existing prompts/personal.md
prompt_file: prompts/personal.md

# Tools — builtin SDK tools + module references
tools:
  builtin:
    - Bash
    - Read
  modules:
    obsidian:
      allowed_prefixes: ["personal/", "shared/"]
      read: true
      write: true
    memory:
      enabled: true
  confirm_gated:
    - obsidian.write
    - obsidian.append

# Memory domain isolation
memory:
  own_domain: personal
  readable_domains: null   # null = own domain only
  can_read_shared: true
  can_write: true
```

### 3.2 All 9 Default Agent Specs

| Agent | Complexity | Tool Modules | Memory Domain | Obsidian |
|-------|-----------|--------------|---------------|----------|
| personal | medium | obsidian(r/w), memory | personal | personal/, shared/ |
| work | medium | obsidian(r), email(r), drive(r), memory | work | work/, shared/, personal/planning/ |
| homelab | high | obsidian(r/w), memory | homelab | homelab/ |
| finance | medium | firefly, memory | finance | — |
| email | medium | email(full), memory | email | — |
| docs | medium | paperless, drive(full), memory | docs | — |
| music | low | memory | music | — |
| home | low | ha, memory | home | — |
| general | medium | obsidian(r), memory | shared | all (no prefix restriction) |

### 3.3 Python Dataclasses

```python
# corvus/agents/spec.py

@dataclass
class AgentModelConfig:
    preferred: str | None = None
    fallback: str | None = None
    auto: bool = True
    complexity: str = "medium"  # "high" | "medium" | "low"

@dataclass
class AgentToolConfig:
    builtin: list[str] = field(default_factory=list)
    modules: dict[str, dict] = field(default_factory=dict)
    confirm_gated: list[str] = field(default_factory=list)

@dataclass
class AgentMemoryConfig:
    own_domain: str
    readable_domains: list[str] | None = None
    can_read_shared: bool = True
    can_write: bool = True

@dataclass
class AgentSpec:
    name: str
    description: str
    enabled: bool = True
    models: AgentModelConfig = field(default_factory=AgentModelConfig)
    prompt_file: str | None = None
    tools: AgentToolConfig = field(default_factory=AgentToolConfig)
    memory: AgentMemoryConfig | None = None
    metadata: dict = field(default_factory=dict)

    def prompt(self, config_dir: Path) -> str:
        """Resolve prompt, anchored to config_dir (not CWD).

        config_dir is passed by AgentRegistry at load time, ensuring
        consistent resolution in Docker, local dev, and tests.
        """
        if self.prompt_file:
            path = config_dir / self.prompt_file
            if path.exists():
                return path.read_text()
        return f"You are the {self.name} agent. Help the user with {self.name}-related tasks."

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec": ...

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentSpec": ...
```

---

## 4. AgentRegistry — Loading and Validation

`corvus/agents/registry.py` — loads YAML files, validates specs, provides lookup and CRUD.

### 4.1 Interface

```python
class AgentRegistry:
    """Load, validate, and serve AgentSpecs from config/agents/*.yaml."""

    def __init__(self, config_dir: Path, emitter: EventEmitter): ...

    def load(self) -> None
    def get(self, name: str) -> AgentSpec | None
    def list_enabled(self) -> list[AgentSpec]
    def list_all(self) -> list[AgentSpec]
    def reload(self) -> ReloadResult
    def create(self, spec: AgentSpec) -> None
    def update(self, name: str, patch: dict) -> AgentSpec
    def deactivate(self, name: str) -> None
    def validate(self, spec: AgentSpec) -> list[str]  # returns error messages
```

### 4.2 Validation Rules

Applied on `load()`, `create()`, and `update()`:

1. `name` — non-empty, alphanumeric + hyphens, unique across all specs
2. `description` — non-empty
3. `prompt_file` — file must exist if specified
4. `tools.modules` — each module name must exist in CapabilitiesRegistry
5. `memory.own_domain` — non-empty if memory config is present
6. `models.complexity` — must be one of `high`, `medium`, `low`

Invalid specs are rejected with structured errors. The registry emits `config_validation_error` events via EventEmitter.

### 4.3 ReloadResult

```python
@dataclass
class ReloadResult:
    added: list[str]      # new YAML files found
    removed: list[str]    # YAML files deleted
    changed: list[str]    # YAML files modified
    errors: dict[str, str]  # name -> validation error
```

`reload()` diffs against in-memory state. Triggered via REST endpoint (file watcher deferred to future work).

### 4.4 Persistence

CRUD operations write directly to `config/agents/{name}.yaml`. The YAML files are the persistence layer — no database needed for agent definitions. Git-auditable by design.

---

## 5. CapabilitiesRegistry — Security-Enforced Tool Resolution

`corvus/capabilities/registry.py` — the security boundary for all tool access. Every tool access flows through here.

### 5.1 Responsibilities

The CapabilitiesRegistry is NOT a simple lookup table. It is the **policy enforcement layer**:

1. **Registration** — tool modules register themselves at startup
2. **Resolution** — given an AgentSpec, return the fully-scoped, policy-enforced tool set
3. **Policy enforcement** — deny-wins at resolution time
4. **Confirm-gating** — derive which tools require user confirmation for a given agent

Hooks (`hooks.py`) remain for **observability and audit** — logging tool calls, emitting events to Loki, forwarding to WebSocket. Primary policy enforcement happens here at resolution time.

### 5.2 Interface

```python
class CapabilitiesRegistry:
    """Security-enforced tool resolution. All tool access flows through here."""

    def register(self, name: str, module: ToolModuleEntry) -> None
    def resolve(self, agent_spec: AgentSpec) -> ResolvedTools
    def is_allowed(self, agent_name: str, tool_name: str) -> bool
    def confirm_gated(self, agent_spec: AgentSpec) -> set[str]
    def list_available(self) -> list[str]
    def health(self, name: str) -> ModuleHealth
```

### 5.3 ToolModuleEntry

```python
@dataclass
class ToolModuleEntry:
    name: str                           # "obsidian", "email", "firefly", etc.
    configure: Callable                 # the existing configure() function
    create_tools: Callable              # returns list of tool functions
    create_mcp_server: Callable         # returns SDK MCP server
    requires_env: list[str]             # gate vars — ["HA_URL", "HA_TOKEN"]
    supports_per_agent: bool = False    # obsidian=True (per-agent clients), email=False
```

### 5.4 ResolvedTools

```python
@dataclass
class ResolvedTools:
    mcp_servers: dict[str, Any]         # name -> SDK MCP server
    confirm_gated: set[str]             # tool names requiring user confirmation
    available_modules: list[str]        # modules that resolved successfully
    unavailable_modules: dict[str, str] # module -> reason (env not set, etc.)
```

### 5.5 Resolution Logic

`resolve(agent_spec)` performs these steps in order:

1. Read `agent_spec.tools.modules` — the agent's requested tool modules
2. For each module, check env gates via `requires_env` — is the service configured?
3. If `supports_per_agent`, create a per-agent instance (e.g., ObsidianClient with agent-specific `allowed_prefixes`)
4. If not per-agent, return the shared module instance
5. Apply deny-wins policy — if any layer denies access, tool is excluded
6. Build `confirm_gated` set from agent spec's `tools.confirm_gated` list
7. Create MCP servers for each resolved module
8. Always create a per-agent memory MCP server (using correct agent identity from spec)
9. Return `ResolvedTools`

### 5.6 Module Registration at Startup

Each existing tool module registers once during server startup:

```python
# At startup — replaces the 100+ lines of imports and configure() calls in server.py
capabilities.register("obsidian", ToolModuleEntry(
    name="obsidian",
    configure=configure_obsidian,
    create_tools=lambda cfg: [...],
    create_mcp_server=...,
    requires_env=["OBSIDIAN_API_KEY"],
    supports_per_agent=True,
))

capabilities.register("email", ToolModuleEntry(
    name="email",
    configure=configure_email,
    create_tools=lambda: [email_list, email_read, ...],
    create_mcp_server=...,
    requires_env=["GOOGLE_CREDS_PATH"],
    supports_per_agent=False,
))

# ... same for ha, paperless, firefly, drive
```

---

## 6. AgentsHub — The Coordinator

`corvus/agents/hub.py` — the central coordinator that wires AgentSpec → tools → memory → SDK options.

### 6.1 Interface

```python
class AgentsHub:
    """Coordinates agent lifecycle: spec → tools → memory → SDK options."""

    def __init__(
        self,
        registry: AgentRegistry,
        capabilities: CapabilitiesRegistry,
        memory_hub: MemoryHub,
        model_router: ModelRouter,
        emitter: EventEmitter,
    ): ...

    # --- Core lifecycle ---
    def build_agent(self, name: str) -> AgentDefinition
    def build_all(self) -> dict[str, AgentDefinition]
    def build_mcp_servers(self, name: str) -> dict[str, Any]
    def build_options(self, user: str, websocket=None) -> ClaudeAgentOptions

    # --- Frontend management ---
    def list_agents(self) -> list[AgentSummary]
    def get_agent(self, name: str) -> AgentSpec
    def create_agent(self, spec: AgentSpec) -> AgentSpec
    def update_agent(self, name: str, patch: dict) -> AgentSpec
    def deactivate_agent(self, name: str) -> None
    def reload(self) -> ReloadResult
```

### 6.2 build_agent() — The Critical Method

This is where all the broken wiring gets fixed:

```python
def build_agent(self, name: str) -> AgentDefinition:
    spec = self.registry.get(name)
    if not spec or not spec.enabled:
        raise ValueError(f"Agent '{name}' not found or disabled")

    # 1. Resolve tools with security enforcement
    resolved = self.capabilities.resolve(spec)

    # 2. Create per-agent memory toolkit with CORRECT identity
    memory_toolkit = create_memory_toolkit(
        self.memory_hub,
        agent_name=spec.name,  # NOT hardcoded "personal"!
    )
    resolved.mcp_servers[f"memory_{spec.name}"] = create_sdk_mcp_server(
        name=f"memory_{spec.name}", version="1.0.0",
        tools=[t.fn for t in memory_toolkit],
    )

    # 3. Resolve model from spec
    model = self.model_router.resolve_for_agent(spec.models)

    # 4. Build SDK AgentDefinition
    return AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,  # from spec.prompt_file
        tools=spec.tools.builtin + [...],  # builtin + resolved module tools
        model=model,
    )
```

### 6.3 build_options() — Replaces server.py's 130-line function

```python
def build_options(self, user: str, websocket=None) -> ClaudeAgentOptions:
    agents = self.build_all()

    # Collect all MCP servers from all agents
    all_mcp_servers = {}
    for name in agents:
        agent_servers = self.build_mcp_servers(name)
        all_mcp_servers.update(agent_servers)

    return ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": ""},
        setting_sources=["project"],
        agents=agents,
        mcp_servers=all_mcp_servers if all_mcp_servers else None,
        hooks=self._build_hooks(websocket),
        permission_mode="bypassPermissions",
        user=user,
    )
```

### 6.4 Multi-Instance Support

The AgentSpec is a template. `build_agent()` creates a fresh `AgentDefinition` each time it's called — each invocation gets its own memory toolkit closure with the correct agent identity. Multiple simultaneous sessions using the same agent spec work naturally because each session calls `build_options()` independently.

### 6.5 AgentSummary for Frontend

```python
@dataclass
class AgentSummary:
    name: str
    description: str
    enabled: bool
    complexity: str
    tool_modules: list[str]
    memory_domain: str
    has_prompt: bool
```

---

## 7. Memory Cleanup — Retire the Old Engine

### 7.1 SessionManager — Separate Concern

Session CRUD moves out of `MemoryEngine` into its own class:

```python
# corvus/session_manager.py

class SessionManager:
    """Session lifecycle — separate concern from memory storage."""

    def __init__(self, db_path: Path): ...

    def start(self, agent_name: str) -> str   # returns session_id
    def end(self, session_id: str, transcript: str) -> None
    def get(self, session_id: str) -> Session
    def list(self, limit: int = 50) -> list[Session]
    def delete(self, session_id: str) -> None
    def rename(self, session_id: str, title: str) -> None
```

Configuration (db path, retention policy) comes from config, not hardcoded constants.

### 7.2 Schema Conflict Resolution

The old `MemoryEngine.init_db()` and new `FTS5Backend` both create a `memories` table with different columns. Resolution:

1. `FTS5Backend` owns the `memories` and `memories_fts` tables (correct schema)
2. `SessionManager` owns the `sessions` table
3. One-time migration script moves data from old `chunks`/`chunks_fts` tables into Hub schema
4. Old tables (`chunks`, `chunks_fts`, `embedding_cache`, `files`, `meta`) dropped after migration
5. `init_db()` from old engine deleted

### 7.3 Old Paths Killed

| Old Path | Replacement |
|----------|-------------|
| `scripts/common/memory_engine.py` | `MemoryHub` + `SessionManager` |
| `scripts/memory_search.py` | `MemoryToolkit` MCP tools (per-agent) |
| `scripts/common/vault_writer.py` | `corvus/memory/backends/vault.py` (already exists) |
| `server.py` importing `init_db` | `FTS5Backend` handles its own schema |

### 7.4 Cognee Overlay

`scripts/common/cognee_engine.py` currently only wired to the old `MemoryEngine`. It needs to be registered as a `MemoryHub` overlay backend, implementing the `MemoryBackend` protocol. The stub at `corvus/memory/backends/cognee.py` already exists — it needs to be completed and wired.

### 7.5 Schema Migration Script

Concrete column mappings for the one-time migration:

**Step 1: Backup.** Copy the SQLite file before any changes.

**Step 2: Migrate `chunks` → `memories` (new schema).**

| Old column (`chunks`) | New column (`memories`) | Mapping |
|----------------------|------------------------|---------|
| `id` | `id` | Auto-increment (new) |
| `content` | `content` | Direct copy |
| — | `record_id` | Generate UUID |
| — | `domain` | Default `"shared"` |
| — | `visibility` | Default `"shared"` |
| `source` | `source` | Direct copy |
| `tags` | `tags` | Direct copy |
| `created_at` | `created_at` | Direct copy |
| — | `updated_at` | Set to `created_at` |
| — | `deleted_at` | `NULL` |
| — | `importance` | Default `0.5` |
| — | `metadata` | `"{}"` |

**Step 3: Migrate old `memories` table** (if it exists with old schema — `session_id`, `expires_at` columns). Same mapping as above, preserving `importance` if present.

**Step 4: Drop old tables.** `chunks`, `chunks_fts`, `embedding_cache`, `files`, `meta`.

**Step 5: Rebuild FTS index.** Re-populate `memories_fts` from migrated `memories` table.

The `sessions` table is preserved as-is for `SessionManager`.

### 7.6 Session Extraction Identity Fix

The current `extract_session_memories()` in `session.py` defaults to `agent_name="general"`, so all extracted memories go to the "shared" domain regardless of which agent was active.

Fix: The `SessionTranscript` already tracks `agents_used`. The extraction call must pass the primary agent:

```python
# In server.py WebSocket stop hook:
primary_agent = transcript.primary_agent()  # most-used agent in the session
memories = await extract_session_memories(
    transcript, hub, agent_name=primary_agent
)
```

For multi-agent sessions, the LLM extraction already assigns domains per memory in its response. The `agent_name` parameter controls write permissions — using the primary agent ensures the MemoryHub allows writes to that agent's domain. Memories the LLM assigns to other domains are saved as "shared" visibility so they're accessible cross-domain.

---

## 8. REST Endpoints and Server Cleanup

### 8.1 New Endpoints

```
# Agent management (for frontend)
GET    /api/agents              → hub.list_agents()
GET    /api/agents/{name}       → hub.get_agent(name)
POST   /api/agents              → hub.create_agent(spec)
PATCH  /api/agents/{name}       → hub.update_agent(name, patch)
DELETE /api/agents/{name}       → hub.deactivate_agent(name)
POST   /api/agents/reload       → hub.reload()

# Capabilities info (for frontend)
GET    /api/capabilities        → capabilities.list_available()
GET    /api/capabilities/{name} → capabilities.health(name)
```

### 8.2 Server.py Transformation

Before (monolithic):
```python
from corvus.agents import build_agents
from corvus.agent_config import AGENT_TOOL_ACCESS, AGENT_MEMORY_ACCESS
# ... 100+ lines of tool imports and configure() calls
def build_options(user, websocket): ...  # 130 lines of hardcoded wiring
```

After (Hub-driven):
```python
from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.capabilities.registry import CapabilitiesRegistry

agent_registry = AgentRegistry(config_dir=Path("config/agents"), emitter=emitter)
capabilities = CapabilitiesRegistry()
hub = AgentsHub(
    registry=agent_registry,
    capabilities=capabilities,
    memory_hub=memory_hub,
    model_router=model_router,
    emitter=emitter,
)

# In WebSocket handler:
options = hub.build_options(user, websocket)
```

### 8.3 Router Agent Update

```python
# Before (hardcoded):
VALID_AGENTS = {"personal", "work", "homelab", ...}

# After (config-driven):
class RouterAgent:
    def __init__(self, registry: AgentRegistry): ...

    def get_valid_agents(self) -> set[str]:
        return {s.name for s in self.registry.list_enabled()}
```

---

## 9. Migration Plan

### Phase 1: Foundation (no behavior change)
1. Create `corvus/agents/spec.py` with dataclasses
2. Create `corvus/agents/registry.py` with load/validate
3. Write 9 default YAML specs in `config/agents/`
4. Create `corvus/capabilities/registry.py` with register/resolve
5. Tests for all of the above

### Phase 2: AgentsHub (the switchover)
6. Create `corvus/agents/hub.py` with build_agent/build_all/build_options
7. Register existing tool modules in CapabilitiesRegistry at startup
8. Add `USE_AGENTS_HUB` feature flag — when true, `server.py` uses `hub.build_options()`; when false, uses old path. Write comparison test that runs both paths and asserts output structures match (agent names, MCP server names, tool lists).
9. Switch default to `USE_AGENTS_HUB=true` after comparison tests pass
10. Update `RouterAgent` to read from registry
11. Tests verifying per-agent memory identity, per-agent tools

### Phase 3: Memory cleanup
12. Extract `SessionManager` from `MemoryEngine`
13. Write schema migration script with concrete column mappings (see 7.5)
14. Switch `/api/sessions/*` endpoints to `SessionManager`
15. Fix `extract_session_memories()` to pass correct agent identity (see 7.6)
16. Wire Cognee overlay into MemoryHub
17. Delete old memory engine paths

### Phase 4: REST + cleanup
18. Add agent management REST endpoints
19. Add capabilities info REST endpoints
20. Delete `corvus/agents.py`, `corvus/agent_config.py`
21. Delete `scripts/common/memory_engine.py`, `scripts/memory_search.py`
22. Delete `corvus/providers/registry.py` (subsumed into CapabilitiesRegistry)
23. Remove hardcoded `VALID_AGENTS`, `CONFIRM_GATED_TOOLS`
24. Remove `USE_AGENTS_HUB` feature flag (old path deleted)

---

## 10. Code Deletions

| File | Reason |
|------|--------|
| `corvus/agents.py` | Replaced by `AgentRegistry` + `config/agents/*.yaml` |
| `corvus/agent_config.py` | Absorbed into agent YAML specs |
| `scripts/common/memory_engine.py` | Replaced by `MemoryHub` + `SessionManager` |
| `scripts/memory_search.py` | Replaced by `MemoryToolkit` MCP tools |
| `corvus/providers/registry.py` | Subsumed into `CapabilitiesRegistry` (health checks + tool resolution unified) |
| `VALID_AGENTS` in `corvus/router.py` | Reads from `AgentRegistry.list_enabled()` |
| `CONFIRM_GATED_TOOLS` in `corvus/hooks.py` | Derived from agent specs via `CapabilitiesRegistry` |
| Old `build_options()` in `server.py` | Delegated to `AgentsHub.build_options()` |
| Old `build_system_prompt()` in `server.py` | Per-agent prompts from spec |

---

## 11. File Map

### New Files

```
corvus/
  agents/
    __init__.py
    spec.py              — AgentSpec, AgentModelConfig, AgentToolConfig, AgentMemoryConfig
    registry.py          — AgentRegistry: load, validate, CRUD, reload
    hub.py               — AgentsHub: build_agent, build_options, management API
  capabilities/
    __init__.py
    registry.py          — CapabilitiesRegistry: register, resolve, policy enforcement
  session_manager.py     — SessionManager: session CRUD (extracted from MemoryEngine)

config/
  agents/
    personal.yaml
    work.yaml
    homelab.yaml
    finance.yaml
    email.yaml
    docs.yaml
    music.yaml
    home.yaml
    general.yaml
```

### Modified Files

```
corvus/server.py           — Replaced monolithic build_options() with hub.build_options()
corvus/router.py           — VALID_AGENTS → registry.list_enabled()
corvus/hooks.py            — CONFIRM_GATED_TOOLS → derived from CapabilitiesRegistry
corvus/memory/hub.py       — Cognee overlay wired
corvus/memory/backends/cognee.py — Completed from stub
```

### Deleted Files

```
corvus/agents.py
corvus/agent_config.py
corvus/providers/registry.py
scripts/common/memory_engine.py
scripts/memory_search.py
```

---

## 12. Deferred from v2

This design implements a pragmatic V1 of the Capabilities Hub. The following v2 features are explicitly deferred to future work:

| Feature | v2 Section | Why Deferred |
|---------|-----------|--------------|
| **Thin proxy dispatch** | 6.2 | Tools are resolved statically at session creation. Per-turn dispatch via `capabilities_hub.dispatch()` is not needed until hot-reload during active sessions is required. |
| **Per-turn tool resolution** | 6.5 | Static resolution is sufficient — tool changes take effect on next session. |
| **5-layer cascading ToolPolicy class** | 6.4 | Policy enforcement happens in `CapabilitiesRegistry.resolve()` with deny-wins logic. A formal `ToolPolicy` class with global/agent/session/confirm/sanitize layers is deferred until session-level overrides are needed. |
| **Session-level tool overrides** | 6.4 | No use case yet. Agents get their spec's tool set. |
| **Dynamic module registration via REST** | 6.6 | Tool modules register at startup. Runtime registration via REST or file watcher deferred to plugin system evolution. |
| **`config/tools/*.yaml` module definitions** | 6.3 | Tool modules are registered in Python. YAML tool definitions deferred to entry-point discovery phase. |
| **File watcher hot-reload for tools** | 6.7 | Reload via REST endpoint. Automatic file watching deferred. |

The current `CapabilitiesRegistry` is designed to support migration to these features without breaking changes — `resolve()` can be extended to call `dispatch()` internally, and `ToolModuleEntry` can be promoted to a class-based `ToolModule` protocol.

---

## 13. Architecture Review Amendments

Amendments based on architect-reviewer findings (2026-03-01):

### Amendment 1: ToolProviderRegistry Subsumed (Finding 3)

The existing `corvus/providers/registry.py` (`ToolProviderRegistry` + `ProviderConfig` + `HealthStatus`) is subsumed into the new `CapabilitiesRegistry`. The `CapabilitiesRegistry` handles both tool resolution AND provider health — one registry, not two. `ToolModuleEntry` includes `requires_env` for availability gating and a `health_check` callable for health status. `HealthStatus` moves to the capabilities module.

The `ToolProviderRegistry` is added to the code deletions list. The `AgentSupervisor` (which currently takes a `ToolProviderRegistry`) will be updated to take the `CapabilitiesRegistry` instead.

### Amendment 2: Prompt Path Anchoring (Finding 4)

`AgentSpec.prompt()` takes a `config_dir: Path` parameter instead of resolving relative to CWD. The `AgentRegistry` passes its own `config_dir` when resolving prompts, ensuring consistent behavior in Docker, local dev, and tests.

### Amendment 3: Schema Migration Specified (Finding 5)

Concrete column mappings added in section 7.5. Includes backup step, UUID generation for `record_id`, sensible defaults for new columns (`domain="shared"`, `visibility="shared"`, `importance=0.5`), and FTS index rebuild.

### Amendment 4: Agent-Scoped MCP Server Names (Finding 6)

Memory MCP servers use `memory_{agent_name}` naming (e.g., `memory_personal`, `memory_work`) to prevent key collisions when collecting servers from all agents. Already updated in section 6.2.

### Amendment 5: Session Extraction Identity (Finding 7)

`extract_session_memories()` now receives the primary agent name from `SessionTranscript.primary_agent()` instead of defaulting to "general". Added in section 7.6.

### Amendment 6: Feature Flag for Safe Switchover (Finding 8)

`USE_AGENTS_HUB` environment variable added to Phase 2. When false, `server.py` uses the old `build_options()`. When true, uses `hub.build_options()`. A comparison test verifies both paths produce equivalent output. The flag is removed in Phase 4 when the old path is deleted.
