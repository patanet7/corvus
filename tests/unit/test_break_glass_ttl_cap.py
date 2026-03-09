"""Behavioral tests for BreakGlassSessionRegistry TTL cap enforcement (F-006).

Every test uses a real BreakGlassManager with a real Argon2id passphrase
stored on disk in a temporary directory -- no mocks.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from corvus.break_glass import BreakGlassManager
from corvus.gateway.control_plane import BreakGlassSessionRegistry

PASSPHRASE = "correct-horse-battery-staple"


@pytest.fixture()
def manager_and_registry():
    """Yield a (BreakGlassManager, BreakGlassSessionRegistry) pair
    with max_ttl_minutes=240, backed by a real temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        mgr = BreakGlassManager(config_dir=Path(tmp))
        mgr.set_passphrase(PASSPHRASE)
        registry = BreakGlassSessionRegistry(mgr, default_ttl_minutes=30, max_ttl_minutes=240)
        yield mgr, registry


class TestTTLCapEnforcement:
    """Break-glass TTL must be capped at max_ttl_minutes."""

    def test_excessive_ttl_is_capped(self, manager_and_registry):
        """Requesting ttl_minutes=9999 must be capped to max_ttl_minutes (240)."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s1",
            passphrase=PASSPHRASE,
            ttl_minutes=9999,
        )
        assert ok is True
        assert expires_at is not None
        # The expiry should be at most ~240 minutes from now, not 9999.
        now = datetime.now(UTC)
        delta = expires_at - now
        assert delta <= timedelta(minutes=241)  # small tolerance
        assert delta > timedelta(minutes=239)

    def test_reasonable_ttl_unchanged(self, manager_and_registry):
        """Requesting ttl_minutes=60 should be honoured as-is."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s2",
            passphrase=PASSPHRASE,
            ttl_minutes=60,
        )
        assert ok is True
        assert expires_at is not None
        now = datetime.now(UTC)
        delta = expires_at - now
        assert delta <= timedelta(minutes=61)
        assert delta > timedelta(minutes=59)

    def test_default_ttl_used_when_none(self, manager_and_registry):
        """When ttl_minutes is None, default_ttl_minutes (30) applies."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s3",
            passphrase=PASSPHRASE,
            ttl_minutes=None,
        )
        assert ok is True
        assert expires_at is not None
        now = datetime.now(UTC)
        delta = expires_at - now
        assert delta <= timedelta(minutes=31)
        assert delta > timedelta(minutes=29)

    def test_negative_ttl_clamped_to_one(self, manager_and_registry):
        """Negative ttl_minutes must be clamped to 1."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s4",
            passphrase=PASSPHRASE,
            ttl_minutes=-100,
        )
        assert ok is True
        assert expires_at is not None
        now = datetime.now(UTC)
        delta = expires_at - now
        assert delta <= timedelta(minutes=2)
        assert delta > timedelta(seconds=30)

    def test_zero_ttl_clamped_to_one(self, manager_and_registry):
        """Zero ttl_minutes must be clamped to 1."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s5",
            passphrase=PASSPHRASE,
            ttl_minutes=0,
        )
        assert ok is True
        assert expires_at is not None
        now = datetime.now(UTC)
        delta = expires_at - now
        assert delta <= timedelta(minutes=2)
        assert delta > timedelta(seconds=30)

    def test_wrong_passphrase_rejected(self, manager_and_registry):
        """Wrong passphrase still rejected regardless of TTL."""
        _mgr, registry = manager_and_registry
        ok, expires_at = registry.activate(
            user="admin",
            session_id="s6",
            passphrase="wrong-passphrase",
            ttl_minutes=60,
        )
        assert ok is False
        assert expires_at is None

    def test_max_ttl_constructor_floor(self):
        """max_ttl_minutes=0 or negative should be clamped to 1."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = BreakGlassManager(config_dir=Path(tmp))
            mgr.set_passphrase(PASSPHRASE)
            registry = BreakGlassSessionRegistry(mgr, max_ttl_minutes=0)
            assert registry._max_ttl_minutes == 1

            registry2 = BreakGlassSessionRegistry(mgr, max_ttl_minutes=-5)
            assert registry2._max_ttl_minutes == 1
