"""LIVE integration tests for the Memory Hub system.

NO mocks. Real SQLite databases, real FTS5 search, real disk I/O.

Run: uv run pytest tests/integration/test_memory_hub_live.py -v
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from corvus.memory.backends.fts5 import FTS5Backend
from corvus.memory.backends.protocol import HealthStatus, MemoryBackend
from corvus.memory.config import BackendConfig, MemoryConfig
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord
from corvus.memory.toolkit import create_memory_toolkit
from tests.conftest import make_hub, run
from tests.integration.conftest import skip_no_llm


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

    def test_from_dict_missing_required_fields(self) -> None:
        with pytest.raises(ValueError, match="Missing required fields"):
            MemoryRecord.from_dict({"domain": "homelab"})

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

    def test_invalid_visibility_rejected(self) -> None:
        with pytest.raises(ValueError, match="visibility"):
            MemoryRecord(id="1", content="x", visibility="INVALID")


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
        backend = FTS5Backend(db_path=tmp_path / "audit.sqlite")
        conn = sqlite3.connect(str(backend.db_path))
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "memory_audit" in tables
        finally:
            conn.close()

    def test_visibility_check_constraint(self, tmp_path: Path) -> None:
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
            id="rec-001",
            content="test save",
            domain="homelab",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(backend.save(record))
        assert result_id == "rec-001"

    def test_save_duplicate_id_raises(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "dup.sqlite")
        record = MemoryRecord(
            id="dup-001",
            content="first",
            domain="shared",
            created_at="2026-02-28T12:00:00",
        )
        run(backend.save(record))
        with pytest.raises(sqlite3.IntegrityError):
            run(backend.save(record))

    def test_save_then_search(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "roundtrip.sqlite")
        record = MemoryRecord(
            id="rec-002",
            content="Deployed Komodo on optiplex",
            domain="homelab",
            visibility="private",
            tags=["docker"],
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
            id="rec-003",
            content="should be hidden",
            domain="shared",
            deleted_at="2026-02-28T12:00:00",
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
        run(
            b.save(
                MemoryRecord(
                    id="f1",
                    content="salary is 150k",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        run(
            b.save(
                MemoryRecord(
                    id="h1",
                    content="docker port 8080",
                    domain="homelab",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        run(
            b.save(
                MemoryRecord(
                    id="s1",
                    content="system announcement",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        return b

    def test_no_filter_returns_all(self, backend: FTS5Backend) -> None:
        results = run(
            backend.search(
                "salary OR docker OR announcement",
            )
        )
        assert len(results) == 3

    def test_readable_domains_filters(self, backend: FTS5Backend) -> None:
        results = run(
            backend.search(
                "salary OR docker OR announcement",
                readable_domains=["finance"],
            )
        )
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
        results = run(
            backend.search(
                "salary OR docker OR announcement",
                limit=1,
            )
        )
        assert len(results) == 1

    def test_empty_query_returns_empty(self, backend: FTS5Backend) -> None:
        results = run(backend.search("xyznonexistent999"))
        assert results == []


class TestFTS5Get:
    """Verify get by record ID."""

    def test_get_existing(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "get.sqlite")
        run(
            backend.save(
                MemoryRecord(
                    id="get-001",
                    content="findable memory",
                    domain="work",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        record = run(backend.get("get-001"))
        assert record is not None
        assert record.content == "findable memory"

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "get2.sqlite")
        record = run(backend.get("does-not-exist"))
        assert record is None

    def test_get_soft_deleted_returns_none(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "getdel.sqlite")
        run(
            backend.save(
                MemoryRecord(
                    id="del-001",
                    content="deleted",
                    domain="shared",
                    deleted_at="2026-02-28T12:00:00",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        record = run(backend.get("del-001"))
        assert record is None


class TestFTS5ListMemories:
    """Verify list with pagination and visibility."""

    def test_list_basic(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "list.sqlite")
        for i in range(5):
            run(
                backend.save(
                    MemoryRecord(
                        id=f"list-{i}",
                        content=f"memory {i}",
                        domain="homelab",
                        visibility="private",
                        created_at=f"2026-02-{20 + i:02d}T12:00:00",
                    )
                )
            )
        results = run(backend.list_memories(limit=3))
        assert len(results) == 3

    def test_list_with_offset(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "offset.sqlite")
        for i in range(5):
            run(
                backend.save(
                    MemoryRecord(
                        id=f"off-{i}",
                        content=f"memory {i}",
                        domain="shared",
                        visibility="shared",
                        created_at=f"2026-02-{20 + i:02d}T12:00:00",
                    )
                )
            )
        page1 = run(backend.list_memories(limit=2, offset=0))
        page2 = run(backend.list_memories(limit=2, offset=2))
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id

    def test_list_filters_by_readable_domains(self, tmp_path: Path) -> None:
        backend = FTS5Backend(db_path=tmp_path / "listvis.sqlite")
        run(
            backend.save(
                MemoryRecord(
                    id="lv-1",
                    content="private finance",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        run(
            backend.save(
                MemoryRecord(
                    id="lv-2",
                    content="shared note",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
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
        run(
            backend.save(
                MemoryRecord(
                    id="fgt-001",
                    content="to be forgotten",
                    domain="shared",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
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
        run(
            backend.save(
                MemoryRecord(
                    id="fs-1",
                    content="still visible",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
        run(
            backend.save(
                MemoryRecord(
                    id="fs-2",
                    content="forgotten visible",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                )
            )
        )
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


class TestHubWriteEnforcement:
    """Hub rejects cross-domain writes."""

    def test_save_own_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-1",
            content="homelab data",
            domain="homelab",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(hub.save(record, agent_name="homelab"))
        assert result_id == "hw-1"

    def test_save_shared_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-2",
            content="shared data",
            domain="shared",
            created_at="2026-02-28T12:00:00",
        )
        result_id = run(hub.save(record, agent_name="homelab"))
        assert result_id == "hw-2"

    def test_reject_cross_domain_write(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-3",
            content="trying to write to finance",
            domain="finance",
            created_at="2026-02-28T12:00:00",
        )
        with pytest.raises(PermissionError, match="domain"):
            run(hub.save(record, agent_name="homelab"))

    def test_unknown_agent_cannot_write(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        record = MemoryRecord(
            id="hw-4",
            content="rogue agent data",
            domain="shared",
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
        run(
            h.save(
                MemoryRecord(
                    id="hs-1",
                    content="salary is 150k",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="finance",
            )
        )
        run(
            h.save(
                MemoryRecord(
                    id="hs-2",
                    content="docker port 8080",
                    domain="homelab",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="homelab",
            )
        )
        run(
            h.save(
                MemoryRecord(
                    id="hs-3",
                    content="shared announcement",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="general",
            )
        )
        return h

    def test_finance_sees_own_private_plus_shared(self, hub: MemoryHub) -> None:
        results = run(
            hub.search(
                "salary OR docker OR announcement",
                agent_name="finance",
            )
        )
        domains = {r.domain for r in results}
        assert "finance" in domains
        assert "shared" in domains
        assert "homelab" not in domains

    def test_homelab_sees_own_private_plus_shared(self, hub: MemoryHub) -> None:
        results = run(
            hub.search(
                "salary OR docker OR announcement",
                agent_name="homelab",
            )
        )
        domains = {r.domain for r in results}
        assert "homelab" in domains
        assert "shared" in domains
        assert "finance" not in domains

    def test_general_sees_only_shared(self, hub: MemoryHub) -> None:
        results = run(
            hub.search(
                "salary OR docker OR announcement",
                agent_name="general",
            )
        )
        assert all(r.visibility == "shared" for r in results)

    def test_temporal_decay_reduces_old_scores(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        # Recent memory
        run(
            hub.save(
                MemoryRecord(
                    id="td-1",
                    content="docker deploy recent",
                    domain="homelab",
                    visibility="shared",
                    created_at=datetime.now(UTC).isoformat(),
                ),
                agent_name="homelab",
            )
        )
        # Old memory (90 days ago)
        old_date = datetime(2025, 12, 1, tzinfo=UTC).isoformat()
        run(
            hub.save(
                MemoryRecord(
                    id="td-2",
                    content="docker deploy ancient",
                    domain="homelab",
                    visibility="shared",
                    created_at=old_date,
                ),
                agent_name="homelab",
            )
        )
        results = run(hub.search("docker deploy", agent_name="homelab"))
        assert len(results) == 2
        # Recent should score higher
        assert results[0].id == "td-1"
        assert results[0].score > results[1].score

    def test_evergreen_exempt_from_decay(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        old_date = datetime(2025, 12, 1, tzinfo=UTC).isoformat()
        # Evergreen old memory
        run(
            hub.save(
                MemoryRecord(
                    id="ev-1",
                    content="architecture decision docker compose",
                    domain="homelab",
                    visibility="shared",
                    importance=0.95,
                    created_at=old_date,
                ),
                agent_name="homelab",
            )
        )
        # Normal old memory
        run(
            hub.save(
                MemoryRecord(
                    id="ev-2",
                    content="routine docker log entry compose",
                    domain="homelab",
                    visibility="shared",
                    importance=0.3,
                    created_at=old_date,
                ),
                agent_name="homelab",
            )
        )
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
        run(
            hub.save(
                MemoryRecord(
                    id="g-1",
                    content="finance secret",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="finance",
            )
        )
        # Owner can get
        r = run(hub.get("g-1", agent_name="finance"))
        assert r is not None
        # Other agent gets PermissionError
        with pytest.raises(PermissionError, match="does not have access"):
            run(hub.get("g-1", agent_name="homelab"))

    def test_list_with_visibility(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(
            hub.save(
                MemoryRecord(
                    id="l-1",
                    content="private fin",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="finance",
            )
        )
        run(
            hub.save(
                MemoryRecord(
                    id="l-2",
                    content="shared note",
                    domain="shared",
                    visibility="shared",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="general",
            )
        )
        # Finance sees both
        results = run(hub.list_memories(agent_name="finance"))
        assert len(results) == 2
        # Homelab sees only shared
        results = run(hub.list_memories(agent_name="homelab"))
        assert len(results) == 1

    def test_forget_own_domain(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(
            hub.save(
                MemoryRecord(
                    id="f-1",
                    content="forgettable",
                    domain="homelab",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="homelab",
            )
        )
        ok = run(hub.forget("f-1", agent_name="homelab"))
        assert ok is True
        r = run(hub.get("f-1", agent_name="homelab"))
        assert r is None

    def test_forget_cross_domain_rejected(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(
            hub.save(
                MemoryRecord(
                    id="f-2",
                    content="finance data",
                    domain="finance",
                    visibility="private",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="finance",
            )
        )
        with pytest.raises(PermissionError):
            run(hub.forget("f-2", agent_name="homelab"))


class TestHubAudit:
    """Verify audit trail is written."""

    def test_save_creates_audit(self, tmp_path: Path) -> None:
        hub = make_hub(tmp_path)
        run(
            hub.save(
                MemoryRecord(
                    id="a-1",
                    content="audited save",
                    domain="homelab",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="homelab",
            )
        )
        conn = sqlite3.connect(str(tmp_path / "hub.sqlite"))
        try:
            rows = conn.execute("SELECT agent_name, operation, record_id FROM memory_audit").fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "homelab"
            assert rows[0][1] == "save"
            assert rows[0][2] == "a-1"
        finally:
            conn.close()

    def test_audit_disabled_suppresses_writes(self, tmp_path: Path) -> None:
        from tests.conftest import _test_memory_access, _test_readable_domains

        config = MemoryConfig(
            primary_db_path=tmp_path / "noaudit.sqlite",
            audit_enabled=False,
        )
        hub = MemoryHub(
            config,
            get_memory_access_fn=_test_memory_access,
            get_readable_domains_fn=_test_readable_domains,
        )
        run(
            hub.save(
                MemoryRecord(
                    id="na-1",
                    content="no audit",
                    domain="homelab",
                    created_at="2026-02-28T12:00:00",
                ),
                agent_name="homelab",
            )
        )
        conn = sqlite3.connect(str(tmp_path / "noaudit.sqlite"))
        try:
            rows = conn.execute("SELECT COUNT(*) FROM memory_audit").fetchone()
            assert rows[0] == 0
        finally:
            conn.close()


class TestMemoryToolkit:
    """Verify SDK tools with closure-injected identity."""

    @pytest.fixture()
    def hub(self, tmp_path: Path) -> MemoryHub:
        return make_hub(tmp_path)

    def test_creates_five_tools(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="homelab")
        names = {t.name for t in tools}
        assert names == {
            "memory_search",
            "memory_save",
            "memory_get",
            "memory_list",
            "memory_forget",
        }

    def test_save_tool_auto_sets_domain(self, hub: MemoryHub) -> None:
        tools = create_memory_toolkit(hub, agent_name="finance")
        save_tool = next(t for t in tools if t.name == "memory_save")
        result_json = run(
            save_tool.fn(
                content="salary data",
                visibility="private",
                tags="budget,salary",
            )
        )
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


# ---------------------------------------------------------------------------
# Task 7: Public API exports
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify claw.memory exports the right symbols."""

    def test_imports(self) -> None:
        from corvus.memory import (
            BackendConfig,
            MemoryConfig,
            MemoryHub,
            MemoryRecord,
            create_memory_toolkit,
        )

        assert MemoryHub is not None
        assert MemoryRecord is not None
        assert MemoryConfig is not None
        assert BackendConfig is not None
        assert create_memory_toolkit is not None


# ---------------------------------------------------------------------------
# Task 9: Session extraction → MemoryHub wiring
# ---------------------------------------------------------------------------


class TestSessionExtraction:
    """Verify session extraction saves through the Hub."""

    @skip_no_llm
    def test_extraction_saves_with_visibility(
        self,
        tmp_path: Path,
        llm_extractor,
    ) -> None:
        """End-to-end: transcript -> extraction -> Hub -> SQLite.

        Uses Anthropic if ANTHROPIC_API_KEY is set, otherwise falls back
        to Ollama running locally. Skips if neither is available.

        NOTE: This test exercises a real LLM call. Results are
        non-deterministic, so we only verify structural correctness
        (no errors, valid domain/visibility) -- not exact content.
        """
        from corvus.session import SessionTranscript, extract_session_memories

        hub = make_hub(tmp_path)
        transcript = SessionTranscript(user="test")
        transcript.messages = [
            {"role": "user", "content": "My salary is 150k"},
            {"role": "assistant", "content": "I'll remember that."},
            {"role": "user", "content": "Save that as private finance data"},
            {"role": "assistant", "content": "Done, saved to finance domain."},
        ]

        saved = run(
            extract_session_memories(
                transcript,
                hub,
                agent_name="finance",
                llm_extractor=llm_extractor,
            )
        )
        # Verify no errors occurred; extraction may produce 0-5 memories
        # depending on the LLM's interpretation
        assert isinstance(saved, list)
        # If anything was saved, verify it went to the right domain
        for mem in saved:
            assert mem.domain in {
                "finance",
                "shared",
                "personal",
                "work",
                "homelab",
                "email",
                "docs",
                "music",
                "home",
            }

    def test_short_session_returns_empty(self, tmp_path: Path) -> None:
        """Sessions with <2 user messages skip extraction entirely."""
        from corvus.session import SessionTranscript, extract_session_memories

        hub = make_hub(tmp_path)
        transcript = SessionTranscript(user="test")
        transcript.messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]

        result = run(extract_session_memories(transcript, hub, agent_name="finance"))
        assert result == []
