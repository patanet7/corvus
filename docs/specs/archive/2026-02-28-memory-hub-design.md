---
title: "Memory Hub Design: Corvus Multi-Agent Memory System"
type: spec
status: implemented
date: 2026-02-28
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Memory Hub Design — Corvus Multi-Agent Memory System

> **Date:** 2026-02-28
> **Status:** Approved design
> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement the implementation plan derived from this design.

## Goal

Replace the current dual memory system (CLI-driven `memory_search.py` + `MemoryEngine` + `SQLiteFTS5Backend`) with a hub-driven, plugin-based memory architecture where agents access memory through SDK tools with identity baked into closures, not Bash scripts or environment variables.

## Architecture Overview

Three-layer architecture with primary + overlay plugin model.

```
┌──────────────────────────────────────┐
│  MemoryToolkit (Layer 3 — SDK Tools) │
│  search / save / get / list / forget │
│  Agent identity baked into closures  │
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│  MemoryHub (Layer 2 — Coordination)  │
│  Write fan-out, search merge,        │
│  temporal decay, visibility filter,  │
│  write enforcement, audit trail      │
└──────────────┬───────────────────────┘
               │
     ┌─────────┼─────────┬──────────┐
     │         │         │          │
┌────▼───┐ ┌──▼────┐ ┌──▼──────┐ ┌─▼────────┐
│Primary │ │Overlay│ │Overlay  │ │Overlay   │
│SQLite  │ │Cognee │ │sqlite-  │ │CORPGEN   │
│FTS5    │ │Graph  │ │vec      │ │Extraction│
│(always)│ │(opt)  │ │(opt)    │ │(opt)     │
└────────┘ └───────┘ └─────────┘ └──────────┘
```

### Identity Flow

Gateway spawns agent → creates `MemoryToolkit(hub, agent_name="finance")` → all tool closures capture `agent_name` → agent cannot override identity → Hub enforces domain ownership and visibility at every operation.

### Plugin Model: Primary + Overlay Registry

- **Primary backend** (SQLite FTS5): Always on. All writes land here first. Source of truth. If overlays die, primary still works.
- **Overlay backends** (Cognee, sqlite-vec, CORPGEN extraction, Mem0): Optional plugins registered via config. Hub fans writes to all enabled overlays (best-effort). Search collects from all, merges algorithmically.
- **Config-driven**: Each overlay can be enabled/disabled without code changes. Plugin registry in `MemoryConfig`.

This is tighter than OpenClaw's approach (which injects results independently into context). Our Hub merges results algorithmically with weighted scoring + dedup + MMR.

---

## Data Model

### MemoryRecord (Unified)

Consolidates the best of `MemoryResult` (from `memory_backends.py`) and `SearchResult` (from `memory_engine.py`) into one dataclass.

```python
@dataclass
class MemoryRecord:
    id: str                          # UUID
    content: str                     # The memory text
    domain: str = "shared"           # finance, homelab, work, shared, etc.
    visibility: str = "private"      # "private" | "shared"
    importance: float = 0.5          # 0.0-1.0; >= 0.9 = evergreen (exempt from decay)
    tags: list[str] = field(default_factory=list)
    source: str = "agent"            # "agent" | "session" | "system"
    created_at: str = ""             # ISO 8601
    updated_at: str | None = None
    deleted_at: str | None = None    # soft-delete (forget sets this)
    score: float = 0.0               # search relevance score (populated on retrieval)
    metadata: dict = field(default_factory=dict)  # backend-specific data
```

### Visibility Rules

| Visibility | Who can read | Who can write |
|-----------|-------------|---------------|
| `"private"` | Only agent whose `own_domain` matches `record.domain` | Only agent whose `own_domain` matches `record.domain` |
| `"shared"` | All agents | Any agent (to `"shared"` domain) or own-domain agent (to own domain) |

### Evergreen Exemption

Records with `importance >= 0.9` are exempt from temporal decay. Use for architectural decisions, critical reference data, user preferences — things that should never fade.

---

## Backend Protocol

Every backend (primary and overlay) implements this protocol:

```python
class MemoryBackend(Protocol):
    async def save(self, record: MemoryRecord) -> str:
        """Persist a memory record. Returns the record ID."""
        ...

    async def search(
        self, query: str, *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search memories. readable_domains enables SQL-level visibility filtering."""
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        ...

    async def list_memories(
        self, *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        ...

    async def forget(self, record_id: str) -> bool:
        """Soft-delete: set deleted_at. Returns True if found and deleted."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check backend health."""
        ...
```

The `readable_domains` parameter pushes visibility filtering into the SQL WHERE clause (not Python-side filtering), so backends never return data the agent shouldn't see.

---

## MemoryHub (Layer 2)

The central coordinator. Handles write enforcement, fan-out, search merge, temporal decay, and audit.

### Write Flow

```
memory_save(content, visibility, tags, importance)
    │
    ▼
MemoryHub.save(record, agent_name)
    │
    ├─ 1. Write enforcement: verify agent owns record.domain (from agent_config)
    │     REJECT if mismatch → return error
    │
    ├─ 2. Save to PRIMARY (must succeed, or operation fails)
    │
    ├─ 3. Fan out to OVERLAYS (best-effort, log failures, don't block)
    │
    └─ 4. Audit event: log {timestamp, agent, op, record_id, domain, visibility}
```

### Search Flow

```
memory_search(query, limit, domain)
    │
    ▼
MemoryHub.search(query, agent_name, limit, domain)
    │
    ├─ 1. Resolve readable_domains from agent_config
    │
    ├─ 2. Collect results from PRIMARY + all healthy OVERLAYS
    │     (each backend filters by readable_domains at SQL level)
    │
    ├─ 3. Weighted merge + dedup (by record.id, highest score wins)
    │     Novel overlay results (graph connections) added to pool
    │
    ├─ 4. Temporal decay: score *= e^(-ln(2)/30 * age_days)
    │     Skip records with importance >= 0.9 (evergreen)
    │
    ├─ 5. MMR diversity re-ranking (lambda=0.7)
    │
    └─ 6. Return top N results
```

### Get/List/Forget

- **get**: Primary only, enforce visibility (agent must be able to read the domain)
- **list**: Primary only, enforce visibility, paginated
- **forget**: Soft-delete on primary + fan out to overlays. Only domain owner can forget.

### Temporal Decay

Start with OpenClaw's exponential decay:

```
decayed_score = score × e^(-ln(2)/30 × age_days)
```

| Age | Retention |
|-----|-----------|
| Today | 100% |
| 7 days | ~84% |
| 30 days | 50% |
| 90 days | 12.5% |
| Evergreen | 100% (exempt) |

**Future evolution**: Add CrewAI-style composite scoring with per-domain configurable weights (semantic × W1 + recency × W2 + importance × W3). This is a Hub config change, not a backend change.

### Plugin Registry (MemoryConfig)

```python
@dataclass
class BackendConfig:
    name: str                    # e.g., "cognee", "sqlite-vec"
    enabled: bool = False
    weight: float = 0.3          # search result weight relative to primary (1.0)
    settings: dict = field(default_factory=dict)

@dataclass
class MemoryConfig:
    primary_db_path: Path
    overlays: list[BackendConfig] = field(default_factory=list)
    decay_half_life_days: float = 30.0
    evergreen_threshold: float = 0.9
    mmr_lambda: float = 0.7
    audit_enabled: bool = True
```

---

## MemoryToolkit (Layer 3 — SDK Tools)

SDK tools with identity baked into closures. Created per-agent at spawn time.

```python
def create_memory_toolkit(hub: MemoryHub, agent_name: str) -> list[Tool]:
    """Create memory tools with identity baked into closures.

    Called by the gateway when spawning an agent. agent_name is captured
    in the closure — the agent cannot override it.
    """
    own_domain = get_memory_access(agent_name)["own_domain"]

    async def memory_search(query: str, limit: int = 10, domain: str | None = None) -> str:
        results = await hub.search(query, agent_name=agent_name, limit=limit, domain=domain)
        return json.dumps([r.to_dict() for r in results])

    async def memory_save(
        content: str,
        visibility: str = "private",
        tags: str = "",
        importance: float = 0.5,
    ) -> str:
        record = MemoryRecord(
            id=str(uuid4()),
            content=content,
            domain=own_domain,        # AUTO-SET from agent identity
            visibility=visibility,
            importance=importance,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            source="agent",
            created_at=datetime.utcnow().isoformat(),
        )
        record_id = await hub.save(record, agent_name=agent_name)
        return json.dumps({"id": record_id, "status": "saved"})

    async def memory_get(record_id: str) -> str:
        record = await hub.get(record_id, agent_name=agent_name)
        if record is None:
            return json.dumps({"error": "not found"})
        return json.dumps(record.to_dict())

    async def memory_list(domain: str | None = None, limit: int = 20) -> str:
        records = await hub.list_memories(agent_name=agent_name, domain=domain, limit=limit)
        return json.dumps([r.to_dict() for r in records])

    async def memory_forget(record_id: str) -> str:
        ok = await hub.forget(record_id, agent_name=agent_name)
        return json.dumps({"status": "forgotten" if ok else "not found"})

    return [
        Tool("memory_search", memory_search, "Search memories by query. Returns ranked results."),
        Tool("memory_save", memory_save, "Save a new memory. Domain is auto-set. Choose visibility: private (default) or shared."),
        Tool("memory_get", memory_get, "Retrieve a specific memory by ID."),
        Tool("memory_list", memory_list, "List recent memories, optionally filtered by domain."),
        Tool("memory_forget", memory_forget, "Soft-delete a memory by ID. Only works for your own domain."),
    ]
```

**Key design decisions:**
- `domain` is NOT a parameter on `memory_save` — it's auto-set from `agent_config`
- Agent controls: `content`, `visibility`, `tags`, `importance`
- Agent cannot control: `domain`, `agent_name`, `source`, `created_at`

---

## Security Model

### Threat Mitigations

| Threat | Mitigation |
|--------|-----------|
| Agent forges identity | Closure injection — `agent_name` baked at spawn, not controllable by agent |
| Agent writes cross-domain | Hub checks `own_domain` before dispatch; backend has `CHECK(visibility IN ('private','shared'))` constraint |
| Agent reads others' privates | SQL WHERE: `visibility='shared' OR (visibility='private' AND domain IN (?,...))` |
| Agent hard-deletes evidence | `forget()` is soft-delete only (`deleted_at`). Hard-delete reserved for future prune agent |
| Overlay injects bad data | Primary is source of truth. Overlays contribute search results only |
| Concurrent write corruption | SQLite WAL mode + Hub serialization for write enforcement |

### Defense in Depth

Write enforcement in **both** layers:
1. **Hub layer**: `MemoryHub.save()` checks `agent_config.get_memory_access(agent_name)["own_domain"]` matches `record.domain`
2. **Backend layer**: FTS5 backend validates domain + visibility at the SQL level

### Audit Trail

Separate `memory_audit` table in the primary SQLite DB:

```sql
CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    operation TEXT NOT NULL,  -- save, search, get, list, forget
    record_id TEXT,
    domain TEXT,
    visibility TEXT,
    details TEXT              -- JSON metadata
)
```

---

## Planned Overlay Backends

### 1. SQLite FTS5 (Primary — always on)
- BM25 keyword search
- Source of truth for all records
- Handles visibility filtering at SQL level
- Consolidated from existing `SQLiteFTS5Backend` + `MemoryEngine`

### 2. sqlite-vec (Overlay — optional)
- Vector similarity search using local embeddings
- Same SQLite database, separate virtual table
- Enables semantic matching across different wording
- Aligned with OpenClaw's local-first approach

### 3. Cognee (Overlay — optional)
- Knowledge graph overlay
- Three-phase integration: Startup (scan+index), Recall (graph search), Index (sync changes)
- Memify pipeline for adaptive pruning and edge reinforcement
- Multi-hop reasoning for complex queries

### 4. CORPGEN-style Extraction (Overlay — optional)
- System-managed memory extraction (not relying on agent judgment)
- Auto-extracts salient facts from agent sessions
- Stores successful execution traces as procedural memory (experiential learning)
- Adaptive summarization of routine observations
- Per Microsoft research: experiential learning provides largest single performance boost (3.5x)

### 5. Mem0 (Overlay — future)
- Triple-scoped vector + graph memory
- Automatic entity extraction and consolidation
- 26% accuracy improvement over OpenAI Memory on LOCOMO benchmark

---

## Migration Plan

### What Gets Consolidated

| Current | Becomes |
|---------|---------|
| `corvus/memory_backends.py` → `SQLiteFTS5Backend` | `corvus/memory/backends/fts5.py` — consolidated primary |
| `corvus/memory_backends.py` → `MemoryBackend` protocol | `corvus/memory/backends/protocol.py` — extended protocol |
| `corvus/memory_backends.py` → `MemoryResult` | `corvus/memory/record.py` → `MemoryRecord` |
| `scripts/common/memory_engine.py` → `MemoryEngine` | Absorbed into `MemoryHub` (merge logic) + `fts5.py` (schema) |
| `scripts/common/memory_engine.py` → `SearchResult` | Replaced by `MemoryRecord` |
| `scripts/memory_search.py` CLI | Replaced by `MemoryToolkit` SDK tools |
| `corvus/agent_config.py` → `MemoryAccess` | Kept as-is (already correct) |

### What Gets Removed

- `scripts/memory_search.py` — replaced by SDK tools
- CLI memory access from agent prompts — replaced by tool descriptions
- `MEMORY_AGENT` env var pattern — replaced by closure injection
- `scripts/common/memory_engine.py` — absorbed into Hub + FTS5 backend

### Backward Compatibility

- Existing SQLite databases work with new schema (idempotent migrations)
- `corvus/session.py` extraction updated to use `MemoryHub.save()` instead of direct engine calls
- Agent prompts updated to describe SDK tools instead of CLI commands

---

## File Structure

```
corvus/memory/
  __init__.py              — Public API: MemoryHub, MemoryRecord, create_memory_toolkit
  hub.py                   — MemoryHub class (coordination, merge, decay, audit)
  record.py                — MemoryRecord dataclass + serialization
  toolkit.py               — create_memory_toolkit() for SDK tool creation
  config.py                — MemoryConfig, BackendConfig dataclasses
  backends/
    __init__.py
    protocol.py            — MemoryBackend protocol (extended)
    fts5.py                — SQLite FTS5 primary backend (consolidated)
    cognee.py              — Cognee overlay backend (stub, enabled later)
    vault.py               — Obsidian vault writer overlay (from existing)
```

---

## Research Basis

This design synthesizes findings from:

- **OpenClaw**: Per-agent SQLite, BM25+vector hybrid, exponential decay with evergreen exemption, exclusive slot + augmentation overlays
- **Cognee**: Knowledge graph overlay, Memify adaptive pruning, three-phase integration
- **Mem0**: Triple-scope isolation, automatic entity extraction, 26% accuracy gain over OpenAI Memory
- **Microsoft CORPGEN (Feb 2026)**: Tiered memory + experiential learning = 3.5x improvement
- **CrewAI**: Composite scoring with configurable weights, RecallFlow pipeline
- **Zep/Graphiti**: Bi-temporal data model, 94.8% accuracy on DMR benchmark
- **Claude Agent SDK**: BetaAbstractMemoryTool pattern, context engineering best practices
- **O'Reilly "Memory Engineering"**: Five pillars — taxonomy, persistence lifecycle, retrieval strategy, coordination/visibility, consistency guarantees
- **2026 consensus**: Hybrid BM25 + vector + graph with weighted scoring; system-managed extraction over agent self-management
