"""Integration tests for ChatSession extraction refactor.

Covers three areas:
  1. Model wiring source contracts (resolve_backend_and_model pipeline)
  2. Parallel chat isolation (independent ChatSession instances)
  3. Session start/resume contracts (query param resume, SessionManager CRUD)

All tests are behavioral: real SQLite databases, real objects, real source reads.
NO mocks, NO monkeypatch, NO @patch, NO unittest.mock, NO fakes.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.gateway.chat_session import ChatSession, TurnContext
from corvus.gateway.trace_hub import TraceHub
from corvus.session import SessionTranscript
from corvus.session_manager import SessionManager

SDK_AVAILABLE = importlib.util.find_spec("claude_agent_sdk") is not None
skip_no_sdk = pytest.mark.skipif(
    not SDK_AVAILABLE,
    reason="claude_agent_sdk not installed",
)


# ---------------------------------------------------------------------------
# Lightweight runtime helper (same pattern as test_chat_session.py)
# ---------------------------------------------------------------------------


class _MinimalRuntime:
    """Real runtime with real SQLite DB, NOT a mock."""

    def __init__(self, db_path: Path) -> None:
        self.session_mgr = SessionManager(db_path=db_path)
        self.trace_hub = TraceHub()


def _make_session(
    tmp_path: Path,
    session_id: str | None = None,
    user: str = "testuser",
) -> tuple[_MinimalRuntime, ChatSession]:
    """Create a ChatSession with an isolated SQLite DB for behavioral tests."""
    sid = session_id or f"sess-{uuid4().hex[:8]}"
    runtime = _MinimalRuntime(db_path=tmp_path / f"{sid}.sqlite")
    runtime.session_mgr.start(sid, user=user)
    session = ChatSession(
        runtime=runtime,  # type: ignore[arg-type]
        websocket=None,
        user=user,
        session_id=sid,
    )
    return runtime, session


# ---------------------------------------------------------------------------
# Source reader helper
# ---------------------------------------------------------------------------


def _read_source(relative_parts: list[str]) -> str:
    """Read a source file from the project root and return its contents."""
    project_root = Path(__file__).resolve().parent.parent.parent
    source_path = project_root
    for part in relative_parts:
        source_path = source_path / part
    return source_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Model Wiring Source Contracts
# ---------------------------------------------------------------------------


@skip_no_sdk
class TestModelWiringContracts:
    """Source-level contract tests verifying model selection pipeline wiring."""

    @pytest.fixture(autouse=True)
    def _load_source(self) -> None:
        self.source = _read_source(["corvus", "gateway", "chat_session.py"])

    def test_resolve_backend_and_model_is_called(self) -> None:
        """chat_session.py must call resolve_backend_and_model(."""
        assert "resolve_backend_and_model(" in self.source

    def test_user_model_passed_to_resolve(self) -> None:
        """The resolve call area must pass user_model= to derive the requested model."""
        # Find the resolve call and verify user_model is referenced near it.
        # The code uses: requested_model = route.requested_model or turn.user_model
        # Then: resolve_backend_and_model(runtime=..., agent_name=..., requested_model=requested_model)
        assert "requested_model=" in self.source
        # Verify user_model is extracted from TurnContext and used upstream
        assert "turn.user_model" in self.source

    def test_active_model_feeds_set_model(self) -> None:
        """After resolve_backend_and_model, set_model(active_model) must be called."""
        # Find the resolve call
        resolve_idx = self.source.index("resolve_backend_and_model(")
        # Find set_model call after it
        set_model_idx = self.source.index("set_model(active_model)", resolve_idx)
        assert set_model_idx > resolve_idx

    def test_model_error_paths_are_distinct(self) -> None:
        """Source must have both model_unavailable and model_capability_mismatch as distinct error types."""
        assert '"model_unavailable"' in self.source
        assert '"model_capability_mismatch"' in self.source
        # Verify they appear in different locations (distinct error paths)
        unavailable_idx = self.source.index('"model_unavailable"')
        mismatch_idx = self.source.index('"model_capability_mismatch"')
        assert unavailable_idx != mismatch_idx

    def test_ui_model_id_sent_to_frontend(self) -> None:
        """Source must call ui_model_id( to produce frontend-facing model identifiers."""
        assert "ui_model_id(" in self.source
        # Verify it is imported at module level
        assert "from corvus.gateway.options import" in self.source
        # Verify the import line includes ui_model_id
        import_block_start = self.source.index("from corvus.gateway.options import")
        # Find the closing paren of the import
        import_block_end = self.source.index(")", import_block_start)
        import_block = self.source[import_block_start:import_block_end]
        assert "ui_model_id" in import_block


# ---------------------------------------------------------------------------
# 2. Parallel Chat Isolation
# ---------------------------------------------------------------------------


class TestParallelChatIsolation:
    """Behavioral tests verifying independent ChatSession instances don't interfere."""

    def test_independent_transcripts(self, tmp_path: Path) -> None:
        """Two sessions must have independent transcript objects."""
        _, session_a = _make_session(tmp_path, "sess-alpha")
        _, session_b = _make_session(tmp_path, "sess-beta")
        assert session_a.transcript is not session_b.transcript
        assert isinstance(session_a.transcript, SessionTranscript)
        assert isinstance(session_b.transcript, SessionTranscript)

    def test_independent_session_ids(self, tmp_path: Path) -> None:
        """Two sessions with different IDs must each store their own ID."""
        _, session_a = _make_session(tmp_path, "sess-alpha")
        _, session_b = _make_session(tmp_path, "sess-beta")
        assert session_a.session_id == "sess-alpha"
        assert session_b.session_id == "sess-beta"
        assert session_a.session_id != session_b.session_id

    def test_independent_turn_contexts(self, tmp_path: Path) -> None:
        """Setting _current_turn on one session must not affect the other."""
        _, session_a = _make_session(tmp_path, "sess-alpha")
        _, session_b = _make_session(tmp_path, "sess-beta")
        # Both start with None
        assert session_a._current_turn is None
        assert session_b._current_turn is None
        # Set on session_a only
        session_a._current_turn = TurnContext(
            dispatch_id="d-test",
            turn_id="t-test",
            dispatch_interrupted=asyncio.Event(),
            user_model=None,
            requires_tools=False,
        )
        assert session_a._current_turn is not None
        assert session_b._current_turn is None

    def test_independent_send_locks(self, tmp_path: Path) -> None:
        """Each session must have its own asyncio.Lock instance."""
        _, session_a = _make_session(tmp_path, "sess-alpha")
        _, session_b = _make_session(tmp_path, "sess-beta")
        assert isinstance(session_a.send_lock, asyncio.Lock)
        assert isinstance(session_b.send_lock, asyncio.Lock)
        assert session_a.send_lock is not session_b.send_lock

    def test_independent_session_managers(self, tmp_path: Path) -> None:
        """Two sessions backed by different DBs must have independent session data."""
        runtime_a, session_a = _make_session(tmp_path, "sess-alpha")
        runtime_b, session_b = _make_session(tmp_path, "sess-beta")
        # Each session_mgr should only know about its own session
        result_a = runtime_a.session_mgr.get("sess-alpha")
        result_b = runtime_b.session_mgr.get("sess-beta")
        assert result_a is not None
        assert result_b is not None
        # Cross-check: session_mgr_a should NOT know about sess-beta
        assert runtime_a.session_mgr.get("sess-beta") is None
        assert runtime_b.session_mgr.get("sess-alpha") is None

    def test_transcript_agent_recording_is_isolated(self, tmp_path: Path) -> None:
        """Recording an agent on one session must not affect the other."""
        _, session_a = _make_session(tmp_path, "sess-alpha")
        _, session_b = _make_session(tmp_path, "sess-beta")
        session_a.transcript.record_agent("homelab")
        assert "homelab" in session_a.transcript.agents_used
        assert len(session_b.transcript.agents_used) == 0


# ---------------------------------------------------------------------------
# 3. Session Start/Resume Contracts
# ---------------------------------------------------------------------------


class TestSessionStartResumeContracts:
    """Source-level and behavioral tests for session start/resume logic."""

    @pytest.fixture(autouse=True)
    def _load_chat_source(self) -> None:
        self.chat_source = _read_source(["corvus", "api", "chat.py"])

    # --- Source-level contract tests on chat.py ---

    def test_session_id_read_from_query_params(self) -> None:
        """chat.py must read session_id from websocket query params."""
        assert 'websocket.query_params.get("session_id")' in self.chat_source

    def test_resume_checks_user_ownership(self) -> None:
        """chat.py must verify that the resumed session belongs to the requesting user."""
        assert 'resumed_session.get("user") == user' in self.chat_source

    def test_new_session_generates_uuid(self) -> None:
        """chat.py must generate a UUID for new sessions."""
        assert "str(uuid.uuid4())" in self.chat_source

    def test_session_manager_start_called_for_new(self) -> None:
        """chat.py must call runtime.session_mgr.start(session_id for new sessions."""
        assert "runtime.session_mgr.start(session_id" in self.chat_source

    def test_resumed_session_passed_to_run(self) -> None:
        """chat.py must pass resumed_session=resumed_session to session.run()."""
        assert "resumed_session=resumed_session" in self.chat_source

    # --- Behavioral tests using real SessionManager ---

    def test_session_manager_get_returns_started_session(self, tmp_path: Path) -> None:
        """Starting a session and then getting it returns the correct data."""
        mgr = SessionManager(db_path=tmp_path / "resume-test.sqlite")
        mgr.start("sess-get-test", user="testuser")
        result = mgr.get("sess-get-test")
        assert result is not None
        assert result["user"] == "testuser"
        assert result["id"] == "sess-get-test"
        mgr.close()

    def test_session_manager_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        """Getting a nonexistent session returns None."""
        mgr = SessionManager(db_path=tmp_path / "missing-test.sqlite")
        result = mgr.get("nonexistent-session-id")
        assert result is None
        mgr.close()

    def test_session_resume_preserves_session_id(self, tmp_path: Path) -> None:
        """Starting a session and retrieving it preserves the session_id."""
        mgr = SessionManager(db_path=tmp_path / "preserve-test.sqlite")
        mgr.start("sess-abc", user="testuser")
        result = mgr.get("sess-abc")
        assert result is not None
        assert result["id"] == "sess-abc"
        mgr.close()
