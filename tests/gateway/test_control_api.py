"""Behavioral tests for control-plane API endpoints.

Real FastAPI app + real SessionManager SQLite + real BreakGlassManager.
No mocks.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from corvus.api.control import configure, router
from corvus.break_glass import BreakGlassManager
from corvus.gateway.control_plane import BreakGlassSessionRegistry, DispatchControlRegistry
from corvus.session_manager import SessionManager

_AUTH_HEADERS = {"X-Remote-User": "testuser"}


def _seed_session_graph(session_mgr: SessionManager) -> tuple[str, str, str]:
    """Seed one session, one dispatch, and one run."""
    session_id = "sess-control-1"
    dispatch_id = "disp-control-1"
    run_id = "run-control-1"
    now = datetime.now(UTC)
    session_mgr.start(session_id, user="testuser", started_at=now)
    session_mgr.create_dispatch(
        dispatch_id,
        session_id=session_id,
        turn_id="turn-1",
        user="testuser",
        prompt="test",
        dispatch_mode="parallel",
        target_agents=["work"],
        status="running",
        created_at=now,
    )
    session_mgr.start_agent_run(
        run_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        turn_id="turn-1",
        agent="work",
        status="executing",
        started_at=now,
    )
    return session_id, dispatch_id, run_id


def _build_client(tmp_path: Path) -> tuple[TestClient, SessionManager, DispatchControlRegistry]:
    db_path = tmp_path / "control.sqlite"
    session_mgr = SessionManager(db_path=db_path)
    dispatch_controls = DispatchControlRegistry()
    bg_mgr = BreakGlassManager(config_dir=tmp_path / ".claw")
    bg_mgr.set_passphrase("pass-123")
    bg_sessions = BreakGlassSessionRegistry(bg_mgr, default_ttl_minutes=15)

    configure(session_mgr, dispatch_controls, bg_sessions)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, headers=_AUTH_HEADERS)
    return client, session_mgr, dispatch_controls


class TestControlAPI:
    def test_dispatch_interrupt_active(self, tmp_path: Path):
        client, session_mgr, dispatch_controls = _build_client(tmp_path)
        _session_id, dispatch_id, _run_id = _seed_session_graph(session_mgr)
        interrupt_event = asyncio.Event()
        dispatch_controls.register(
            dispatch_id=dispatch_id,
            session_id="sess-control-1",
            user="testuser",
            turn_id="turn-1",
            interrupt_event=interrupt_event,
        )

        resp = client.post(f"/api/dispatch/{dispatch_id}/interrupt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "interrupt_requested"
        assert body["active"] is True
        assert interrupt_event.is_set()
        assert session_mgr.get_dispatch(dispatch_id)["status"] == "interrupted"

    def test_run_interrupt_active(self, tmp_path: Path):
        client, session_mgr, dispatch_controls = _build_client(tmp_path)
        _session_id, dispatch_id, run_id = _seed_session_graph(session_mgr)
        interrupt_event = asyncio.Event()
        dispatch_controls.register(
            dispatch_id=dispatch_id,
            session_id="sess-control-1",
            user="testuser",
            turn_id="turn-1",
            interrupt_event=interrupt_event,
        )

        resp = client.post(f"/api/runs/{run_id}/interrupt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "interrupt_requested"
        assert body["active"] is True
        assert body["dispatch_id"] == dispatch_id
        assert interrupt_event.is_set()
        assert session_mgr.get_run(run_id)["status"] == "interrupted"

    def test_dispatch_interrupt_not_active(self, tmp_path: Path):
        client, session_mgr, _dispatch_controls = _build_client(tmp_path)
        _session_id, dispatch_id, _run_id = _seed_session_graph(session_mgr)

        resp = client.post(f"/api/dispatch/{dispatch_id}/interrupt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_active"
        assert body["active"] is False

    def test_break_glass_activate_status_deactivate(self, tmp_path: Path):
        client, session_mgr, _dispatch_controls = _build_client(tmp_path)
        session_id, _dispatch_id, _run_id = _seed_session_graph(session_mgr)

        denied = client.post(
            "/api/break-glass/activate",
            json={"session_id": session_id, "passphrase": "wrong"},
        )
        assert denied.status_code == 403
        assert denied.json()["status"] == "denied"

        activated = client.post(
            "/api/break-glass/activate",
            json={"session_id": session_id, "passphrase": "pass-123", "ttl_minutes": 5},
        )
        assert activated.status_code == 200
        body = activated.json()
        assert body["status"] == "active"
        assert body["session_id"] == session_id
        assert body["expires_at"] is not None

        status = client.get("/api/break-glass/status", params={"session_id": session_id})
        assert status.status_code == 200
        status_body = status.json()
        assert status_body["active"] is True
        assert status_body["session_id"] == session_id
        assert status_body["has_passphrase"] is True

        deactivated = client.post("/api/break-glass/deactivate", json={"session_id": session_id})
        assert deactivated.status_code == 200
        assert deactivated.json()["status"] == "deactivated"

        status_after = client.get("/api/break-glass/status", params={"session_id": session_id})
        assert status_after.status_code == 200
        assert status_after.json()["active"] is False

    def test_active_dispatch_listing_is_user_scoped(self, tmp_path: Path):
        client, session_mgr, dispatch_controls = _build_client(tmp_path)
        _session_id, dispatch_id, _run_id = _seed_session_graph(session_mgr)
        interrupt_event = asyncio.Event()
        dispatch_controls.register(
            dispatch_id=dispatch_id,
            session_id="sess-control-1",
            user="testuser",
            turn_id="turn-1",
            interrupt_event=interrupt_event,
        )
        dispatch_controls.register(
            dispatch_id="disp-control-other",
            session_id="sess-other",
            user="someone-else",
            turn_id="turn-2",
            interrupt_event=asyncio.Event(),
        )

        resp = client.get("/api/dispatch/active")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["dispatch_id"] == dispatch_id
