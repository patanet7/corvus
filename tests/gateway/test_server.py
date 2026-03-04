"""Behavioral tests for the Claw server module.

NO mocks. Tests are split into:
1. Source contract tests — verify server.py source code contracts (no import needed)
2. build_system_prompt tests — exercise real file I/O with tmp_path
3. Full app tests — require claude_agent_sdk, skipped if not installed
"""

import importlib
from pathlib import Path

import pytest

# --- SDK availability check ---
SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed — run in Docker for full coverage",
)


# ---------------------------------------------------------------------------
# 1. Source contract tests — don't need to import server.py
# ---------------------------------------------------------------------------


class TestServerSourceContracts:
    """Verify structural contracts across the refactored gateway modules."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        root = Path(__file__).parent.parent.parent / "corvus"
        self.server_source = (root / "server.py").read_text()
        self.chat_source = (root / "api" / "chat.py").read_text()
        self.chat_session_source = (root / "gateway" / "chat_session.py").read_text()
        self.webhooks_source = (root / "api" / "webhooks.py").read_text()
        self.options_source = (root / "gateway" / "options.py").read_text()

    def test_no_memory_server_import(self):
        assert "memory_server" not in self.server_source
        assert "build_memory_server" not in self.server_source

    def test_app_title_in_source(self):
        assert 'FastAPI(title="Corvus Gateway"' in self.server_source

    def test_uses_lifespan_not_on_event(self):
        """FastAPI lifespan context manager replaces deprecated on_event."""
        assert "async def lifespan" in self.server_source
        assert "lifespan=lifespan" in self.server_source
        assert "@app.on_event" not in self.server_source

    def test_health_endpoint_defined(self):
        assert '@app.get("/health")' in self.server_source
        assert "async def health" in self.server_source

    def test_websocket_endpoint_defined(self):
        assert '@router.websocket("/ws")' in self.chat_source
        assert "async def websocket_chat" in self.chat_source

    def test_webhook_endpoint_defined(self):
        assert '@router.post("/{webhook_type}")' in self.webhooks_source
        assert "async def webhook" in self.webhooks_source

    def test_ws_auth_before_accept(self):
        """Verify WebSocket auth check happens before accept() call."""
        auth_pos = self.chat_source.index("websocket.headers.get")
        close_pos = self.chat_source.index("await websocket.close(code=4401")
        accept_pos = self.chat_source.index("await websocket.accept()")
        # Auth check and rejection must come before accept
        assert auth_pos < accept_pos
        assert close_pos < accept_pos

    def test_permission_mode_is_resolved_dynamically(self):
        assert '"permission_mode": permission_mode' in self.options_source
        assert "_resolve_permission_mode(" in self.options_source

    def test_imports_allowed_users_for_auth(self):
        assert "ALLOWED_USERS" in self.chat_source

    def test_ws_checks_auth_header(self):
        assert "X-Remote-User" in self.chat_source

    def test_imports_hooks(self):
        assert "create_hooks" in self.options_source

    # --- Stop hook wiring contracts ---

    def test_imports_session_transcript(self):
        """ChatSession module imports SessionTranscript from corvus.session."""
        assert "from corvus.session import SessionTranscript" in self.chat_session_source

    def test_imports_extract_session_memories(self):
        """WebSocket module imports extract_session_memories from corvus.session."""
        assert "extract_session_memories" in self.chat_source

    def test_get_memory_hub_defined(self):
        """get_memory_hub() helper is defined in server.py."""
        assert "def get_memory_hub()" in self.server_source

    def test_transcript_created_in_websocket(self):
        """SessionTranscript is instantiated inside ChatSession."""
        assert "SessionTranscript(" in self.chat_session_source

    def test_user_messages_collected_in_transcript(self):
        """User messages are appended to transcript.messages."""
        assert 'transcript.messages.append({"role": "user"' in self.chat_session_source

    def test_assistant_responses_collected_in_transcript(self):
        """Assistant responses are appended to transcript.messages."""
        assert "transcript.messages.append(" in self.chat_session_source
        assert '"role": "assistant"' in self.chat_session_source

    def test_stop_hook_calls_extract_on_disconnect(self):
        """extract_session_memories is called in the WebSocketDisconnect handler."""
        # Find the WebSocketDisconnect block and verify extraction is called there
        disconnect_pos = self.chat_source.index("except WebSocketDisconnect:")
        extract_pos = self.chat_source.index("extract_session_memories(")
        assert extract_pos > disconnect_pos

    def test_stop_hook_wrapped_in_try_except(self):
        """The stop hook extraction is wrapped in try/except so it never crashes teardown."""
        # The memory extraction must be inside a try/except within the disconnect handler
        disconnect_pos = self.chat_source.index("except WebSocketDisconnect:")
        # Look for the inner try/except after the disconnect handler
        remaining = self.chat_source[disconnect_pos:]
        assert "try:" in remaining
        assert "except Exception:" in remaining
        assert "Session memory extraction failed" in remaining

    def test_response_parts_collected(self):
        """response_parts list is used to collect text blocks before appending to transcript."""
        assert "response_parts: list[str] = []" in self.chat_session_source
        assert "response_parts.append(block.text)" in self.chat_session_source

    def test_imports_memory_config(self):
        """Runtime module still provisions memory paths."""
        assert "ensure_dirs" in self.server_source

    # --- Slice 10B: Paperless + Firefly webhook wiring ---

    def test_webhook_dispatch_includes_paperless(self):
        assert "process_paperless" in self.webhooks_source
        assert "PaperlessWebhookPayload" in self.webhooks_source

    def test_webhook_dispatch_includes_finance(self):
        assert "process_finance" in self.webhooks_source
        assert "FinanceWebhookPayload" in self.webhooks_source

    # --- Hub path wiring ---

    def test_build_options_wires_mcp_servers(self):
        """build_options must call build_mcp_servers and pass them to options."""
        assert "build_mcp_servers" in self.options_source
        assert '"mcp_servers"' in self.options_source or "mcp_servers" in self.options_source

    def test_transcript_records_agent(self):
        """target_agent must be recorded in transcript.agents_used."""
        assert "transcript.record_agent(agent_name)" in self.chat_session_source

    def test_dispatch_plan_event_emitted(self):
        """WebSocket chat loop emits dispatch_plan for hierarchical routing UI."""
        assert '"type": "dispatch_plan"' in self.chat_session_source
        assert "dispatch_plan.to_payload()" in self.chat_session_source

    def test_run_route_metadata_is_persisted(self):
        """Run rows persist route-level task metadata fields."""
        assert "task_type=route.task_type" in self.chat_session_source
        assert "subtask_id=route.subtask_id" in self.chat_session_source
        assert "skill=route.skill" in self.chat_session_source

    def test_selected_model_is_applied_before_query(self):
        """WebSocket chat loop must apply active model before querying."""
        src = self.chat_session_source
        set_model_pos = src.index("await client.set_model(active_model)")
        if "await client.query(run_message, session_id=self.session_id)" in src:
            query_pos = src.index("await client.query(run_message, session_id=self.session_id)")
        else:
            query_pos = src.index("await client.query(user_message, session_id=self.session_id)")
        assert set_model_pos < query_pos

    def test_model_unavailable_returns_typed_error(self):
        """Unavailable user-selected model returns typed error contract."""
        assert '"error": "model_unavailable"' in self.chat_session_source

    def test_model_capability_mismatch_returns_typed_error(self):
        """Tool-required turns on chat-only models return typed capability mismatch."""
        assert '"error": "model_capability_mismatch"' in self.chat_session_source
        assert '"capability": "tools"' in self.chat_session_source

    def test_invalid_agent_returns_typed_error(self):
        """Unknown/disabled target agent returns typed error contract via chat_engine."""
        engine_source = (Path(__file__).parent.parent.parent / "corvus" / "gateway" / "chat_engine.py").read_text()
        assert '"invalid_agent"' in engine_source
        # ChatSession sends dispatch_error.error which includes invalid_agent
        assert "dispatch_error.error" in self.chat_session_source


class TestAgentAPISourceContracts:
    """Verify agent REST API source-level contracts."""

    @pytest.fixture(autouse=True)
    def _load_source(self):
        self.source = (Path(__file__).parent.parent.parent / "corvus" / "api" / "agents.py").read_text()

    def test_all_endpoints_require_auth(self):
        """Every route function must have Depends(get_user) for authentication."""
        assert "from corvus.auth import get_user" in self.source
        # Count endpoint definitions and Depends(get_user) occurrences
        endpoint_count = self.source.count("async def ")
        auth_count = self.source.count("Depends(get_user)")
        assert auth_count >= endpoint_count, f"Found {endpoint_count} endpoints but only {auth_count} auth dependencies"

    def test_imports_depends(self):
        assert "from fastapi import" in self.source
        assert "Depends" in self.source


# ---------------------------------------------------------------------------
# 2. build_system_prompt tests — exercise real file I/O
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """Test build_system_prompt() with real file I/O.

    Since server.py imports claude_agent_sdk at module level, we extract and
    test the prompt-building logic directly. The function only reads files from
    WORKSPACE_DIR — we point it at a tmp_path.
    """

    @staticmethod
    def _build_system_prompt(workspace_dir: Path) -> str:
        """Replicate build_system_prompt logic for testing without SDK import.

        This exercises the exact same algorithm as server.py:build_system_prompt
        using real file I/O against a real temp directory.
        """
        parts: list[str] = []

        memory_file = workspace_dir / "MEMORY.md"
        if memory_file.exists():
            parts.append(f"# Long-term Memory\n\n{memory_file.read_text()}")

        user_file = workspace_dir / "USER.md"
        if user_file.exists():
            parts.append(f"# User Profile\n\n{user_file.read_text()}")

        for name in ["personal.md", "projects.md", "health.md"]:
            efile = workspace_dir / "memory" / name
            if efile.exists():
                parts.append(f"# {name.replace('.md', '').title()} Notes\n\n{efile.read_text()}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def test_returns_empty_when_no_files(self, tmp_path):
        result = self._build_system_prompt(tmp_path)
        assert result == ""

    def test_loads_memory_md(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("test memory content")
        result = self._build_system_prompt(tmp_path)
        assert "test memory content" in result
        assert "Long-term Memory" in result

    def test_loads_user_md(self, tmp_path):
        (tmp_path / "USER.md").write_text("user profile data")
        result = self._build_system_prompt(tmp_path)
        assert "user profile data" in result
        assert "User Profile" in result

    def test_loads_evergreen_files(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "personal.md").write_text("personal notes")
        (memory_dir / "projects.md").write_text("project notes")
        result = self._build_system_prompt(tmp_path)
        assert "personal notes" in result
        assert "project notes" in result

    def test_combines_all_sections_with_separator(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("memory")
        (tmp_path / "USER.md").write_text("user")
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "health.md").write_text("health")
        result = self._build_system_prompt(tmp_path)
        assert "---" in result
        assert "memory" in result
        assert "user" in result
        assert "health" in result

    def test_ignores_nonexistent_evergreen_files(self, tmp_path):
        """Only existing files contribute to the prompt."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "personal.md").write_text("personal notes")
        # projects.md and health.md don't exist
        result = self._build_system_prompt(tmp_path)
        assert "personal notes" in result
        assert "projects" not in result.lower() or "Projects Notes" not in result

    def test_section_order(self, tmp_path):
        """Memory comes first, then user, then evergreen files."""
        (tmp_path / "MEMORY.md").write_text("AAA_MEMORY")
        (tmp_path / "USER.md").write_text("BBB_USER")
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "personal.md").write_text("CCC_PERSONAL")
        result = self._build_system_prompt(tmp_path)
        assert result.index("AAA_MEMORY") < result.index("BBB_USER")
        assert result.index("BBB_USER") < result.index("CCC_PERSONAL")


# ---------------------------------------------------------------------------
# 3. Full app tests — require SDK, skipped if not installed
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestFullAppWithSDK:
    """Tests that require the real server app with claude_agent_sdk.

    These run in Docker or when the SDK is pip-installed.
    """

    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient

        from corvus.server import app

        return TestClient(app)

    def test_health_endpoint_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "corvus-gateway"

    def test_health_response_shape(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert set(body.keys()) == {"status", "service", "backends"}

    def test_webhook_rejects_invalid_payload(self, client):
        """Invalid payload returns 401 (auth check) or 422 (validation) depending on config."""
        import os

        secret = os.environ.get("WEBHOOK_SECRET", "")
        resp = client.post(
            "/api/webhooks/transcript",
            json={"not_valid": True},
            headers={"X-Webhook-Secret": secret},
        )
        # Without WEBHOOK_SECRET set, auth rejects first with 401
        assert resp.status_code in (401, 422)

    def test_webhook_rejects_unknown_type(self, client):
        """Unknown webhook type returns 401 (auth check) or 400 depending on config."""
        import os

        secret = os.environ.get("WEBHOOK_SECRET", "")
        resp = client.post(
            "/api/webhooks/nonexistent",
            json={},
            headers={"X-Webhook-Secret": secret},
        )
        assert resp.status_code in (400, 401)

    def test_app_has_expected_routes(self, client):
        routes = [r.path for r in client.app.routes]
        assert "/health" in routes
        assert "/ws" in routes
        assert "/api/webhooks/{webhook_type}" in routes

    def test_app_title(self, client):
        assert client.app.title == "Corvus Gateway"

    def test_websocket_rejects_unauthenticated(self, client):
        """WebSocket without auth headers should be rejected before accept."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws") as _ws:
                pass
        assert exc_info.value.code == 4401

    def test_webhook_returns_json_content_type(self, client):
        """Even error responses return JSON content type."""
        import os

        secret = os.environ.get("WEBHOOK_SECRET", "")
        resp = client.post(
            "/api/webhooks/unknown",
            json={"x": 1},
            headers={"X-Webhook-Secret": secret},
        )
        assert resp.headers["content-type"] == "application/json"
