"""LIVE E2E tests for SDK integration -- real server, real WebSocket, real events.

NO mocks. TestClient + real SDKClientManager + real event pipeline.
Verifies the SDK integration actually works through the full gateway stack.

Run: uv run pytest tests/integration/test_sdk_e2e.py -v
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

pytestmark = [pytest.mark.integration, pytest.mark.live]


# ---------------------------------------------------------------------------
# Environment fixture -- isolates env for SDK E2E tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sdk_env(tmp_path: Path):
    """Set env vars for SDK E2E tests.

    Creates all required directories and sets env vars to point at tmp_path.
    Restores original env on teardown.
    """
    env_overrides = {
        "HOST": "127.0.0.1",
        "PORT": "18789",
        "ALLOWED_USERS": "testuser,testuser",
        "WORKSPACE_DIR": str(tmp_path / "workspace"),
        "DATA_DIR": str(tmp_path / "data"),
        "MEMORY_DB": str(tmp_path / "data" / "memory.sqlite"),
        "LOG_DIR": str(tmp_path / "logs"),
        "HA_URL": "",
        "PAPERLESS_URL": "",
        "FIREFLY_URL": "",
    }
    original: dict[str, str | None] = {}
    for k, v in env_overrides.items():
        original[k] = os.environ.get(k)
        os.environ[k] = v

    # Create dirs the server expects
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    yield

    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(_sdk_env) -> TestClient:
    """Create a real FastAPI TestClient with auth header."""
    from corvus.server import app

    return TestClient(app, headers={"X-Remote-User": "testuser"})


@pytest.fixture()
def bare_client(_sdk_env) -> TestClient:
    """TestClient without default auth headers -- for token-based auth."""
    from corvus.server import app

    return TestClient(app)


def _get_auth_token(bare_client: TestClient) -> str:
    """Obtain a session auth token via the /api/auth/token endpoint."""
    resp = bare_client.post("/api/auth/token")
    assert resp.status_code == 200, f"Auth token request failed: {resp.text}"
    token = resp.json()["token"]
    assert isinstance(token, str) and len(token) > 0
    return token


# ---------------------------------------------------------------------------
# TestSDKManagerViaRuntime -- verify SDKClientManager is wired in
# ---------------------------------------------------------------------------


class TestSDKManagerViaRuntime:
    """Verify SDKClientManager is wired into GatewayRuntime correctly."""

    def test_runtime_has_sdk_client_manager(self, client: TestClient) -> None:
        """The runtime should have an SDKClientManager attribute."""
        from corvus.gateway.runtime import GatewayRuntime
        from corvus.gateway.sdk_client_manager import SDKClientManager

        # Access the runtime through the server module
        from corvus.server import runtime

        assert isinstance(runtime, GatewayRuntime)
        assert hasattr(runtime, "sdk_client_manager")
        assert isinstance(runtime.sdk_client_manager, SDKClientManager)

    def test_sdk_manager_has_no_active_runs(self, client: TestClient) -> None:
        """Runtime should have no clients with active_run=True."""
        from corvus.server import runtime

        active = runtime.sdk_client_manager.list_active_clients()
        active_runs = [c for c in active if c.active_run]
        assert active_runs == []

    def test_sdk_manager_pool_lifecycle_via_stubs(self, client: TestClient) -> None:
        """Verify pool creation, get, and teardown without real SDK clients.

        Uses ManagedClient.create_stub() to test pool mechanics through the
        real SDKClientManager instance on the runtime, without needing a
        live LLM backend.
        """
        from corvus.gateway.sdk_client_manager import ManagedClient
        from corvus.server import runtime

        mgr = runtime.sdk_client_manager
        session_id = "test-pool-lifecycle"

        # Pool should not exist yet
        assert mgr._get_existing(session_id, "general") is None

        # Add a stub client through pool mechanics
        pool = mgr._get_pool(session_id)
        stub = ManagedClient.create_stub(session_id=session_id, agent_name="general")
        pool.add(stub)

        # Should now be findable
        found = mgr._get_existing(session_id, "general")
        assert found is not None
        assert found.agent_name == "general"
        assert found.session_id == session_id
        assert found.client is None  # stub has no real client

        # Verify it appears in active clients list
        active = mgr.list_active_clients()
        assert len(active) >= 1
        info = [c for c in active if c.session_id == session_id]
        assert len(info) == 1
        assert info[0].agent_name == "general"
        assert info[0].active_run is False

        # Release and verify
        mgr.release(session_id, "general")
        found_after = mgr._get_existing(session_id, "general")
        assert found_after is not None
        assert found_after.active_run is False

        # Clean up -- remove from pool to avoid polluting other tests
        pool.remove("general")

    def test_sdk_manager_idle_eviction_collects_stubs(self, client: TestClient) -> None:
        """Idle stubs should be collected by eviction with zero timeout."""
        from corvus.gateway.sdk_client_manager import ManagedClient
        from corvus.server import runtime

        mgr = runtime.sdk_client_manager
        session_id = "test-eviction"

        pool = mgr._get_pool(session_id)
        stub = ManagedClient.create_stub(session_id=session_id, agent_name="evict-me")
        # Backdate last_activity so it looks idle
        stub.last_activity = time.monotonic() - 9999
        pool.add(stub)

        # Collect with a short timeout
        evicted = pool.collect_idle(timeout=1.0)
        assert len(evicted) == 1
        assert evicted[0].agent_name == "evict-me"

        # Pool should be empty now
        assert pool.get("evict-me") is None

        # Clean up empty pool
        mgr._pools.pop(session_id, None)

    def test_sdk_manager_accumulate_tracks_metrics(self, client: TestClient) -> None:
        """ManagedClient.accumulate() should update running totals."""
        from corvus.gateway.sdk_client_manager import ManagedClient

        stub = ManagedClient.create_stub(session_id="test-metrics", agent_name="metrics-agent")
        assert stub.total_tokens == 0
        assert stub.total_cost_usd == 0.0
        assert stub.turn_count == 0

        stub.active_run = True
        stub.accumulate(tokens=150, cost_usd=0.003, sdk_session_id="sdk-123")

        assert stub.total_tokens == 150
        assert stub.total_cost_usd == pytest.approx(0.003)
        assert stub.turn_count == 1
        assert stub.sdk_session_id == "sdk-123"
        assert stub.active_run is False

        # Second accumulation
        stub.active_run = True
        stub.accumulate(tokens=200, cost_usd=0.004, sdk_session_id="sdk-123")
        assert stub.total_tokens == 350
        assert stub.total_cost_usd == pytest.approx(0.007)
        assert stub.turn_count == 2

    def test_sdk_manager_checkpoint_tracking(self, client: TestClient) -> None:
        """ManagedClient should track checkpoint UUIDs."""
        from corvus.gateway.sdk_client_manager import ManagedClient

        stub = ManagedClient.create_stub(session_id="test-ckpt", agent_name="ckpt-agent")
        assert stub.checkpoints == []

        stub.track_checkpoint("uuid-1")
        stub.track_checkpoint("uuid-2")
        assert stub.checkpoints == ["uuid-1", "uuid-2"]


# ---------------------------------------------------------------------------
# TestWebSocketSDKPipeline -- verify WS message flow
# ---------------------------------------------------------------------------


class TestWebSocketSDKPipeline:
    """Verify WebSocket message flow through the SDK pipeline."""

    def test_ws_connect_and_receive_init(self, bare_client: TestClient) -> None:
        """Connecting via WS with a valid token should yield an init message."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "session_id" in data
            assert isinstance(data["session_id"], str)
            assert len(data["session_id"]) > 0

    def test_ws_init_includes_models(self, bare_client: TestClient) -> None:
        """Init message should include a models list."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "models" in data
            assert isinstance(data["models"], list)

    def test_ws_init_includes_agents(self, bare_client: TestClient) -> None:
        """Init message should include an agents list with expected shape."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "agents" in data
            agents = data["agents"]
            assert isinstance(agents, list)
            assert len(agents) > 0
            # Each agent should have id, label, description
            for agent in agents:
                assert "id" in agent
                assert "label" in agent
                assert "description" in agent
                assert "isDefault" in agent

    def test_ws_init_includes_default_model(self, bare_client: TestClient) -> None:
        """Init message should include a default_model field."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "default_model" in data

    def test_ws_init_includes_default_agent(self, bare_client: TestClient) -> None:
        """Init message should include a default_agent field."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "default_agent" in data

    def test_ws_init_includes_session_name(self, bare_client: TestClient) -> None:
        """Init message should include a session_name field."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"
            assert "session_name" in data

    def test_ws_ping_pong(self, bare_client: TestClient) -> None:
        """Sending a ping should return a pong."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            # Consume init
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            # Send ping
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"

    def test_ws_ping_pong_multiple(self, bare_client: TestClient) -> None:
        """Multiple ping/pong rounds should all succeed."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            for _ in range(3):
                ws.send_json({"type": "ping"})
                pong = ws.receive_json()
                assert pong["type"] == "pong"

    def test_ws_invalid_json_returns_error(self, bare_client: TestClient) -> None:
        """Sending invalid JSON should return an error message."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            ws.send_text("this is not json{{{")
            error = ws.receive_json()
            assert error["type"] == "error"
            assert "Invalid JSON" in error.get("message", "")

    def test_ws_empty_message_ignored(self, bare_client: TestClient) -> None:
        """A message with empty text should be silently ignored.

        After sending an empty message, we send a ping to verify the
        connection is still alive and responsive.
        """
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            # Send empty message (no "message" key)
            ws.send_json({"type": "chat", "message": ""})
            # Should be ignored -- verify with ping
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"

    def test_ws_message_triggers_dispatch_start(self, bare_client: TestClient) -> None:
        """Sending a real message should produce dispatch_start event.

        Even if the LLM backend is not available, the dispatch pipeline
        should fire dispatch_start and dispatch_plan before attempting
        the actual agent run.
        """
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"
            session_id = init_data["session_id"]

            # Send a real user message
            ws.send_json({"message": "hello"})

            # Collect events until we see dispatch_start or hit a timeout
            events: list[dict] = []
            seen_dispatch_start = False
            for _ in range(20):
                try:
                    event = ws.receive_json()
                except Exception:
                    break
                events.append(event)
                if event.get("type") == "dispatch_start":
                    seen_dispatch_start = True
                    assert event["session_id"] == session_id
                    assert "dispatch_id" in event
                    assert "turn_id" in event
                    assert "target_agents" in event
                if event.get("type") == "dispatch_plan":
                    assert event["session_id"] == session_id
                    assert "dispatch_id" in event
                # Stop once we see dispatch_complete, done, or error
                if event.get("type") in ("dispatch_complete", "done", "error"):
                    break

            event_types = [e.get("type") for e in events]
            assert seen_dispatch_start, (
                f"Expected dispatch_start in event stream, got: {event_types}"
            )

    def test_ws_message_triggers_dispatch_plan(self, bare_client: TestClient) -> None:
        """Sending a message should produce a dispatch_plan event."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            ws.send_json({"message": "what time is it"})

            events: list[dict] = []
            seen_dispatch_plan = False
            for _ in range(20):
                try:
                    event = ws.receive_json()
                except Exception:
                    break
                events.append(event)
                if event.get("type") == "dispatch_plan":
                    seen_dispatch_plan = True
                    assert "task_type" in event
                if event.get("type") in ("dispatch_complete", "done", "error"):
                    break

            event_types = [e.get("type") for e in events]
            assert seen_dispatch_plan, (
                f"Expected dispatch_plan in event stream, got: {event_types}"
            )

    def test_ws_dispatch_completes_or_errors(self, bare_client: TestClient) -> None:
        """A dispatch should eventually produce dispatch_complete or error.

        Without a real LLM the agent run will fail, but the dispatch
        pipeline should still complete with an error status or error event.
        The event stream can be long (dispatch_start, dispatch_plan, routing,
        run_start, task_start, run_phase, task_progress, etc.) so we read
        up to 100 events.
        """
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            ws.send_json({"message": "test dispatch completion"})

            events: list[dict] = []
            terminal_seen = False
            terminal_types = {"dispatch_complete", "done", "error"}
            for _ in range(100):
                try:
                    event = ws.receive_json()
                except Exception:
                    break
                events.append(event)
                if event.get("type") in terminal_types:
                    terminal_seen = True
                # "done" is the very last event in a successful dispatch
                if event.get("type") == "done":
                    break
                # After an error event beyond the initial dispatch events, stop
                if event.get("type") == "error" and len(events) > 2:
                    break

            event_types = [e.get("type") for e in events]
            assert terminal_seen, (
                f"Expected terminal event (dispatch_complete/done/error), got: {event_types}"
            )

    def test_ws_dispatch_events_have_consistent_ids(self, bare_client: TestClient) -> None:
        """All events in a dispatch should share the same dispatch_id."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            ws.send_json({"message": "check id consistency"})

            dispatch_ids: set[str] = set()
            for _ in range(30):
                try:
                    event = ws.receive_json()
                except Exception:
                    break
                if "dispatch_id" in event:
                    dispatch_ids.add(event["dispatch_id"])
                if event.get("type") in ("done", "error"):
                    break

            # All dispatch events should share the same dispatch_id
            if dispatch_ids:
                assert len(dispatch_ids) == 1, (
                    f"Expected single dispatch_id, got: {dispatch_ids}"
                )


# ---------------------------------------------------------------------------
# TestWebSocketInterrupt -- verify interrupt handling
# ---------------------------------------------------------------------------


class TestWebSocketInterrupt:
    """Verify interrupt message handling through the WS pipeline."""

    def test_interrupt_before_dispatch_is_harmless(self, bare_client: TestClient) -> None:
        """Sending interrupt before any dispatch should not crash.

        Pre-dispatch interrupts are handled by the main loop in chat_session.run().
        """
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"

            # Send interrupt with no active dispatch
            ws.send_json({"type": "interrupt"})

            # Connection should still be alive -- verify with ping
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"


# ---------------------------------------------------------------------------
# TestSessionPersistence -- verify session data survives across connections
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    """Verify session creation and persistence through the runtime."""

    def test_session_created_on_ws_connect(self, bare_client: TestClient) -> None:
        """A new WS connection should create a session in SessionManager."""
        from corvus.server import runtime

        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"
            session_id = init_data["session_id"]

            # Session should exist in the session manager
            session = runtime.session_mgr.get(session_id)
            assert session is not None
            assert session["user"] == "testuser"

    def test_session_resume_returns_same_session(self, bare_client: TestClient) -> None:
        """Reconnecting with same session_id should resume the session."""
        token = _get_auth_token(bare_client)

        # First connection -- get session_id
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"
            session_id = init_data["session_id"]

        # Second connection -- resume with same session_id
        with bare_client.websocket_connect(f"/ws?token={token}&session_id={session_id}") as ws:
            init_data = ws.receive_json()
            assert init_data["type"] == "init"
            assert init_data["session_id"] == session_id

    def test_different_connections_get_different_sessions(self, bare_client: TestClient) -> None:
        """Two connections without session_id should get different sessions."""
        token = _get_auth_token(bare_client)

        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init1 = ws.receive_json()
            session_id_1 = init1["session_id"]

        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            init2 = ws.receive_json()
            session_id_2 = init2["session_id"]

        assert session_id_1 != session_id_2


# ---------------------------------------------------------------------------
# TestSDKManagerPoolIsolation -- verify session pool isolation
# ---------------------------------------------------------------------------


class TestSDKManagerPoolIsolation:
    """Verify that SDKClientManager pools are isolated per session."""

    def test_separate_sessions_have_separate_pools(self, client: TestClient) -> None:
        """Clients in different sessions should not see each other."""
        from corvus.gateway.sdk_client_manager import ManagedClient
        from corvus.server import runtime

        mgr = runtime.sdk_client_manager
        sess_a = "session-a-isolation"
        sess_b = "session-b-isolation"

        try:
            pool_a = mgr._get_pool(sess_a)
            pool_b = mgr._get_pool(sess_b)

            stub_a = ManagedClient.create_stub(session_id=sess_a, agent_name="general")
            stub_b = ManagedClient.create_stub(session_id=sess_b, agent_name="general")
            pool_a.add(stub_a)
            pool_b.add(stub_b)

            # Each session should only see its own client
            assert mgr._get_existing(sess_a, "general") is stub_a
            assert mgr._get_existing(sess_b, "general") is stub_b
            assert mgr._get_existing(sess_a, "general") is not stub_b
        finally:
            mgr._pools.pop(sess_a, None)
            mgr._pools.pop(sess_b, None)

    def test_teardown_session_only_removes_target(self, client: TestClient) -> None:
        """Tearing down one session should not affect another."""
        import asyncio

        from corvus.gateway.sdk_client_manager import ManagedClient
        from corvus.server import runtime

        mgr = runtime.sdk_client_manager
        sess_keep = "session-keep"
        sess_remove = "session-remove"

        try:
            pool_keep = mgr._get_pool(sess_keep)
            pool_remove = mgr._get_pool(sess_remove)

            stub_keep = ManagedClient.create_stub(session_id=sess_keep, agent_name="work")
            stub_remove = ManagedClient.create_stub(session_id=sess_remove, agent_name="work")
            pool_keep.add(stub_keep)
            pool_remove.add(stub_remove)

            # Teardown only sess_remove
            count = asyncio.run(mgr.teardown_session(sess_remove))
            assert count == 1

            # sess_keep should still be there
            assert mgr._get_existing(sess_keep, "work") is stub_keep
            # sess_remove should be gone
            assert mgr._get_existing(sess_remove, "work") is None
        finally:
            mgr._pools.pop(sess_keep, None)
            mgr._pools.pop(sess_remove, None)


# ---------------------------------------------------------------------------
# TestAuthTokenIntegration -- verify auth flow used by SDK tests
# ---------------------------------------------------------------------------


class TestAuthTokenIntegration:
    """Verify the auth token endpoint works for SDK test setup."""

    def test_auth_token_returns_valid_token(self, bare_client: TestClient) -> None:
        """POST /api/auth/token should return a usable token."""
        resp = bare_client.post("/api/auth/token")
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert isinstance(body["token"], str)
        assert len(body["token"]) > 10

    def test_auth_token_works_for_ws(self, bare_client: TestClient) -> None:
        """Token from /api/auth/token should be accepted by /ws."""
        token = _get_auth_token(bare_client)
        with bare_client.websocket_connect(f"/ws?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "init"

    def test_invalid_token_rejected(self, bare_client: TestClient) -> None:
        """Garbage token should be rejected at WS handshake."""
        with pytest.raises((WebSocketDisconnect, RuntimeError)):
            with bare_client.websocket_connect("/ws?token=garbage-invalid-token"):
                pass

    def test_no_token_rejected(self, bare_client: TestClient) -> None:
        """No token and no proxy header should be rejected."""
        with pytest.raises((WebSocketDisconnect, RuntimeError)):
            with bare_client.websocket_connect("/ws"):
                pass
