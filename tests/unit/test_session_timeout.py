"""Behavioral tests for session idle timeout tracker (F-013).

Uses small timeout values with time.sleep for fast, real-behavior tests.
No mocks, no monkeypatch.
"""

from __future__ import annotations

import time

from corvus.security.session_timeout import SessionTimeoutConfig, SessionTimeoutTracker


class TestSessionTimeoutConfig:
    def test_default_values(self) -> None:
        config = SessionTimeoutConfig()
        assert config.idle_timeout_seconds == 1800.0
        assert config.break_glass_auto_deactivate is True

    def test_custom_values(self) -> None:
        config = SessionTimeoutConfig(
            idle_timeout_seconds=60.0,
            break_glass_auto_deactivate=False,
        )
        assert config.idle_timeout_seconds == 60.0
        assert config.break_glass_auto_deactivate is False


class TestSessionTimeoutTracker:
    def _make_tracker(
        self, timeout: float = 0.1, auto_deactivate: bool = True
    ) -> SessionTimeoutTracker:
        return SessionTimeoutTracker(
            SessionTimeoutConfig(
                idle_timeout_seconds=timeout,
                break_glass_auto_deactivate=auto_deactivate,
            )
        )

    def test_unknown_session_is_not_idle(self) -> None:
        tracker = self._make_tracker()
        assert tracker.is_idle("unknown") is False

    def test_unknown_session_idle_seconds_is_none(self) -> None:
        tracker = self._make_tracker()
        assert tracker.idle_seconds("unknown") is None

    def test_recently_active_session_is_not_idle(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        assert tracker.is_idle("s1") is False

    def test_session_becomes_idle_after_timeout(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        time.sleep(0.15)
        assert tracker.is_idle("s1") is True

    def test_idle_seconds_increases_over_time(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        time.sleep(0.05)
        elapsed = tracker.idle_seconds("s1")
        assert elapsed is not None
        assert elapsed >= 0.04  # small tolerance

    def test_record_activity_resets_idle(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        time.sleep(0.15)
        assert tracker.is_idle("s1") is True
        tracker.record_activity("s1")
        assert tracker.is_idle("s1") is False

    def test_should_deactivate_break_glass_when_idle(self) -> None:
        tracker = self._make_tracker(timeout=0.1, auto_deactivate=True)
        tracker.record_activity("s1")
        time.sleep(0.15)
        assert tracker.should_deactivate_break_glass("s1") is True

    def test_should_not_deactivate_break_glass_when_active(self) -> None:
        tracker = self._make_tracker(timeout=0.1, auto_deactivate=True)
        tracker.record_activity("s1")
        assert tracker.should_deactivate_break_glass("s1") is False

    def test_should_not_deactivate_when_auto_deactivate_disabled(self) -> None:
        tracker = self._make_tracker(timeout=0.1, auto_deactivate=False)
        tracker.record_activity("s1")
        time.sleep(0.15)
        assert tracker.should_deactivate_break_glass("s1") is False

    def test_should_not_deactivate_unknown_session(self) -> None:
        tracker = self._make_tracker(timeout=0.1, auto_deactivate=True)
        assert tracker.should_deactivate_break_glass("unknown") is False

    def test_remove_session_clears_tracking(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        tracker.remove_session("s1")
        assert tracker.idle_seconds("s1") is None
        assert tracker.is_idle("s1") is False

    def test_remove_nonexistent_session_is_noop(self) -> None:
        tracker = self._make_tracker()
        tracker.remove_session("nonexistent")  # should not raise

    def test_multiple_sessions_tracked_independently(self) -> None:
        tracker = self._make_tracker(timeout=0.1)
        tracker.record_activity("s1")
        time.sleep(0.15)
        tracker.record_activity("s2")
        assert tracker.is_idle("s1") is True
        assert tracker.is_idle("s2") is False

    def test_default_config_when_none_provided(self) -> None:
        tracker = SessionTimeoutTracker()
        tracker.record_activity("s1")
        assert tracker.is_idle("s1") is False
        elapsed = tracker.idle_seconds("s1")
        assert elapsed is not None
        assert elapsed < 1.0
