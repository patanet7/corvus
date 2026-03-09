"""Behavioral frontend/backend contract tests.

These tests verify the backend payload contracts consumed by the Svelte frontend
(API and WebSocket), using the real FastAPI app + real SQLite session store.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

# Importing claw.server requires claude_agent_sdk.
SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed -- run in Docker for full coverage",
)


@skip_no_sdk
class TestFrontendAPIContracts:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        return TestClient(app, headers={"X-Remote-User": "testuser"})

    def test_models_endpoint_shape_matches_frontend_model_info(self, client):
        resp = client.get("/api/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body
        assert "default_model" in body
        assert isinstance(body["models"], list)

        for model in body["models"]:
            # frontend/src/lib/types.ts::ModelInfo
            assert isinstance(model.get("id"), str)
            assert isinstance(model.get("label"), str)
            assert isinstance(model.get("backend"), str)
            assert isinstance(model.get("available"), bool)
            capabilities = model.get("capabilities")
            assert isinstance(capabilities, dict)
            assert isinstance(capabilities.get("supports_tools"), bool)
            assert isinstance(capabilities.get("supports_streaming"), bool)

    def test_session_endpoints_shape_matches_frontend_session_mapping(self, client):
        from corvus.server import session_mgr

        session_id = "frontend-contract-session"
        try:
            session_mgr.start(
                session_id,
                user="testuser",
                started_at=datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC),
            )
            session_mgr.end(
                session_id,
                ended_at=datetime(2026, 3, 3, 12, 10, 0, tzinfo=UTC),
                message_count=2,
                tool_count=1,
                agents_used=["general"],
            )
            session_mgr.add_message(
                session_id,
                "user",
                "hello",
                agent="general",
                model="sonnet",
            )

            list_resp = client.get("/api/sessions")
            assert list_resp.status_code == 200
            sessions = list_resp.json()
            row = next((s for s in sessions if s["id"] == session_id), None)
            assert row is not None

            # frontend/src/lib/api/sessions.ts expects these snake_case keys
            assert "started_at" in row
            assert "ended_at" in row
            assert "summary" in row
            assert "message_count" in row
            assert "tool_count" in row
            assert "agents_used" in row

            msg_resp = client.get(f"/api/sessions/{session_id}/messages")
            assert msg_resp.status_code == 200
            messages = msg_resp.json()
            assert isinstance(messages, list)
            assert len(messages) >= 1
            assert {"id", "session_id", "role", "content", "created_at"}.issubset(messages[0].keys())

            session_mgr.add_event(
                session_id,
                "task_start",
                {"type": "task_start", "task_id": "task-123", "agent": "general"},
                turn_id="turn-123",
            )
            evt_resp = client.get(f"/api/sessions/{session_id}/events")
            assert evt_resp.status_code == 200
            events = evt_resp.json()
            assert isinstance(events, list)
            assert len(events) >= 1
            assert {"id", "session_id", "event_type", "payload", "created_at"}.issubset(events[0].keys())
        finally:
            session_mgr.delete(session_id)


@skip_no_sdk
class TestFrontendWebSocketContracts:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from corvus.server import app

        return TestClient(app)

    def _get_token(self, client) -> str:
        resp = client.post("/api/auth/token")
        assert resp.status_code == 200
        return resp.json()["token"]

    def test_ws_init_payload_matches_frontend_init_contract(self, client):
        token = self._get_token(client)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "init"
            assert isinstance(init_msg.get("models"), list)
            assert isinstance(init_msg.get("default_model"), str)
            assert isinstance(init_msg.get("agents"), list)
            assert isinstance(init_msg.get("default_agent"), str)
            assert isinstance(init_msg.get("session_id"), str)
            assert isinstance(init_msg.get("session_name"), str)

    def test_ws_ping_pong_contract(self, client):
        token = self._get_token(client)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            _ = ws.receive_json()  # init
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong == {"type": "pong"}
