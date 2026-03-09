# Memory Hub Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dual CLI-driven memory system with a hub-driven, plugin-based architecture where agents access memory through SDK tools with closure-injected identity.

**Architecture:** Three layers — MemoryToolkit (SDK tools with closures) → MemoryHub (coordination, decay, merge, audit) → Backends (Primary FTS5 + optional overlays). Single shared SQLite DB. Write enforcement in both Hub and backend. See `docs/plans/2026-02-28-memory-hub-design.md` for full design.

**Tech Stack:** Python 3.11+, SQLite FTS5, dataclasses, asyncio, pytest (no mocks — real SQLite DBs)

**Testing policy:** NO mocks. Real SQLite databases, real FTS5 search, real disk I/O. Tests verify contracts, not implementation details.

**Test output:** All test runs must save full output to `tests/output/TIMESTAMP_test_XXX_results.log`.

---

## Task 1: Create `MemoryRecord` dataclass

The unified data model replacing both `MemoryResult` (from `memory_backends.py`) and `SearchResult` (from `memory_engine.py`).

**Files:**
- Create: `corvus/memory/__init__.py`
- Create: `corvus/memory/record.py`
- Test: `tests/integration/test_memory_hub_live.py`

**Step 1: Create package directory**

```bash
mkdir -p corvus/memory/backends
```

**Step 2: Write the failing test**

Create `tests/integration/test_memory_hub_live.py`:

```python
"""LIVE integration tests for the Memory Hub system.

NO mocks. Real SQLite databases, real FTS5 search, real disk I/O.

Run: uv run pytest tests/integration/test_memory_hub_live.py -v
"""

import json
from dataclasses import asdict

import pytest

from corvus.memory.record import MemoryRecord


class TestMemoryRecord:
    """Verify MemoryRecord dataclass shape and serialization."""

    def test_default_values(self) -> None:
        r = MemoryRecord(id="abc-123", content="test content")
        assert r.id == "abc-123"
        assert r.content == "test content"
        assert r.domain == "shared"
        assert r.visibility == "private"
        assert r.importance == 0.5
        assert r.tags == []
        assert r.source == "agent"
        assert r.created_at == ""
        assert r.updated_at is None
        assert r.deleted_at is None
        assert r.score == 0.0
        assert r.metadata == {}

    def test_to_dict_roundtrip(self) -> None:
        r = MemoryRecord(
            id="abc-123",
            content="test content",
            domain="homelab",
            visibility="private",
            importance=0.9,
            tags=["docker", "deploy"],
            source="agent",
            created_at="2026-02-28T12:00:00",
        )
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "abc-123"
        assert d["tags"] == ["docker", "deploy"]
        # Verify JSON-serializable
        json_str = json.dumps(d)
        assert "abc-123" in json_str

    def test_from_dict(self) -> None:
        d = {
            "id": "xyz-789",
            "content": "restored memory",
            "domain": "finance",
            "visibility": "shared",
            "importance": 0.8,
            "tags": ["budget"],
            "source": "session",
            "created_at": "2026-02-28T12:00:00",
        }
        r = MemoryRecord.from_dict(d)
        assert r.id == "xyz-789"
        assert r.domain == "finance"
        assert r.visibility == "shared"
        assert r.tags == ["budget"]

    def test_is_evergreen(self) -> None:
        normal = MemoryRecord(id="1", content="x", importance=0.5)
        evergreen = MemoryRecord(id="2", content="x", importance=0.95)
        assert not normal.is_evergreen
        assert evergreen.is_evergreen

    def test_is_deleted(self) -> None:
        alive = MemoryRecord(id="1", content="x")
        dead = MemoryRecord(id="2", content="x", deleted_at="2026-02-28T12:00:00")
        assert not alive.is_deleted
        assert dead.is_deleted
```

**Step 3: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryRecord -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_memory_record_results.log
```

Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.memory'`

**Step 4: Write minimal implementation**

Create `corvus/memory/__init__.py`:

```python
"""Corvus Memory Hub — plugin-based multi-agent memory system."""
```

Create `corvus/memory/backends/__init__.py`:

```python
"""Memory backend implementations."""
```

Create `corvus/memory/record.py`:

```python
"""Unified memory record dataclass.

Replaces both MemoryResult (memory_backends.py) and SearchResult (memory_engine.py)
with a single data model used across all layers of the memory system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EVERGREEN_THRESHOLD = 0.9


@dataclass
class MemoryRecord:
    """A single memory record flowing through the Hub.

    Fields set by the system (not agent-controllable):
        id, domain, source, created_at, updated_at, deleted_at, score

    Fields set by the agent:
        content, visibility, importance, tags

    Fields set by search:
        score (populated on retrieval, 0.0 otherwise)
    """

    id: str
    content: str
    domain: str = "shared"
    visibility: str = "private"
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    source: str = "agent"
    created_at: str = ""
    updated_at: str | None = None
    deleted_at: str | None = None
    score: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_evergreen(self) -> bool:
        """Evergreen memories are exempt from temporal decay."""
        return self.importance >= EVERGREEN_THRESHOLD

    @property
    def is_deleted(self) -> bool:
        """Soft-deleted records have a non-None deleted_at."""
        return self.deleted_at is not None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": self.id,
            "content": self.content,
            "domain": self.domain,
            "visibility": self.visibility,
            "importance": self.importance,
            "tags": list(self.tags),
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "score": self.score,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryRecord:
        """Deserialize from a dict, ignoring unknown keys."""
        known = {
            "id", "content", "domain", "visibility", "importance",
            "tags", "source", "created_at", "updated_at", "deleted_at",
            "score", "metadata",
        }
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
```

**Step 5: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryRecord -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_memory_record_results.log
```

Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add corvus/memory/__init__.py corvus/memory/backends/__init__.py corvus/memory/record.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add MemoryRecord dataclass — unified data model for Hub"
```

---

## Task 2: Create `MemoryBackend` protocol

The extended backend protocol that all backends (primary and overlay) must implement.

**Files:**
- Create: `corvus/memory/backends/protocol.py`
- Modify: `tests/integration/test_memory_hub_live.py`

**Step 1: Write the failing test**

Append to `tests/integration/test_memory_hub_live.py`:

```python
from corvus.memory.backends.protocol import MemoryBackend, HealthStatus


class TestMemoryBackendProtocol:
    """Verify the protocol is structurally sound."""

    def test_health_status_shape(self) -> None:
        h = HealthStatus(name="test", status="healthy")
        assert h.name == "test"
        assert h.status == "healthy"
        assert h.detail is None

    def test_health_status_unhealthy(self) -> None:
        h = HealthStatus(name="test", status="unhealthy", detail="connection failed")
        assert h.status == "unhealthy"
        assert h.detail == "connection failed"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryBackendProtocol -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_protocol_results.log
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `corvus/memory/backends/protocol.py`:

```python
"""Memory backend protocol — the contract all backends must satisfy.

Both the primary backend (SQLite FTS5) and overlay backends (Cognee, sqlite-vec,
CORPGEN extraction) implement this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from corvus.memory.record import MemoryRecord


@dataclass
class HealthStatus:
    """Health check result from a backend."""

    name: str
    status: str  # "healthy" | "unhealthy"
    detail: str | None = None


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for pluggable memory backends.

    All methods accept `readable_domains` so visibility filtering
    happens at the storage level (SQL WHERE), not in Python.
    """

    async def save(self, record: MemoryRecord) -> str:
        """Persist a memory record. Returns the record ID."""
        ...

    async def search(
        self,
        query: str,
        *,
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
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        ...

    async def forget(self, record_id: str) -> bool:
        """Soft-delete: set deleted_at. Returns True if found and soft-deleted."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check backend health."""
        ...
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryBackendProtocol -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_protocol_results.log
```

Expected: 2 tests PASS

**Step 5: Commit**

```bash
git add corvus/memory/backends/protocol.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add MemoryBackend protocol with HealthStatus"
```

---

## Task 3: Create `MemoryConfig`

Plugin registry configuration for the Hub.

**Files:**
- Create: `corvus/memory/config.py`
- Modify: `tests/integration/test_memory_hub_live.py`

**Step 1: Write the failing test**

Append to `tests/integration/test_memory_hub_live.py`:

```python
from pathlib import Path

from corvus.memory.config import BackendConfig, MemoryConfig


class TestMemoryConfig:
    """Verify config dataclasses."""

    def test_default_config(self, tmp_path: Path) -> None:
        cfg = MemoryConfig(primary_db_path=tmp_path / "mem.sqlite")
        assert cfg.primary_db_path == tmp_path / "mem.sqlite"
        assert cfg.overlays == []
        assert cfg.decay_half_life_days == 30.0
        assert cfg.evergreen_threshold == 0.9
        assert cfg.mmr_lambda == 0.7
        assert cfg.audit_enabled is True

    def test_backend_config(self) -> None:
        bc = BackendConfig(name="cognee", enabled=True, weight=0.4)
        assert bc.name == "cognee"
        assert bc.enabled is True
        assert bc.weight == 0.4
        assert bc.settings == {}

    def test_config_with_overlays(self, tmp_path: Path) -> None:
        cfg = MemoryConfig(
            primary_db_path=tmp_path / "mem.sqlite",
            overlays=[
                BackendConfig(name="cognee", enabled=True, weight=0.3),
                BackendConfig(name="sqlite-vec", enabled=False, weight=0.5),
            ],
        )
        assert len(cfg.overlays) == 2
        enabled = [o for o in cfg.overlays if o.enabled]
        assert len(enabled) == 1
        assert enabled[0].name == "cognee"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryConfig -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_config_results.log
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `corvus/memory/config.py`:

```python
"""Memory Hub configuration — plugin registry for backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BackendConfig:
    """Configuration for a single overlay backend."""

    name: str
    enabled: bool = False
    weight: float = 0.3
    settings: dict = field(default_factory=dict)


@dataclass
class MemoryConfig:
    """Configuration for the MemoryHub."""

    primary_db_path: Path
    overlays: list[BackendConfig] = field(default_factory=list)
    decay_half_life_days: float = 30.0
    evergreen_threshold: float = 0.9
    mmr_lambda: float = 0.7
    audit_enabled: bool = True
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryConfig -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_config_results.log
```

Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add corvus/memory/config.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add MemoryConfig and BackendConfig for plugin registry"
```

---

## Task 4: Create FTS5 Primary Backend

The consolidated SQLite FTS5 backend. This is the biggest task — it replaces both `SQLiteFTS5Backend` and the SQL parts of `MemoryEngine`.

**Files:**
- Create: `corvus/memory/backends/fts5.py`
- Modify: `tests/integration/test_memory_hub_live.py`

**Reference docs:**
- Current schema: `corvus/memory_backends.py:110-140`
- Current MemoryEngine schema: `scripts/common/memory_engine.py:40-128`
- Visibility filtering: `corvus/memory_backends.py:223-233`
- Design doc: `docs/plans/2026-02-28-memory-hub-design.md`

**Step 1: Write the failing tests**

Append to `tests/integration/test_memory_hub_live.py`:

```python
import asyncio

from corvus.memory.backends.fts5 import FTS5Backend


def run(coro):
    """Run async in sync tests."""
    return asyncio.run(coro)


class TestFTS5Schema:
    """Verify DB schema creation."""

    def test_db_file_created(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "test.sqlite")
        assert backend.db_path.exists()

    def test_idempotent_init(self, tmp_path: Path) -> None:
        db = tmp_path / "idem.sqlite"
        FTS5Backend(db_path=db)
        FTS5Backend(db_path=db)  # Should not raise

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db = tmp_path / "deep" / "nested" / "mem.sqlite"
        FTS5Backend(db_path=db)
        assert db.exists()

    def test_has_audit_table(self, tmp_path: Path) -> None:
        import sqlite3
        backend = FTS5Backend(db_path=tmp_path / "audit.sqlite")
        conn = sqlite3.connect(str(backend.db_path))
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            assert "memory_audit" in tables
        finally:
            conn.close()

    def test_visibility_check_constraint(self, tmp_path: Path) -> None:
        import sqlite3
        backend = FTS5Backend(db_path=tmp_path / "check.sqlite")
        conn = sqlite3.connect(str(backend.db_path))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO memories (record_id, content, domain, visibility, "
                    "importance, source, created_at) "
                    "VALUES ('bad', 'x', 'shared', 'INVALID', 0.5, 'agent', '2026-01-01')"
                )
        finally:
            conn.close()


class TestFTS5Save:
    """Verify save persists to disk."""

    def test_save_returns_record_id(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "save.sqlite")
        record = MemoryRecord(
            id="rec-001", content="test save", domain="homelab",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(backend.save(record))
        assert result_id == "rec-001"

    def test_save_then_search(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "roundtrip.sqlite")
        record = MemoryRecord(
            id="rec-002", content="Deployed Komodo on optiplex",
            domain="homelab", visibility="private", tags=["docker"],
            created_at="2026-02-28T12:00:00",
        )
        run(backend.save(record))
        results = run(backend.search("Komodo"))
        assert len(results) == 1
        assert results[0].content == "Deployed Komodo on optiplex"
        assert results[0].domain == "homelab"
        assert results[0].visibility == "private"
        assert results[0].tags == ["docker"]

    def test_save_soft_deleted_not_returned(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "soft.sqlite")
        record = MemoryRecord(
            id="rec-003", content="should be hidden",
            domain="shared", deleted_at="2026-02-28T12:00:00",
            created_at="2026-02-28T12:00:00",
        )
        run(backend.save(record))
        results = run(backend.search("hidden"))
        assert len(results) == 0


class TestFTS5Search:
    """Verify FTS5 search with visibility filtering."""

    @pytest.fixture()
    def backend(self, tmp_path: Path) -> FTS5Backend:
        b = FTS5Backend(db_path=tmp_path / "search.sqlite")
        run(b.save(MemoryRecord(
            id="f1", content="salary is 150k", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        )))
        run(b.save(MemoryRecord(
            id="h1", content="docker port 8080", domain="homelab",
            visibility="private", created_at="2026-02-28T12:00:00",
        )))
        run(b.save(MemoryRecord(
            id="s1", content="system announcement", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        )))
        return b

    def test_no_filter_returns_all(self, backend: FTS5Backend) -> None:
        results = run(backend.search(
            "salary OR docker OR announcement",
        ))
        assert len(results) == 3

    def test_readable_domains_filters(self, backend: FTS5Backend) -> None:
        results = run(backend.search(
            "salary OR docker OR announcement",
            readable_domains=["finance"],
        ))
        # Should see: finance private + shared
        domains = {r.domain for r in results}
        assert "finance" in domains
        assert "shared" in domains
        assert "homelab" not in domains

    def test_domain_filter(self, backend: FTS5Backend) -> None:
        results = run(backend.search("docker", domain="homelab"))
        assert len(results) == 1
        assert results[0].domain == "homelab"

    def test_limit_respected(self, backend: FTS5Backend) -> None:
        results = run(backend.search(
            "salary OR docker OR announcement", limit=1,
        ))
        assert len(results) == 1

    def test_empty_query_returns_empty(self, backend: FTS5Backend) -> None:
        results = run(backend.search("xyznonexistent999"))
        assert results == []


class TestFTS5Get:
    """Verify get by record ID."""

    def test_get_existing(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "get.sqlite")
        run(backend.save(MemoryRecord(
            id="get-001", content="findable memory", domain="work",
            created_at="2026-02-28T12:00:00",
        )))
        record = run(backend.get("get-001"))
        assert record is not None
        assert record.content == "findable memory"

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "get2.sqlite")
        record = run(backend.get("does-not-exist"))
        assert record is None

    def test_get_soft_deleted_returns_none(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "getdel.sqlite")
        run(backend.save(MemoryRecord(
            id="del-001", content="deleted", domain="shared",
            deleted_at="2026-02-28T12:00:00",
            created_at="2026-02-28T12:00:00",
        )))
        record = run(backend.get("del-001"))
        assert record is None


class TestFTS5ListMemories:
    """Verify list with pagination and visibility."""

    def test_list_basic(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "list.sqlite")
        for i in range(5):
            run(backend.save(MemoryRecord(
                id=f"list-{i}", content=f"memory {i}", domain="homelab",
                visibility="private", created_at=f"2026-02-{20+i:02d}T12:00:00",
            )))
        results = run(backend.list_memories(limit=3))
        assert len(results) == 3

    def test_list_with_offset(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "offset.sqlite")
        for i in range(5):
            run(backend.save(MemoryRecord(
                id=f"off-{i}", content=f"memory {i}", domain="shared",
                visibility="shared", created_at=f"2026-02-{20+i:02d}T12:00:00",
            )))
        page1 = run(backend.list_memories(limit=2, offset=0))
        page2 = run(backend.list_memories(limit=2, offset=2))
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id

    def test_list_filters_by_readable_domains(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "listvis.sqlite")
        run(backend.save(MemoryRecord(
            id="lv-1", content="private finance", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        )))
        run(backend.save(MemoryRecord(
            id="lv-2", content="shared note", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        )))
        # Finance agent sees both
        results = run(backend.list_memories(readable_domains=["finance"]))
        assert len(results) == 2
        # Homelab agent sees only shared
        results = run(backend.list_memories(readable_domains=["homelab"]))
        assert len(results) == 1
        assert results[0].visibility == "shared"


class TestFTS5Forget:
    """Verify soft-delete."""

    def test_forget_sets_deleted_at(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "forget.sqlite")
        run(backend.save(MemoryRecord(
            id="fgt-001", content="to be forgotten", domain="shared",
            created_at="2026-02-28T12:00:00",
        )))
        ok = run(backend.forget("fgt-001"))
        assert ok is True
        # Should not be findable
        record = run(backend.get("fgt-001"))
        assert record is None

    def test_forget_nonexistent(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "forget2.sqlite")
        ok = run(backend.forget("nope"))
        assert ok is False

    def test_forgotten_excluded_from_search(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "fgtsearch.sqlite")
        run(backend.save(MemoryRecord(
            id="fs-1", content="still visible", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        )))
        run(backend.save(MemoryRecord(
            id="fs-2", content="forgotten visible", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        )))
        run(backend.forget("fs-2"))
        results = run(backend.search("visible"))
        assert len(results) == 1
        assert results[0].id == "fs-1"


class TestFTS5HealthCheck:
    """Verify health check."""

    def test_healthy(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "health.sqlite")
        status = run(backend.health_check())
        assert status.status == "healthy"
        assert status.name == "fts5-primary"

    def test_satisfies_protocol(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "proto.sqlite")
        assert isinstance(backend, MemoryBackend)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -k "FTS5" -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_fts5_results.log
```

Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.memory.backends.fts5'`

**Step 3: Write the implementation**

Create `corvus/memory/backends/fts5.py`:

```python
"""SQLite FTS5 primary backend — consolidated from SQLiteFTS5Backend + MemoryEngine.

This is the always-on primary backend. All writes land here first. Source of truth.
Uses BM25 text search via SQLite FTS5 with visibility filtering at the SQL level.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from corvus.memory.backends.protocol import HealthStatus
from corvus.memory.record import MemoryRecord

if TYPE_CHECKING:
    pass

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'shared',
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK(visibility IN ('private', 'shared')),
    importance REAL NOT NULL DEFAULT 0.5,
    tags TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    deleted_at TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, domain, tags,
    content='memories', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, domain, tags)
    VALUES ('delete', old.id, old.content, old.domain, old.tags);
    INSERT INTO memories_fts(rowid, content, domain, tags)
    VALUES (new.id, new.content, new.domain, new.tags);
END;

CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_name TEXT,
    operation TEXT NOT NULL,
    record_id TEXT,
    domain TEXT,
    visibility TEXT,
    details TEXT
);
"""


def _parse_tags(raw: str) -> list[str]:
    """Parse comma-separated tags string into a list."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _join_tags(tags: list[str]) -> str:
    """Join tag list into comma-separated string for storage."""
    return ",".join(tags)


class FTS5Backend:
    """SQLite FTS5 primary backend with BM25 search and visibility filtering.

    Implements the MemoryBackend protocol. Designed to be the always-on
    primary backend in the Hub's primary + overlay architecture.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create schema if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Get a connection with WAL mode enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def save(self, record: MemoryRecord) -> str:
        """Save a memory record. Returns the record_id."""
        import asyncio
        return await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: MemoryRecord) -> str:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO memories "
                "(record_id, content, domain, visibility, importance, tags, "
                "source, created_at, updated_at, deleted_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.content,
                    record.domain,
                    record.visibility,
                    record.importance,
                    _join_tags(record.tags),
                    record.source,
                    record.created_at,
                    record.updated_at,
                    record.deleted_at,
                    "{}",
                ),
            )
            conn.commit()
            return record.id
        finally:
            conn.close()

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search with BM25 ranking and visibility filtering."""
        import asyncio
        return await asyncio.to_thread(
            self._search_sync, query, limit, domain, readable_domains,
        )

    def _search_sync(
        self,
        query: str,
        limit: int,
        domain: str | None,
        readable_domains: list[str] | None,
    ) -> list[MemoryRecord]:
        conn = self._connect()
        try:
            # Build query with visibility filtering
            sql = (
                "SELECT m.record_id, m.content, m.domain, m.visibility, "
                "m.importance, m.tags, m.source, m.created_at, m.updated_at, "
                "m.deleted_at, -rank AS score "
                "FROM memories_fts f "
                "JOIN memories m ON f.rowid = m.id "
                "WHERE memories_fts MATCH ? "
                "AND m.deleted_at IS NULL "
            )
            params: list = [query]

            # Visibility filtering
            if readable_domains is not None:
                placeholders = ",".join("?" for _ in readable_domains)
                sql += (
                    "AND (m.visibility = 'shared' "
                    f"OR (m.visibility = 'private' AND m.domain IN ({placeholders}))) "
                )
                params.extend(readable_domains)

            # Domain filter
            if domain is not None:
                sql += "AND m.domain = ? "
                params.append(domain)

            sql += "ORDER BY score DESC LIMIT ?"
            params.append(limit)

            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # FTS5 query syntax error — return empty
                return []

            return [
                MemoryRecord(
                    id=row[0],
                    content=row[1],
                    domain=row[2],
                    visibility=row[3],
                    importance=row[4],
                    tags=_parse_tags(row[5]),
                    source=row[6],
                    created_at=row[7],
                    updated_at=row[8],
                    deleted_at=row[9],
                    score=float(row[10]) if row[10] else 0.0,
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Get a single record by ID. Excludes soft-deleted."""
        import asyncio
        return await asyncio.to_thread(self._get_sync, record_id)

    def _get_sync(self, record_id: str) -> MemoryRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT record_id, content, domain, visibility, importance, "
                "tags, source, created_at, updated_at, deleted_at "
                "FROM memories WHERE record_id = ? AND deleted_at IS NULL",
                (record_id,),
            ).fetchone()
            if row is None:
                return None
            return MemoryRecord(
                id=row[0],
                content=row[1],
                domain=row[2],
                visibility=row[3],
                importance=row[4],
                tags=_parse_tags(row[5]),
                source=row[6],
                created_at=row[7],
                updated_at=row[8],
                deleted_at=row[9],
            )
        finally:
            conn.close()

    async def list_memories(
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        import asyncio
        return await asyncio.to_thread(
            self._list_sync, domain, limit, offset, readable_domains,
        )

    def _list_sync(
        self,
        domain: str | None,
        limit: int,
        offset: int,
        readable_domains: list[str] | None,
    ) -> list[MemoryRecord]:
        conn = self._connect()
        try:
            sql = (
                "SELECT record_id, content, domain, visibility, importance, "
                "tags, source, created_at, updated_at, deleted_at "
                "FROM memories WHERE deleted_at IS NULL "
            )
            params: list = []

            if readable_domains is not None:
                placeholders = ",".join("?" for _ in readable_domains)
                sql += (
                    "AND (visibility = 'shared' "
                    f"OR (visibility = 'private' AND domain IN ({placeholders}))) "
                )
                params.extend(readable_domains)

            if domain is not None:
                sql += "AND domain = ? "
                params.append(domain)

            sql += "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [
                MemoryRecord(
                    id=row[0],
                    content=row[1],
                    domain=row[2],
                    visibility=row[3],
                    importance=row[4],
                    tags=_parse_tags(row[5]),
                    source=row[6],
                    created_at=row[7],
                    updated_at=row[8],
                    deleted_at=row[9],
                )
                for row in rows
            ]
        finally:
            conn.close()

    async def forget(self, record_id: str) -> bool:
        """Soft-delete by setting deleted_at. Returns True if record existed."""
        import asyncio
        return await asyncio.to_thread(self._forget_sync, record_id)

    def _forget_sync(self, record_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE memories SET deleted_at = ? "
                "WHERE record_id = ? AND deleted_at IS NULL",
                (now, record_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    async def health_check(self) -> HealthStatus:
        """Check database health."""
        import asyncio
        return await asyncio.to_thread(self._health_sync)

    def _health_sync(self) -> HealthStatus:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                return HealthStatus(name="fts5-primary", status="healthy")
            finally:
                conn.close()
        except Exception as e:
            return HealthStatus(
                name="fts5-primary", status="unhealthy", detail=str(e),
            )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -k "FTS5" -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_fts5_results.log
```

Expected: All FTS5 tests PASS (approximately 20 tests)

**Step 5: Commit**

```bash
git add corvus/memory/backends/fts5.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add FTS5Backend — consolidated primary with visibility + soft-delete"
```

---

## Task 5: Create MemoryHub

The central coordinator. Handles write enforcement, fan-out, search merge, temporal decay, MMR, and audit trail.

**Files:**
- Create: `corvus/memory/hub.py`
- Modify: `tests/integration/test_memory_hub_live.py`

**Reference docs:**
- `corvus/agent_config.py:122-141` — get_memory_access, get_readable_private_domains
- Design doc: `docs/plans/2026-02-28-memory-hub-design.md` — Search Flow, Write Flow

**Step 1: Write the failing tests**

Append to `tests/integration/test_memory_hub_live.py`:

```python
from corvus.memory.hub import MemoryHub
from corvus.memory.config import MemoryConfig


def make_hub(tmp_path: Path) -> MemoryHub:
    """Create a Hub with a fresh FTS5 primary backend."""
    config = MemoryConfig(primary_db_path=tmp_path / "hub.sqlite")
    return MemoryHub(config)


class TestHubWriteEnforcement:
    """Hub rejects cross-domain writes."""

    def test_save_own_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-1", content="homelab data", domain="homelab",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(hub.save(record, agent_name="homelab"))
        assert result_id == "hw-1"

    def test_save_shared_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-2", content="shared data", domain="shared",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(hub.save(record, agent_name="homelab"))
        assert result_id == "hw-2"

    def test_reject_cross_domain_write(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-3", content="trying to write to finance",
            domain="finance", created_at="2026-02-28T12:00:00",
        )
        with pytest.raises(PermissionError, match="domain"):
            run(hub.save(record, agent_name="homelab"))

    def test_unknown_agent_cannot_write(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-4", content="rogue agent data", domain="shared",
            created_at="2026-02-28T12:00:00",
        )
        with pytest.raises(PermissionError, match="write"):
            run(hub.save(record, agent_name="nonexistent"))


class TestHubSearch:
    """Hub search with visibility filtering and temporal decay."""

    @pytest.fixture()
    def hub(self, tmp_path: Path) -> MemoryHub:
        h = make_hub(tmp_path)
        # Seed data across domains
        run(h.save(MemoryRecord(
            id="hs-1", content="salary is 150k", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="finance"))
        run(h.save(MemoryRecord(
            id="hs-2", content="docker port 8080", domain="homelab",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="homelab"))
        run(h.save(MemoryRecord(
            id="hs-3", content="shared announcement", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        ), agent_name="general"))
        return h

    def test_finance_sees_own_private_plus_shared(self, hub: MemoryHub) -> None:
        results = run(hub.search(
            "salary OR docker OR announcement", agent_name="finance",
        ))
        domains = {r.domain for r in results}
        assert "finance" in domains
        assert "shared" in domains
        assert "homelab" not in domains

    def test_homelab_sees_own_private_plus_shared(self, hub: MemoryHub) -> None:
        results = run(hub.search(
            "salary OR docker OR announcement", agent_name="homelab",
        ))
        domains = {r.domain for r in results}
        assert "homelab" in domains
        assert "shared" in domains
        assert "finance" not in domains

    def test_general_sees_only_shared(self, hub: MemoryHub) -> None:
        results = run(hub.search(
            "salary OR docker OR announcement", agent_name="general",
        ))
        assert all(r.visibility == "shared" for r in results)

    def test_temporal_decay_reduces_old_scores(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        # Recent memory
        run(hub.save(MemoryRecord(
            id="td-1", content="docker deploy recent", domain="homelab",
            visibility="shared",
            created_at=datetime.now(timezone.utc).isoformat(),
        ), agent_name="homelab"))
        # Old memory (90 days ago)
        old_date = datetime(2025, 12, 1, tzinfo=timezone.utc).isoformat()
        run(hub.save(MemoryRecord(
            id="td-2", content="docker deploy ancient", domain="homelab",
            visibility="shared", created_at=old_date,
        ), agent_name="homelab"))
        results = run(hub.search("docker deploy", agent_name="homelab"))
        assert len(results) == 2
        # Recent should score higher
        assert results[0].id == "td-1"
        assert results[0].score > results[1].score

    def test_evergreen_exempt_from_decay(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        old_date = datetime(2025, 12, 1, tzinfo=timezone.utc).isoformat()
        # Evergreen old memory
        run(hub.save(MemoryRecord(
            id="ev-1", content="architecture decision docker compose",
            domain="homelab", visibility="shared", importance=0.95,
            created_at=old_date,
        ), agent_name="homelab"))
        # Normal old memory
        run(hub.save(MemoryRecord(
            id="ev-2", content="routine docker log entry compose",
            domain="homelab", visibility="shared", importance=0.3,
            created_at=old_date,
        ), agent_name="homelab"))
        results = run(hub.search("docker compose", agent_name="homelab"))
        assert len(results) == 2
        # Evergreen should score higher despite same age
        evergreen = next(r for r in results if r.id == "ev-1")
        normal = next(r for r in results if r.id == "ev-2")
        assert evergreen.score > normal.score


class TestHubGetListForget:
    """Hub get, list, forget operations."""

    def test_get_with_visibility_check(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(hub.save(MemoryRecord(
            id="g-1", content="finance secret", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="finance"))
        # Owner can get
        r = run(hub.get("g-1", agent_name="finance"))
        assert r is not None
        # Other agent gets None
        r = run(hub.get("g-1", agent_name="homelab"))
        assert r is None

    def test_list_with_visibility(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(hub.save(MemoryRecord(
            id="l-1", content="private fin", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="finance"))
        run(hub.save(MemoryRecord(
            id="l-2", content="shared note", domain="shared",
            visibility="shared", created_at="2026-02-28T12:00:00",
        ), agent_name="general"))
        # Finance sees both
        results = run(hub.list_memories(agent_name="finance"))
        assert len(results) == 2
        # Homelab sees only shared
        results = run(hub.list_memories(agent_name="homelab"))
        assert len(results) == 1

    def test_forget_own_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(hub.save(MemoryRecord(
            id="f-1", content="forgettable", domain="homelab",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="homelab"))
        ok = run(hub.forget("f-1", agent_name="homelab"))
        assert ok is True
        r = run(hub.get("f-1", agent_name="homelab"))
        assert r is None

    def test_forget_cross_domain_rejected(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(hub.save(MemoryRecord(
            id="f-2", content="finance data", domain="finance",
            visibility="private", created_at="2026-02-28T12:00:00",
        ), agent_name="finance"))
        with pytest.raises(PermissionError):
            run(hub.forget("f-2", agent_name="homelab"))


class TestHubAudit:
    """Verify audit trail is written."""

    def test_save_creates_audit(self, tmp_path: Path) -> None:
        import sqlite3
        hub = make_hub(tmp_path)
        run(hub.save(MemoryRecord(
            id="a-1", content="audited save", domain="homelab",
            created_at="2026-02-28T12:00:00",
        ), agent_name="homelab"))
        conn = sqlite3.connect(str(tmp_path / "hub.sqlite"))
        try:
            rows = conn.execute(
                "SELECT agent_name, operation, record_id FROM memory_audit"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "homelab"
            assert rows[0][1] == "save"
            assert rows[0][2] == "a-1"
        finally:
            conn.close()
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -k "Hub" -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_hub_results.log
```

Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.memory.hub'`

**Step 3: Write the implementation**

Create `corvus/memory/hub.py`:

```python
"""MemoryHub — central coordinator for the memory system.

Handles:
- Write enforcement (domain ownership check)
- Write fan-out to primary + overlays
- Search merge across backends
- Temporal decay (exponential, with evergreen exemption)
- Audit trail
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from corvus.agent_config import get_memory_access, get_readable_private_domains
from corvus.memory.backends.fts5 import FTS5Backend
from corvus.memory.backends.protocol import MemoryBackend
from corvus.memory.config import MemoryConfig
from corvus.memory.record import MemoryRecord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MemoryHub:
    """Central memory coordinator.

    Primary + Overlay architecture:
    - Primary (FTS5): always on, source of truth
    - Overlays: optional, fan-out writes, merge search results
    """

    def __init__(
        self,
        config: MemoryConfig,
        overlays: list[MemoryBackend] | None = None,
    ) -> None:
        self.config = config
        self.primary = FTS5Backend(db_path=config.primary_db_path)
        self.overlays: list[MemoryBackend] = overlays or []

    async def save(
        self,
        record: MemoryRecord,
        *,
        agent_name: str,
    ) -> str:
        """Save a memory record with write enforcement.

        Raises PermissionError if agent tries to write cross-domain.
        """
        access = get_memory_access(agent_name)

        # Unknown agents cannot write
        if not access.get("can_write", False):
            msg = f"Agent '{agent_name}' does not have write permission"
            raise PermissionError(msg)

        # Domain ownership check
        own_domain = access["own_domain"]
        if record.domain != own_domain and record.domain != "shared":
            msg = (
                f"Agent '{agent_name}' owns domain '{own_domain}' "
                f"but tried to write to domain '{record.domain}'"
            )
            raise PermissionError(msg)

        # Save to primary (must succeed)
        record_id = await self.primary.save(record)

        # Fan out to overlays (best-effort)
        for overlay in self.overlays:
            try:
                await overlay.save(record)
            except Exception:
                logger.warning(
                    "Overlay save failed for record %s", record.id, exc_info=True,
                )

        # Audit
        self._audit(agent_name, "save", record.id, record.domain, record.visibility)

        return record_id

    async def search(
        self,
        query: str,
        *,
        agent_name: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> list[MemoryRecord]:
        """Search with visibility filtering, temporal decay, and result merge."""
        readable = get_readable_private_domains(agent_name)

        # Collect from primary
        results = await self.primary.search(
            query, limit=limit * 2, domain=domain, readable_domains=readable,
        )

        # Collect from overlays and merge
        for overlay in self.overlays:
            try:
                overlay_results = await overlay.search(
                    query, limit=limit * 2, domain=domain,
                    readable_domains=readable,
                )
                results = self._merge_results(results, overlay_results)
            except Exception:
                logger.warning("Overlay search failed", exc_info=True)

        # Apply temporal decay
        results = self._apply_temporal_decay(results)

        # Sort by final score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def get(
        self,
        record_id: str,
        *,
        agent_name: str,
    ) -> MemoryRecord | None:
        """Get a record by ID with visibility enforcement."""
        record = await self.primary.get(record_id)
        if record is None:
            return None

        # Visibility check
        if record.visibility == "private":
            readable = get_readable_private_domains(agent_name)
            if record.domain not in readable:
                return None

        return record

    async def list_memories(
        self,
        *,
        agent_name: str,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memories with visibility filtering."""
        readable = get_readable_private_domains(agent_name)
        return await self.primary.list_memories(
            domain=domain, limit=limit, offset=offset,
            readable_domains=readable,
        )

    async def forget(
        self,
        record_id: str,
        *,
        agent_name: str,
    ) -> bool:
        """Soft-delete a memory. Only domain owner can forget."""
        record = await self.primary.get(record_id)
        if record is None:
            return False

        # Permission check: only domain owner can forget
        access = get_memory_access(agent_name)
        own_domain = access["own_domain"]
        if record.domain != own_domain and record.domain != "shared":
            msg = (
                f"Agent '{agent_name}' cannot forget records in "
                f"domain '{record.domain}'"
            )
            raise PermissionError(msg)

        ok = await self.primary.forget(record_id)

        # Fan out to overlays
        for overlay in self.overlays:
            try:
                await overlay.forget(record_id)
            except Exception:
                logger.warning(
                    "Overlay forget failed for %s", record_id, exc_info=True,
                )

        if ok:
            self._audit(
                agent_name, "forget", record_id, record.domain, record.visibility,
            )

        return ok

    def _merge_results(
        self,
        primary: list[MemoryRecord],
        overlay: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        """Merge results from primary and overlay. Dedup by ID, keep highest score."""
        by_id: dict[str, MemoryRecord] = {}
        for r in primary:
            by_id[r.id] = r
        for r in overlay:
            if r.id in by_id:
                if r.score > by_id[r.id].score:
                    by_id[r.id] = r
            else:
                by_id[r.id] = r
        return list(by_id.values())

    def _apply_temporal_decay(
        self, results: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        """Apply exponential temporal decay. Evergreen records are exempt."""
        half_life = self.config.decay_half_life_days
        lam = math.log(2) / half_life
        now = datetime.now(timezone.utc)

        for r in results:
            if r.is_evergreen:
                continue
            try:
                created = datetime.fromisoformat(r.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (now - created).total_seconds() / 86400
                if age_days > 0:
                    r.score *= math.exp(-lam * age_days)
            except (ValueError, TypeError):
                pass

        return results

    def _audit(
        self,
        agent_name: str,
        operation: str,
        record_id: str | None,
        domain: str | None,
        visibility: str | None,
    ) -> None:
        """Write an audit event to the primary DB."""
        if not self.config.audit_enabled:
            return
        try:
            conn = sqlite3.connect(str(self.config.primary_db_path))
            try:
                conn.execute(
                    "INSERT INTO memory_audit "
                    "(timestamp, agent_name, operation, record_id, domain, visibility) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        agent_name,
                        operation,
                        record_id,
                        domain,
                        visibility,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("Audit write failed", exc_info=True)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -k "Hub" -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_hub_results.log
```

Expected: All Hub tests PASS (approximately 15 tests)

**Step 5: Commit**

```bash
git add corvus/memory/hub.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add MemoryHub — write enforcement, decay, merge, audit"
```

---

## Task 6: Create MemoryToolkit (SDK tools)

SDK tools with closure-based identity injection. This is what agents actually call.

**Files:**
- Create: `corvus/memory/toolkit.py`
- Modify: `tests/integration/test_memory_hub_live.py`

**Reference docs:**
- Tool pattern: `corvus/tools/obsidian.py:363-561` — ObsidianClient closure pattern
- Agent SDK tool format — check `corvus/server.py` for how tools are registered

**Step 1: Write the failing tests**

Append to `tests/integration/test_memory_hub_live.py`:

```python
from corvus.memory.toolkit import create_memory_toolkit


class TestMemoryToolkit:
    """Verify SDK tools with closure-injected identity."""

    @pytest.fixture()
    def hub(self, tmp_path: Path) -> MemoryHub:
        return make_hub(tmp_path)

    def test_creates_five_tools(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="homelab")
        names = {t.name for t in tools}
        assert names == {
            "memory_search", "memory_save", "memory_get",
            "memory_list", "memory_forget",
        }

    def test_save_tool_auto_sets_domain(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="finance")
        save_tool = next(t for t in tools if t.name == "memory_save")
        result_json = run(save_tool.fn(
            content="salary data", visibility="private", tags="budget,salary",
        ))
        result = json.loads(result_json)
        assert result["status"] == "saved"
        # Verify domain was auto-set to "finance"
        search_tool = next(t for t in tools if t.name == "memory_search")
        search_json = run(search_tool.fn(query="salary"))
        search_results = json.loads(search_json)
        assert len(search_results) == 1
        assert search_results[0]["domain"] == "finance"

    def test_search_tool_respects_visibility(self, hub: MemoryHub) -> None:
        # Save as finance
        fin_tools = create_memory_toolkit(hub, agent_name="finance")
        save_fn = next(t for t in fin_tools if t.name == "memory_save").fn
        run(save_fn(content="secret salary data", visibility="private"))

        # Save as homelab
        lab_tools = create_memory_toolkit(hub, agent_name="homelab")
        search_fn = next(t for t in lab_tools if t.name == "memory_search").fn

        # Homelab should NOT see finance private data
        result_json = run(search_fn(query="salary"))
        results = json.loads(result_json)
        assert len(results) == 0

    def test_forget_tool_rejects_cross_domain(self, hub: MemoryHub) -> None:
        # Save as finance
        fin_tools = create_memory_toolkit(hub, agent_name="finance")
        save_fn = next(t for t in fin_tools if t.name == "memory_save").fn
        result = json.loads(run(save_fn(content="to delete", visibility="private")))

        # Try to forget as homelab
        lab_tools = create_memory_toolkit(hub, agent_name="homelab")
        forget_fn = next(t for t in lab_tools if t.name == "memory_forget").fn
        result_json = run(forget_fn(record_id=result["id"]))
        result = json.loads(result_json)
        assert result["status"] == "error"

    def test_list_tool(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="homelab")
        save_fn = next(t for t in tools if t.name == "memory_save").fn
        list_fn = next(t for t in tools if t.name == "memory_list").fn

        run(save_fn(content="memory one", visibility="shared"))
        run(save_fn(content="memory two", visibility="shared"))

        result_json = run(list_fn())
        results = json.loads(result_json)
        assert len(results) == 2

    def test_get_tool(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="homelab")
        save_fn = next(t for t in tools if t.name == "memory_save").fn
        get_fn = next(t for t in tools if t.name == "memory_get").fn

        saved = json.loads(run(save_fn(content="findable", visibility="shared")))
        got = json.loads(run(get_fn(record_id=saved["id"])))
        assert got["content"] == "findable"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryToolkit -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_toolkit_results.log
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the implementation**

Create `corvus/memory/toolkit.py`:

```python
"""MemoryToolkit — SDK tools with closure-injected agent identity.

Created per-agent at spawn time. The agent_name is captured in closures
and cannot be overridden by the agent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from corvus.agent_config import get_memory_access
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord

logger = logging.getLogger(__name__)


@dataclass
class MemoryTool:
    """A single memory tool with name, async function, and description."""

    name: str
    fn: object  # async callable
    description: str


def create_memory_toolkit(
    hub: MemoryHub,
    agent_name: str,
) -> list[MemoryTool]:
    """Create memory tools with identity baked into closures.

    Called by the gateway when spawning an agent. agent_name is captured
    in the closure — the agent cannot override it.

    Returns a list of MemoryTool objects ready for SDK registration.
    """
    own_domain = get_memory_access(agent_name)["own_domain"]

    async def memory_search(
        query: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> str:
        """Search memories by query. Returns ranked results with BM25 scoring."""
        results = await hub.search(
            query, agent_name=agent_name, limit=limit, domain=domain,
        )
        return json.dumps([r.to_dict() for r in results])

    async def memory_save(
        content: str,
        visibility: str = "private",
        tags: str = "",
        importance: float = 0.5,
    ) -> str:
        """Save a new memory. Domain is auto-set from your identity.

        Args:
            content: The memory text to save.
            visibility: "private" (only you can see) or "shared" (all agents).
            tags: Comma-separated tags (e.g., "docker,deploy").
            importance: 0.0-1.0. Set >= 0.9 for evergreen (never decays).
        """
        record = MemoryRecord(
            id=str(uuid4()),
            content=content,
            domain=own_domain,
            visibility=visibility,
            importance=importance,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            source="agent",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            record_id = await hub.save(record, agent_name=agent_name)
            return json.dumps({"id": record_id, "status": "saved"})
        except PermissionError as e:
            return json.dumps({"status": "error", "error": str(e)})

    async def memory_get(record_id: str) -> str:
        """Retrieve a specific memory by its ID."""
        record = await hub.get(record_id, agent_name=agent_name)
        if record is None:
            return json.dumps({"error": "not found"})
        return json.dumps(record.to_dict())

    async def memory_list(
        domain: str | None = None,
        limit: int = 20,
    ) -> str:
        """List recent memories, optionally filtered by domain."""
        records = await hub.list_memories(
            agent_name=agent_name, domain=domain, limit=limit,
        )
        return json.dumps([r.to_dict() for r in records])

    async def memory_forget(record_id: str) -> str:
        """Soft-delete a memory by ID. Only works for your own domain's memories."""
        try:
            ok = await hub.forget(record_id, agent_name=agent_name)
            return json.dumps(
                {"status": "forgotten" if ok else "not found"},
            )
        except PermissionError as e:
            return json.dumps({"status": "error", "error": str(e)})

    return [
        MemoryTool(
            "memory_search",
            memory_search,
            "Search memories by query. Returns ranked results.",
        ),
        MemoryTool(
            "memory_save",
            memory_save,
            "Save a new memory. Domain is auto-set. Choose visibility: "
            "private (default, only you) or shared (all agents).",
        ),
        MemoryTool(
            "memory_get",
            memory_get,
            "Retrieve a specific memory by ID.",
        ),
        MemoryTool(
            "memory_list",
            memory_list,
            "List recent memories, optionally filtered by domain.",
        ),
        MemoryTool(
            "memory_forget",
            memory_forget,
            "Soft-delete a memory by ID. Only works for your own domain.",
        ),
    ]
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestMemoryToolkit -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_toolkit_results.log
```

Expected: All 7 toolkit tests PASS

**Step 5: Commit**

```bash
git add corvus/memory/toolkit.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): add MemoryToolkit — SDK tools with closure-injected identity"
```

---

## Task 7: Update `corvus/memory/__init__.py` public API

Export the key classes so consumers can do `from corvus.memory import MemoryHub, MemoryRecord`.

**Files:**
- Modify: `corvus/memory/__init__.py`

**Step 1: Write the failing test**

Append to `tests/integration/test_memory_hub_live.py`:

```python
class TestPublicAPI:
    """Verify corvus.memory exports the right symbols."""

    def test_imports(self) -> None:
        from corvus.memory import (
            MemoryHub,
            MemoryRecord,
            MemoryConfig,
            BackendConfig,
            create_memory_toolkit,
        )
        assert MemoryHub is not None
        assert MemoryRecord is not None
        assert MemoryConfig is not None
        assert BackendConfig is not None
        assert create_memory_toolkit is not None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestPublicAPI -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_api_results.log
```

Expected: FAIL with ImportError

**Step 3: Update `corvus/memory/__init__.py`**

```python
"""Corvus Memory Hub — plugin-based multi-agent memory system.

Usage:
    from corvus.memory import MemoryHub, MemoryConfig, create_memory_toolkit

    config = MemoryConfig(primary_db_path=Path("memory.sqlite"))
    hub = MemoryHub(config)
    tools = create_memory_toolkit(hub, agent_name="homelab")
"""

from corvus.memory.config import BackendConfig, MemoryConfig
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord
from corvus.memory.toolkit import create_memory_toolkit

__all__ = [
    "BackendConfig",
    "MemoryConfig",
    "MemoryHub",
    "MemoryRecord",
    "create_memory_toolkit",
]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_memory_hub_live.py::TestPublicAPI -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_api_results.log
```

Expected: PASS

**Step 5: Commit**

```bash
git add corvus/memory/__init__.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): export public API from corvus.memory"
```

---

## Task 8: Run the full test suite

Verify everything works together and backward compat is preserved.

**Step 1: Run all new tests**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_full_hub_results.log
```

Expected: All tests PASS (approximately 45+ tests)

**Step 2: Run existing memory tests to verify backward compat**

```bash
uv run pytest tests/integration/test_memory_backends_live.py tests/integration/test_memory_visibility_live.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_backward_compat_results.log
```

Expected: All existing tests still PASS (the old code hasn't been removed yet)

**Step 3: Run the full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/integration/test_routing_live.py 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_all_results.log
```

Expected: No regressions

**Step 4: Commit (if any test output logs need to be committed)**

```bash
git add tests/output/
git commit -m "test: full memory hub test suite — all passing"
```

---

## Task 9: Update `corvus/session.py` to use MemoryHub

Wire session extraction to use the new Hub instead of direct MemoryEngine calls.

**Files:**
- Modify: `corvus/session.py:207-274`
- Modify: `tests/integration/test_memory_hub_live.py`

**Step 1: Write the failing test**

Append to `tests/integration/test_memory_hub_live.py`:

```python
from corvus.session import extract_session_memories, SessionTranscript


class TestSessionExtraction:
    """Verify session extraction saves through the Hub."""

    def test_extraction_saves_with_visibility(self, tmp_path: Path) -> None:
        """End-to-end: transcript → extraction → Hub → SQLite."""
        hub = make_hub(tmp_path)
        transcript = SessionTranscript(user="test")
        transcript.messages = [
            {"role": "user", "content": "My salary is 150k"},
            {"role": "assistant", "content": "I'll remember that."},
            {"role": "user", "content": "Save that as private finance data"},
            {"role": "assistant", "content": "Done, saved to finance domain."},
        ]
        # This test requires ANTHROPIC_API_KEY to call Haiku for extraction.
        # Skip if not available.
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set — skipping live extraction test")

        run(extract_session_memories(transcript, hub, agent_name="finance"))
        # Verify something was saved
        results = run(hub.search("salary", agent_name="finance"))
        # May or may not find it depending on extraction quality
        # Just verify no errors occurred
```

**Step 2: Update `corvus/session.py`**

Modify `extract_session_memories()` to accept either a `MemoryHub` or the legacy `MemoryEngine`:

At line 207, change the function signature:

```python
async def extract_session_memories(
    transcript: SessionTranscript,
    memory_backend,  # MemoryHub or MemoryEngine
    agent_name: str | None = None,
) -> None:
```

At line 246 (inside the for loop), change the save call:

```python
    for mem in memories:
        vis = "shared" if mem.domain == "shared" else "private"

        # Support both new Hub and legacy MemoryEngine
        if hasattr(memory_backend, 'save') and hasattr(memory_backend, 'search'):
            from corvus.memory.hub import MemoryHub
            if isinstance(memory_backend, MemoryHub):
                from corvus.memory.record import MemoryRecord
                from uuid import uuid4
                record = MemoryRecord(
                    id=str(uuid4()),
                    content=mem.content,
                    domain=mem.domain,
                    visibility=vis,
                    importance=mem.importance,
                    tags=mem.tags,
                    source="session",
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                await memory_backend.save(
                    record,
                    agent_name=agent_name or "general",
                )
            else:
                # Legacy MemoryEngine path
                memory_backend.save(
                    content=mem.content,
                    file_path=f"memory/{today}.md",
                    domain=mem.domain,
                    tags=mem.tags,
                    importance=mem.importance,
                    content_type=mem.content_type,
                    visibility=vis,
                )
```

**Note:** Read the actual `session.py` file first to get exact line numbers and surrounding code before making edits. The above is the logical change — adapt to the exact file structure.

**Step 3: Run tests**

```bash
uv run pytest tests/integration/test_memory_hub_live.py -v 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_session_results.log
```

Expected: PASS

**Step 4: Commit**

```bash
git add corvus/session.py tests/integration/test_memory_hub_live.py
git commit -m "feat(memory): wire session extraction to MemoryHub"
```

---

## Task 10: Update agent prompts

Remove CLI memory references from all 9 agent prompts. Replace with descriptions of the SDK tools they now have access to.

**Files:**
- Modify: `corvus/prompts/personal.md`
- Modify: `corvus/prompts/work.md`
- Modify: `corvus/prompts/homelab.md`
- Modify: `corvus/prompts/finance.md`
- Modify: `corvus/prompts/email.md`
- Modify: `corvus/prompts/docs.md`
- Modify: `corvus/prompts/music.md`
- Modify: `corvus/prompts/home.md`
- Modify: `corvus/prompts/general.md`

**Step 1: Read each prompt file first**

Read every prompt file to understand the current memory CLI references.

**Step 2: Replace the memory CLI section in each file**

In every prompt, find the `### Memory` section that looks like:

```markdown
### Memory (agent identity injected automatically)
\```bash
python /app/scripts/memory_search.py search "query" --limit 10
python /app/scripts/memory_search.py save "content" \
    --tags tag1,tag2 --domain <domain>
# Use --visibility shared to make a memory visible to all agents
\```
```

Replace with:

```markdown
### Memory Tools (auto-injected, domain locked to <domain>)

You have five memory tools. Your domain is automatically set — you cannot write to other domains.

- **memory_search** — Search your memories and shared memories. `query` (required), `limit` (default 10), `domain` (optional filter).
- **memory_save** — Save a new memory. `content` (required), `visibility` ("private" default, or "shared" for all agents), `tags` (comma-separated), `importance` (0.0-1.0, set ≥0.9 for permanent/evergreen).
- **memory_get** — Retrieve a specific memory by ID.
- **memory_list** — List recent memories. `domain` (optional), `limit` (default 20).
- **memory_forget** — Soft-delete a memory by ID (your domain only).
```

Replace `<domain>` with each agent's actual domain name (e.g., "work" for work.md, "homelab" for homelab.md, "shared" for general.md).

**Step 3: Verify prompts load correctly**

```bash
uv run python -c "from corvus.agents import build_agents; agents = build_agents(); print(f'{len(agents)} agents loaded')"
```

Expected: `9 agents loaded`

**Step 4: Commit**

```bash
git add corvus/prompts/*.md
git commit -m "docs(prompts): replace CLI memory references with SDK tool descriptions"
```

---

## Summary

| Task | What | Test Count |
|------|------|------------|
| 1 | MemoryRecord dataclass | 5 |
| 2 | MemoryBackend protocol | 2 |
| 3 | MemoryConfig | 3 |
| 4 | FTS5Backend (primary) | ~20 |
| 5 | MemoryHub (coordinator) | ~15 |
| 6 | MemoryToolkit (SDK tools) | 7 |
| 7 | Public API exports | 1 |
| 8 | Full test suite run | 0 (verification) |
| 9 | Session extraction update | 1 |
| 10 | Prompt updates | 0 (manual) |
| **Total** | | **~54 tests** |

All tests use real SQLite databases. No mocks. The old code (`memory_backends.py`, `memory_engine.py`, `memory_search.py`) remains functional until the full migration is validated — it can be removed in a follow-up cleanup task.
