"""Session idle timeout tracker.

Tracks last activity per session. When idle timeout exceeds configured
limit, signals that break-glass should be deactivated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class SessionTimeoutConfig:
    idle_timeout_seconds: float = 1800.0  # 30 minutes default
    break_glass_auto_deactivate: bool = True


class SessionTimeoutTracker:
    def __init__(self, config: SessionTimeoutConfig | None = None) -> None:
        self._config = config or SessionTimeoutConfig()
        self._last_activity: dict[str, float] = {}

    def record_activity(self, session_id: str) -> None:
        self._last_activity[session_id] = time.monotonic()

    def is_idle(self, session_id: str) -> bool:
        last = self._last_activity.get(session_id)
        if last is None:
            return False  # Never active = not idle (hasn't started)
        return (time.monotonic() - last) > self._config.idle_timeout_seconds

    def idle_seconds(self, session_id: str) -> float | None:
        last = self._last_activity.get(session_id)
        if last is None:
            return None
        return time.monotonic() - last

    def should_deactivate_break_glass(self, session_id: str) -> bool:
        return self._config.break_glass_auto_deactivate and self.is_idle(session_id)

    def remove_session(self, session_id: str) -> None:
        self._last_activity.pop(session_id, None)
