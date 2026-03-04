"""Behavioral tests for trace observability API endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from corvus.api.traces import configure, router, ws_router
from corvus.config import ALLOWED_USERS
from corvus.gateway.trace_hub import TraceHub
from corvus.session_manager import SessionManager

_AUTH_USER = ALLOWED_USERS[0]
_AUTH_HEADERS = {"X-Remote-User": _AUTH_USER}


def _build_client(tmp_path: Path) -> tuple[TestClient, SessionManager, TraceHub]:
    db_path = tmp_path / "traces.sqlite"
    session_mgr = SessionManager(db_path=db_path)
    trace_hub = TraceHub()
    configure(session_mgr, trace_hub)
    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    client = TestClient(app, headers=_AUTH_HEADERS)
    return client, session_mgr, trace_hub


def _seed_trace(session_mgr: SessionManager, *, session_id: str, user: str, event_type: str, source: str) -> int:
    now = datetime.now(UTC)
    session_mgr.start(session_id, user=user, started_at=now)
    row = session_mgr.add_trace_event(
        source_app=source,
        session_id=session_id,
        hook_event_type=event_type,
        payload={"type": event_type, "summary": f"{event_type} summary"},
        summary=f"{event_type} summary",
        model_name="ollama:qwen3:8b",
    )
    return int(row["id"])


class TestTraceAPI:
    def test_post_trace_event_ingests_and_returns_row(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        session_mgr.start("sess-trace-api-post-1", user=_AUTH_USER, started_at=datetime.now(UTC))

        resp = client.post(
            "/api/traces/events",
            json={
                "source_app": "work",
                "session_id": "sess-trace-api-post-1",
                "hook_event_type": "tool_start",
                "payload": {"tool": "Bash", "call_id": "call-1"},
                "summary": "Tool start: Bash",
                "model_name": "ollama:qwen3:8b",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["source_app"] == "work"
        assert body["session_id"] == "sess-trace-api-post-1"
        assert body["hook_event_type"] == "tool_start"
        assert body["summary"] == "Tool start: Bash"

        recent = client.get("/api/traces/recent").json()
        assert any(row["id"] == body["id"] for row in recent)

    def test_list_recent_traces_user_scoped(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        seeded_id = _seed_trace(
            session_mgr,
            session_id="sess-trace-api-1",
            user=_AUTH_USER,
            event_type="dispatch_start",
            source="router",
        )
        _seed_trace(
            session_mgr,
            session_id="sess-trace-api-2",
            user="not-me",
            event_type="dispatch_start",
            source="router",
        )

        resp = client.get("/api/traces/recent")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["id"] == seeded_id
        assert rows[0]["session_id"] == "sess-trace-api-1"

    def test_list_recent_traces_with_filters(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        _seed_trace(
            session_mgr,
            session_id="sess-trace-api-3",
            user=_AUTH_USER,
            event_type="run_phase",
            source="work",
        )
        _seed_trace(
            session_mgr,
            session_id="sess-trace-api-4",
            user=_AUTH_USER,
            event_type="dispatch_start",
            source="router",
        )

        resp = client.get(
            "/api/traces/recent",
            params={"hook_event_type": "run_phase", "source_app": "work"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["hook_event_type"] == "run_phase"
        assert rows[0]["source_app"] == "work"

    def test_trace_filter_options(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        _seed_trace(
            session_mgr,
            session_id="sess-trace-api-5",
            user=_AUTH_USER,
            event_type="run_phase",
            source="work",
        )

        resp = client.get("/api/traces/filter-options")
        assert resp.status_code == 200
        body = resp.json()
        assert "work" in body["source_apps"]
        assert "sess-trace-api-5" in body["session_ids"]
        assert "run_phase" in body["hook_event_types"]

    def test_get_trace_event(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        trace_id = _seed_trace(
            session_mgr,
            session_id="sess-trace-api-6",
            user=_AUTH_USER,
            event_type="dispatch_complete",
            source="router",
        )

        resp = client.get(f"/api/traces/{trace_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == trace_id
        assert body["hook_event_type"] == "dispatch_complete"

    def test_list_session_traces_not_found_when_user_mismatch(self, tmp_path: Path):
        client, session_mgr, _trace_hub = _build_client(tmp_path)
        _seed_trace(
            session_mgr,
            session_id="sess-trace-api-7",
            user="someone-else",
            event_type="run_phase",
            source="work",
        )

        resp = client.get("/api/sessions/sess-trace-api-7/traces")
        assert resp.status_code == 404
        assert resp.json()["error"] == "Session not found"

    def test_ws_traces_stream_init_and_live_event(self, tmp_path: Path):
        client, session_mgr, trace_hub = _build_client(tmp_path)
        trace_id = _seed_trace(
            session_mgr,
            session_id="sess-trace-api-8",
            user=_AUTH_USER,
            event_type="dispatch_start",
            source="router",
        )

        with client.websocket_connect("/ws/traces") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "trace_init"
            assert any(row["id"] == trace_id for row in init_msg["events"])
            assert "source_apps" in init_msg["filter_options"]

            live_event = {
                "id": 999999,
                "source_app": "work",
                "session_id": "sess-trace-api-8",
                "dispatch_id": None,
                "run_id": None,
                "turn_id": "turn-live",
                "hook_event_type": "run_phase",
                "payload": {"phase": "executing"},
                "summary": "executing",
                "model_name": "ollama:qwen3:8b",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            asyncio.run(trace_hub.publish(user=_AUTH_USER, event=live_event))
            event_msg = ws.receive_json()
            assert event_msg["type"] == "trace_event"
            assert event_msg["data"]["id"] == 999999
