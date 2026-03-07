"""Behavioral tests for DispatchControlRegistry and BreakGlassSessionRegistry.

Real asyncio events, real BreakGlassManager with real Argon2id hashing.
NO mocks.
"""

import asyncio
import time
from pathlib import Path

import pytest

from corvus.break_glass import BreakGlassManager
from corvus.gateway.control_plane import BreakGlassSessionRegistry, DispatchControlRegistry


# ---------------------------------------------------------------------------
# DispatchControlRegistry
# ---------------------------------------------------------------------------


class TestDispatchControlRegistry:
    """Tests for in-memory dispatch tracking and interrupt requests."""

    def test_register_and_get(self) -> None:
        reg = DispatchControlRegistry()
        event = asyncio.Event()
        reg.register(
            dispatch_id="d1",
            session_id="s1",
            user="alice",
            turn_id="t1",
            interrupt_event=event,
        )
        active = reg.get("d1")
        assert active is not None
        assert active.dispatch_id == "d1"
        assert active.session_id == "s1"
        assert active.user == "alice"

    def test_get_missing_returns_none(self) -> None:
        reg = DispatchControlRegistry()
        assert reg.get("nonexistent") is None

    def test_unregister_removes_dispatch(self) -> None:
        reg = DispatchControlRegistry()
        event = asyncio.Event()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=event)
        reg.unregister("d1")
        assert reg.get("d1") is None

    def test_unregister_missing_no_error(self) -> None:
        reg = DispatchControlRegistry()
        reg.unregister("nonexistent")  # Should not raise

    def test_request_interrupt_sets_event(self) -> None:
        reg = DispatchControlRegistry()
        event = asyncio.Event()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=event)
        assert not event.is_set()
        result = reg.request_interrupt("d1", user="alice")
        assert result is True
        assert event.is_set()

    def test_request_interrupt_wrong_user_denied(self) -> None:
        reg = DispatchControlRegistry()
        event = asyncio.Event()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=event)
        result = reg.request_interrupt("d1", user="bob")
        assert result is False
        assert not event.is_set()

    def test_request_interrupt_missing_dispatch(self) -> None:
        reg = DispatchControlRegistry()
        result = reg.request_interrupt("nonexistent", user="alice")
        assert result is False

    def test_list_active_filters_by_user(self) -> None:
        reg = DispatchControlRegistry()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=asyncio.Event())
        reg.register(dispatch_id="d2", session_id="s2", user="bob", turn_id="t2", interrupt_event=asyncio.Event())
        reg.register(dispatch_id="d3", session_id="s3", user="alice", turn_id="t3", interrupt_event=asyncio.Event())

        alice_dispatches = reg.list_active(user="alice")
        assert len(alice_dispatches) == 2
        assert all(d["user"] == "alice" for d in alice_dispatches)

        all_dispatches = reg.list_active()
        assert len(all_dispatches) == 3

    def test_list_active_returns_dict_shape(self) -> None:
        reg = DispatchControlRegistry()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=asyncio.Event())
        rows = reg.list_active()
        assert len(rows) == 1
        row = rows[0]
        assert "dispatch_id" in row
        assert "session_id" in row
        assert "user" in row
        assert "turn_id" in row
        assert "started_at" in row
        assert "interrupt_requested_at" in row
        assert "interrupt_source" in row

    def test_interrupt_records_metadata(self) -> None:
        reg = DispatchControlRegistry()
        event = asyncio.Event()
        reg.register(dispatch_id="d1", session_id="s1", user="alice", turn_id="t1", interrupt_event=event)
        reg.request_interrupt("d1", user="alice", source="ws")
        active = reg.get("d1")
        assert active.interrupt_requested_at is not None
        assert active.interrupt_source == "ws"


# ---------------------------------------------------------------------------
# BreakGlassSessionRegistry
# ---------------------------------------------------------------------------


class TestBreakGlassSessionRegistry:
    """Tests for per-session break-glass activation with real Argon2id."""

    @pytest.fixture()
    def bg_registry(self, tmp_path: Path) -> BreakGlassSessionRegistry:
        manager = BreakGlassManager(config_dir=tmp_path)
        manager.set_passphrase("test-passphrase-123")
        return BreakGlassSessionRegistry(manager)

    def test_activate_with_correct_passphrase(self, bg_registry: BreakGlassSessionRegistry) -> None:
        ok, expires_at = bg_registry.activate(
            user="alice", session_id="s1", passphrase="test-passphrase-123"
        )
        assert ok is True
        assert expires_at is not None

    def test_activate_with_wrong_passphrase(self, bg_registry: BreakGlassSessionRegistry) -> None:
        ok, expires_at = bg_registry.activate(
            user="alice", session_id="s1", passphrase="wrong-password"
        )
        assert ok is False
        assert expires_at is None

    def test_is_active_after_activation(self, bg_registry: BreakGlassSessionRegistry) -> None:
        bg_registry.activate(user="alice", session_id="s1", passphrase="test-passphrase-123")
        assert bg_registry.is_active(user="alice", session_id="s1") is True

    def test_is_active_without_activation(self, bg_registry: BreakGlassSessionRegistry) -> None:
        assert bg_registry.is_active(user="alice", session_id="s1") is False

    def test_deactivate(self, bg_registry: BreakGlassSessionRegistry) -> None:
        bg_registry.activate(user="alice", session_id="s1", passphrase="test-passphrase-123")
        result = bg_registry.deactivate(user="alice", session_id="s1")
        assert result is True
        assert bg_registry.is_active(user="alice", session_id="s1") is False

    def test_deactivate_not_active(self, bg_registry: BreakGlassSessionRegistry) -> None:
        result = bg_registry.deactivate(user="alice", session_id="s1")
        assert result is False

    def test_session_isolation(self, bg_registry: BreakGlassSessionRegistry) -> None:
        """Different sessions for same user are independent."""
        bg_registry.activate(user="alice", session_id="s1", passphrase="test-passphrase-123")
        assert bg_registry.is_active(user="alice", session_id="s1") is True
        assert bg_registry.is_active(user="alice", session_id="s2") is False

    def test_user_isolation(self, bg_registry: BreakGlassSessionRegistry) -> None:
        """Different users are independent."""
        bg_registry.activate(user="alice", session_id="s1", passphrase="test-passphrase-123")
        assert bg_registry.is_active(user="bob", session_id="s1") is False

    def test_status_shape(self, bg_registry: BreakGlassSessionRegistry) -> None:
        status = bg_registry.status(user="alice", session_id="s1")
        assert "active" in status
        assert "expires_at" in status
        assert "locked_out" in status
        assert "has_passphrase" in status

    def test_status_reflects_activation(self, bg_registry: BreakGlassSessionRegistry) -> None:
        bg_registry.activate(user="alice", session_id="s1", passphrase="test-passphrase-123")
        status = bg_registry.status(user="alice", session_id="s1")
        assert status["active"] is True
        assert status["expires_at"] is not None

    def test_custom_ttl(self, bg_registry: BreakGlassSessionRegistry) -> None:
        ok, expires_at = bg_registry.activate(
            user="alice", session_id="s1", passphrase="test-passphrase-123", ttl_minutes=5
        )
        assert ok is True
        assert expires_at is not None
