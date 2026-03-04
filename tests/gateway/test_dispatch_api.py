"""Behavioral tests for dispatch/run REST APIs.

These tests hit the real FastAPI app with a real SQLite-backed SessionManager.
No mocks or monkeypatching.
"""

import importlib
import uuid
from datetime import UTC, datetime

import pytest

SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed -- run in Docker for full coverage",
)


@skip_no_sdk
class TestDispatchRunEndpoints:
    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient

        from corvus.server import app

        return TestClient(app, headers={"X-Remote-User": "testuser"})

    @pytest.fixture(autouse=True)
    def _seed_session(self):
        from corvus.server import session_mgr

        self.session_id = f"dispatch-api-{uuid.uuid4()}"
        session_mgr.start(
            self.session_id,
            user="testuser",
            started_at=datetime.now(UTC),
        )
        yield
        try:
            session_mgr.delete(self.session_id)
        except Exception:
            pass

    def test_dispatch_crud(self, client):
        from corvus.server import session_mgr

        create_resp = client.post(
            "/api/dispatch",
            json={
                "session_id": self.session_id,
                "prompt": "check homelab + finance",
                "dispatch_mode": "parallel",
                "target_agents": ["homelab", "finance"],
            },
        )
        assert create_resp.status_code == 201
        dispatch = create_resp.json()
        dispatch_id = dispatch["id"]
        assert dispatch["session_id"] == self.session_id
        assert dispatch["dispatch_mode"] == "parallel"
        assert dispatch["status"] == "queued"

        list_resp = client.get("/api/dispatch")
        assert list_resp.status_code == 200
        rows = list_resp.json()
        assert isinstance(rows, list)
        assert any(row["id"] == dispatch_id for row in rows)

        get_resp = client.get(f"/api/dispatch/{dispatch_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == dispatch_id

        patch_resp = client.patch(
            f"/api/dispatch/{dispatch_id}",
            json={"status": "running"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "running"

        del_resp = client.delete(f"/api/dispatch/{dispatch_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"
        assert session_mgr.get_dispatch(dispatch_id) is None

    def test_dispatch_active_endpoint(self, client):
        """GET /api/dispatch/active returns active dispatches (served by control.py)."""
        resp = client.get("/api/dispatch/active")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_run_crud(self, client):
        from corvus.server import session_mgr

        dispatch_id = str(uuid.uuid4())
        session_mgr.create_dispatch(
            dispatch_id,
            session_id=self.session_id,
            turn_id=str(uuid.uuid4()),
            user="testuser",
            prompt="single run seed",
            dispatch_mode="direct",
            target_agents=["homelab"],
            status="running",
        )

        run_id = str(uuid.uuid4())
        session_mgr.start_agent_run(
            run_id,
            dispatch_id=dispatch_id,
            session_id=self.session_id,
            turn_id=str(uuid.uuid4()),
            agent="homelab",
            backend="claude",
            model="sonnet",
            status="executing",
        )
        session_mgr.add_run_event(
            run_id,
            dispatch_id=dispatch_id,
            session_id=self.session_id,
            turn_id=None,
            event_type="run_phase",
            payload={"type": "run_phase", "phase": "executing"},
        )

        list_resp = client.get("/api/runs")
        assert list_resp.status_code == 200
        rows = list_resp.json()
        assert any(row["id"] == run_id for row in rows)

        get_resp = client.get(f"/api/runs/{run_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == run_id

        events_resp = client.get(f"/api/runs/{run_id}/events")
        assert events_resp.status_code == 200
        events = events_resp.json()
        assert any(event["event_type"] == "run_phase" for event in events)

        patch_resp = client.patch(
            f"/api/runs/{run_id}",
            json={"status": "done", "summary": "completed"},
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["status"] == "done"
        assert patched["summary"] == "completed"

        del_resp = client.delete(f"/api/runs/{run_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"
        assert session_mgr.get_run(run_id) is None
