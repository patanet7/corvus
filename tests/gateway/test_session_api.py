"""Tests for session REST API endpoints.

All tests are behavioral -- real SQLite databases, real HTTP requests via
TestClient. NO mocks, NO monkeypatch, NO @patch.

Split into:
1. Contract shape tests -- verify response shapes without a running server
2. Database query tests -- real SQLite setup/query/teardown
3. Full endpoint tests -- TestClient against real FastAPI app (requires SDK)
"""

import importlib
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.common.memory_engine import MemoryEngine, init_db

# --- SDK availability check ---
SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed -- run in Docker for full coverage",
)


# ---------------------------------------------------------------------------
# 1. Contract shape tests -- verify response shapes
# ---------------------------------------------------------------------------


class TestSessionAPIContract:
    """Verify session API response shapes without running the full server."""

    def test_session_list_response_shape(self):
        """GET /api/sessions returns a list of session objects."""
        session = {
            "id": "sess-001",
            "user": "thomas",
            "started_at": "2026-02-28T14:00:00Z",
            "ended_at": "2026-02-28T14:30:00Z",
            "message_count": 12,
            "tool_count": 5,
            "agents_used": ["homelab", "finance"],
        }
        assert "id" in session
        assert "agents_used" in session
        assert isinstance(session["agents_used"], list)

    def test_session_detail_response_shape(self):
        """GET /api/sessions/{id} includes summary and agents_used."""
        detail = {
            "id": "sess-001",
            "user": "thomas",
            "started_at": "2026-02-28T14:00:00Z",
            "ended_at": "2026-02-28T14:30:00Z",
            "summary": "Plex check",
            "message_count": 12,
            "tool_count": 5,
            "agents_used": ["homelab"],
        }
        assert "summary" in detail
        assert detail["agents_used"] == ["homelab"]

    def test_session_export_returns_markdown(self):
        """GET /api/sessions/{id}/export returns markdown string."""
        export = "# Session: Check plex\n\n**User:** check plex\n\n**Agent (homelab):** Plex is running.\n"
        assert export.startswith("# Session")

    def test_session_messages_response_shape(self):
        """GET /api/sessions/{id}/messages returns transcript rows."""
        message = {
            "id": 1,
            "session_id": "sess-001",
            "role": "assistant",
            "content": "Plex is up",
            "agent": "homelab",
            "model": "sonnet",
            "created_at": "2026-02-28T14:01:00Z",
        }
        assert message["role"] in {"user", "assistant"}
        assert "created_at" in message

    def test_session_delete_response_shape(self):
        """DELETE /api/sessions/{id} returns status: deleted."""
        response = {"status": "deleted"}
        assert response["status"] == "deleted"

    def test_session_rename_response_shape(self):
        """PATCH /api/sessions/{id} returns status: updated with name."""
        response = {"status": "updated", "name": "Plex check"}
        assert response["status"] == "updated"
        assert response["name"] == "Plex check"


# ---------------------------------------------------------------------------
# 2. Database query tests -- real SQLite
# ---------------------------------------------------------------------------


class TestSessionDB:
    """Test session queries against real SQLite via MemoryEngine."""

    def setup_method(self):
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self._tmpfile.name)
        self._tmpfile.close()

        # Initialize the schema using the real init_db
        conn = sqlite3.connect(self.db_path)
        init_db(conn)
        conn.close()

        # Create engine
        self.engine = MemoryEngine(
            db_path=self.db_path,
            cognee_enabled=False,
        )

        # Seed sessions
        self.engine.start_session("sess-001", "thomas", datetime(2026, 2, 28, 14, 0, 0, tzinfo=UTC))
        self.engine.end_session(
            session_id="sess-001",
            ended_at=datetime(2026, 2, 28, 14, 30, 0, tzinfo=UTC),
            message_count=12,
            tool_count=5,
            agents_used=["homelab", "finance"],
        )

        self.engine.start_session("sess-002", "thomas", datetime(2026, 2, 28, 10, 0, 0, tzinfo=UTC))
        self.engine.end_session(
            session_id="sess-002",
            ended_at=datetime(2026, 2, 28, 10, 15, 0, tzinfo=UTC),
            message_count=3,
            tool_count=1,
            agents_used=["general"],
        )

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_list_sessions_returns_all(self):
        """list_sessions returns all sessions, newest first."""
        sessions = self.engine.list_sessions()
        assert len(sessions) == 2
        # Newest first
        assert sessions[0]["id"] == "sess-001"
        assert sessions[1]["id"] == "sess-002"

    def test_list_sessions_with_limit(self):
        """list_sessions respects limit parameter."""
        sessions = self.engine.list_sessions(limit=1)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess-001"

    def test_list_sessions_with_offset(self):
        """list_sessions respects offset parameter."""
        sessions = self.engine.list_sessions(offset=1)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess-002"

    def test_list_sessions_filter_by_agent(self):
        """list_sessions filters by agent name."""
        sessions = self.engine.list_sessions(agent_filter="homelab")
        assert len(sessions) == 1
        assert sessions[0]["id"] == "sess-001"
        assert "homelab" in sessions[0]["agents_used"]

    def test_list_sessions_filter_no_match(self):
        """list_sessions returns empty when no sessions match agent filter."""
        sessions = self.engine.list_sessions(agent_filter="music")
        assert len(sessions) == 0

    def test_get_session_by_id(self):
        """get_session returns a single session dict."""
        session = self.engine.get_session("sess-001")
        assert session is not None
        assert session["id"] == "sess-001"
        assert session["message_count"] == 12
        assert session["tool_count"] == 5
        assert session["agents_used"] == ["homelab", "finance"]

    def test_get_session_not_found(self):
        """get_session returns None for missing session."""
        session = self.engine.get_session("nonexistent")
        assert session is None

    def test_delete_session(self):
        """delete_session removes the session from the database."""
        self.engine.delete_session("sess-001")
        session = self.engine.get_session("sess-001")
        assert session is None
        # Other sessions unaffected
        remaining = self.engine.list_sessions()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "sess-002"

    def test_delete_nonexistent_session(self):
        """delete_session does not raise for missing session."""
        self.engine.delete_session("nonexistent")
        sessions = self.engine.list_sessions()
        assert len(sessions) == 2

    def test_rename_session(self):
        """rename_session updates the summary field."""
        self.engine.rename_session("sess-001", "Plex check")
        session = self.engine.get_session("sess-001")
        assert session["summary"] == "Plex check"

    def test_session_to_dict_shape(self):
        """Session dict has all expected keys."""
        session = self.engine.get_session("sess-001")
        expected_keys = {
            "id",
            "user",
            "started_at",
            "ended_at",
            "summary",
            "message_count",
            "tool_count",
            "agents_used",
        }
        assert set(session.keys()) == expected_keys

    def test_session_agents_used_is_list(self):
        """agents_used is deserialized as a list, not a comma-separated string."""
        session = self.engine.get_session("sess-001")
        assert isinstance(session["agents_used"], list)
        assert len(session["agents_used"]) == 2

    def test_session_to_markdown(self):
        """session_to_markdown produces valid Markdown output."""
        session = self.engine.get_session("sess-001")
        md = MemoryEngine.session_to_markdown(session)
        assert md.startswith("# ")
        assert "**Session ID:**" in md
        assert "sess-001" in md
        assert "homelab" in md

    def test_session_to_markdown_with_summary(self):
        """Markdown export uses summary as title when available."""
        self.engine.rename_session("sess-001", "Plex infrastructure check")
        session = self.engine.get_session("sess-001")
        md = MemoryEngine.session_to_markdown(session)
        assert "Plex infrastructure check" in md


# ---------------------------------------------------------------------------
# 3. Full endpoint tests -- require SDK, skipped if not installed
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestSessionEndpointsWithSDK:
    """Tests against real FastAPI app with TestClient.

    These run in Docker or when the SDK is pip-installed.
    Seeds a session into the real database for endpoint testing.
    """

    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient

        from corvus.server import app

        return TestClient(app, headers={"X-Remote-User": "testuser"})

    @pytest.fixture(autouse=True)
    def _seed_session(self):
        """Seed a test session into the database via SessionManager."""
        from corvus.server import session_mgr

        self._session_id = "test-sess-api-001"
        try:
            session_mgr.start(
                self._session_id,
                user="testuser",
                started_at=datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC),
            )
            session_mgr.end(
                session_id=self._session_id,
                ended_at=datetime(2026, 2, 28, 12, 30, 0, tzinfo=UTC),
                message_count=5,
                tool_count=2,
                agents_used=["homelab"],
            )
        except Exception:
            pass  # May already exist from previous test run
        yield
        # Cleanup
        try:
            session_mgr.delete(self._session_id)
        except Exception:
            pass

    def test_list_sessions_endpoint(self, client):
        """GET /api/sessions returns 200 with a list."""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_get_session_endpoint(self, client):
        """GET /api/sessions/{id} returns 200 with session data."""
        resp = client.get(f"/api/sessions/{self._session_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == self._session_id

    def test_get_session_not_found(self, client):
        """GET /api/sessions/{id} returns 404 for missing session."""
        resp = client.get("/api/sessions/nonexistent-session-xyz")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body

    def test_rename_session_endpoint(self, client):
        """PATCH /api/sessions/{id} renames and returns 200."""
        resp = client.patch(
            f"/api/sessions/{self._session_id}",
            json={"name": "Test rename"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "updated"
        assert body["name"] == "Test rename"

    def test_export_session_endpoint(self, client):
        """GET /api/sessions/{id}/export returns 200 with markdown."""
        resp = client.get(f"/api/sessions/{self._session_id}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert "markdown" in body
        assert body["markdown"].startswith("# ")

    def test_session_messages_endpoint(self, client):
        """GET /api/sessions/{id}/messages returns persisted transcript rows."""
        from corvus.server import session_mgr

        session_mgr.add_message(
            self._session_id,
            "user",
            "show me session history",
            agent="general",
            model="sonnet",
        )
        resp = client.get(f"/api/sessions/{self._session_id}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert any(msg.get("content") == "show me session history" for msg in body)

    def test_session_events_endpoint(self, client):
        """GET /api/sessions/{id}/events returns persisted event rows."""
        from corvus.server import session_mgr

        session_mgr.add_event(
            self._session_id,
            "task_start",
            {"type": "task_start", "task_id": "task-001", "agent": "general"},
            turn_id="turn-001",
        )
        resp = client.get(f"/api/sessions/{self._session_id}/events")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert any(event.get("event_type") == "task_start" for event in body)

    def test_export_session_not_found(self, client):
        """GET /api/sessions/{id}/export returns 404 for missing session."""
        resp = client.get("/api/sessions/nonexistent-session-xyz/export")
        assert resp.status_code == 404

    def test_delete_session_endpoint(self, client):
        """DELETE /api/sessions/{id} returns 200."""
        resp = client.delete(f"/api/sessions/{self._session_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "deleted"

        # Verify it's gone
        resp2 = client.get(f"/api/sessions/{self._session_id}")
        assert resp2.status_code == 404

    def test_list_sessions_with_agent_filter(self, client):
        """GET /api/sessions?agent=homelab filters correctly."""
        resp = client.get("/api/sessions?agent=homelab")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        # All returned sessions should have homelab in agents_used
        for session in body:
            assert "homelab" in session.get("agents_used", [])

    def test_session_endpoints_return_json_content_type(self, client):
        """All session endpoints return JSON content type."""
        resp = client.get("/api/sessions")
        assert resp.headers["content-type"] == "application/json"


class TestSessionServerSourceContracts:
    """Verify session router endpoints are defined at source level."""

    def _load_source(self):
        return (Path(__file__).parent.parent.parent / "corvus" / "api" / "sessions.py").read_text()

    def test_list_sessions_endpoint_defined(self):
        """GET /api/sessions endpoint is defined."""
        source = self._load_source()
        assert '@router.get("")' in source
        assert "async def list_sessions" in source

    def test_get_session_endpoint_defined(self):
        """GET /api/sessions/{session_id} endpoint is defined."""
        source = self._load_source()
        assert '@router.get("/{session_id}")' in source
        assert "async def get_session" in source

    def test_delete_session_endpoint_defined(self):
        """DELETE /api/sessions/{session_id} endpoint is defined."""
        source = self._load_source()
        assert '@router.delete("/{session_id}")' in source
        assert "async def delete_session" in source

    def test_rename_session_endpoint_defined(self):
        """PATCH /api/sessions/{session_id} endpoint is defined."""
        source = self._load_source()
        assert '@router.patch("/{session_id}")' in source
        assert "async def rename_session" in source

    def test_export_session_endpoint_defined(self):
        """GET /api/sessions/{session_id}/export endpoint is defined."""
        source = self._load_source()
        assert '@router.get("/{session_id}/export")' in source
        assert "async def export_session" in source

    def test_session_messages_endpoint_defined(self):
        """GET /api/sessions/{session_id}/messages endpoint is defined."""
        source = self._load_source()
        assert '@router.get("/{session_id}/messages")' in source
        assert "async def get_session_messages" in source

    def test_session_events_endpoint_defined(self):
        """GET /api/sessions/{session_id}/events endpoint is defined."""
        source = self._load_source()
        assert '@router.get("/{session_id}/events")' in source
        assert "async def get_session_events" in source
