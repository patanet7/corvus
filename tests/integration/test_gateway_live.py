"""LIVE integration tests for the Claw Gateway server.

NO mocks. Real FastAPI TestClient, real SQLite, real event pipeline.
Tests verify the server actually starts, endpoints respond, and
auth enforcement works.

Run: uv run pytest tests/integration/test_gateway_live.py -v
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture(autouse=True)
def _gateway_env(tmp_path: Path):
    """Set minimal env vars so the server can import without crashing."""
    env_overrides = {
        "HOST": "127.0.0.1",
        "PORT": "18789",
        "ALLOWED_USERS": "testuser,testuser",
        "WORKSPACE_DIR": str(tmp_path / "workspace"),
        "DATA_DIR": str(tmp_path / "data"),
        "MEMORY_DB": str(tmp_path / "memory.sqlite"),
        "LOG_DIR": str(tmp_path / "logs"),
        # Don't configure external services — tests shouldn't need them
        "HA_URL": "",
        "PAPERLESS_URL": "",
        "FIREFLY_URL": "",
    }
    original = {}
    for k, v in env_overrides.items():
        original[k] = os.environ.get(k)
        os.environ[k] = v

    # Create dirs the server expects
    (tmp_path / "workspace").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()

    yield

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def client(_gateway_env) -> TestClient:
    """Create a real FastAPI TestClient for the Claw Gateway."""
    # Import here so env vars are set first
    from corvus.server import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """The most basic test: does the server respond?"""

    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_correct_json(self, client: TestClient) -> None:
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "corvus-gateway"

    def test_health_response_is_fast(self, client: TestClient) -> None:
        """Health endpoint should respond in under 100ms."""
        import time

        start = time.monotonic()
        resp = client.get("/health")
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        assert elapsed < 0.1


# ---------------------------------------------------------------------------
# WebSocket auth enforcement
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    """Verify WebSocket auth is enforced before accept."""

    def test_ws_rejects_no_auth_header(self, client: TestClient) -> None:
        """WebSocket without X-Remote-User header should be rejected."""
        with pytest.raises((WebSocketDisconnect, RuntimeError)):
            with client.websocket_connect("/ws"):
                pass

    def test_ws_rejects_unknown_user(self, client: TestClient) -> None:
        """WebSocket with unknown user should be rejected."""
        with pytest.raises((WebSocketDisconnect, RuntimeError)):
            with client.websocket_connect("/ws", headers={"X-Remote-User": "hacker"}):
                pass

    def test_ws_accepts_allowed_user(self, client: TestClient) -> None:
        """WebSocket with valid user should be accepted."""
        with client.websocket_connect("/ws", headers={"X-Remote-User": "testuser"}) as _ws:
            # Connection opened — that's the test. Close cleanly.
            pass


# ---------------------------------------------------------------------------
# Schedule API
# ---------------------------------------------------------------------------


class TestScheduleAPI:
    """Verify the schedule management endpoints respond."""

    def test_list_schedules_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_unknown_schedule_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/schedules/nonexistent")
        assert resp.status_code == 404

    def test_trigger_unknown_schedule_returns_404(self, client: TestClient) -> None:
        resp = client.post("/api/schedules/nonexistent/trigger")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


class TestWebhookEndpoint:
    """Verify webhook endpoint basic behavior."""

    def test_unknown_webhook_type_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/webhooks/nonexistent",
            json={"test": True},
            headers={"X-Webhook-Secret": "wrong"},
        )
        # Should be 401 (bad secret) or 400 (unknown type) — not 500
        assert resp.status_code in (400, 401)

    def test_webhook_without_secret_returns_401(self, client: TestClient) -> None:
        resp = client.post("/api/webhooks/transcript", json={"test": True})
        assert resp.status_code == 401
