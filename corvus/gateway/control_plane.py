"""Runtime control plane for dispatch interrupts and break-glass sessions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from corvus.break_glass import BreakGlassManager


@dataclass(slots=True)
class ActiveDispatch:
    """In-memory metadata for an active dispatch execution."""

    dispatch_id: str
    session_id: str
    user: str
    turn_id: str
    interrupt_event: asyncio.Event
    started_at: datetime
    interrupt_requested_at: datetime | None = None
    interrupt_source: str | None = None


class DispatchControlRegistry:
    """Tracks active dispatches and allows cross-path interrupt requests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._active: dict[str, ActiveDispatch] = {}

    def register(
        self,
        *,
        dispatch_id: str,
        session_id: str,
        user: str,
        turn_id: str,
        interrupt_event: asyncio.Event,
    ) -> None:
        with self._lock:
            self._active[dispatch_id] = ActiveDispatch(
                dispatch_id=dispatch_id,
                session_id=session_id,
                user=user,
                turn_id=turn_id,
                interrupt_event=interrupt_event,
                started_at=datetime.now(UTC),
            )

    def unregister(self, dispatch_id: str) -> None:
        with self._lock:
            self._active.pop(dispatch_id, None)

    def get(self, dispatch_id: str) -> ActiveDispatch | None:
        with self._lock:
            return self._active.get(dispatch_id)

    def request_interrupt(self, dispatch_id: str, *, user: str, source: str = "api") -> bool:
        """Request interruption for an active dispatch owned by *user*."""
        with self._lock:
            active = self._active.get(dispatch_id)
            if active is None or active.user != user:
                return False
            active.interrupt_requested_at = datetime.now(UTC)
            active.interrupt_source = source
            active.interrupt_event.set()
            return True

    def list_active(self, *, user: str | None = None) -> list[dict]:
        with self._lock:
            rows = list(self._active.values())
        if user:
            rows = [row for row in rows if row.user == user]
        rows.sort(key=lambda row: row.started_at, reverse=True)
        return [
            {
                "dispatch_id": row.dispatch_id,
                "session_id": row.session_id,
                "user": row.user,
                "turn_id": row.turn_id,
                "started_at": row.started_at.isoformat(),
                "interrupt_requested_at": row.interrupt_requested_at.isoformat()
                if row.interrupt_requested_at
                else None,
                "interrupt_source": row.interrupt_source,
            }
            for row in rows
        ]


class BreakGlassSessionRegistry:
    """Per-user/session break-glass activation built on BreakGlassManager."""

    def __init__(
        self,
        manager: BreakGlassManager,
        *,
        default_ttl_minutes: int = 30,
        max_ttl_minutes: int = 240,
    ) -> None:
        self._manager = manager
        self._default_ttl_minutes = max(1, default_ttl_minutes)
        self._max_ttl_minutes = max(1, max_ttl_minutes)
        self._lock = RLock()
        self._active_until: dict[tuple[str, str], datetime] = {}

    def activate(
        self,
        *,
        user: str,
        session_id: str,
        passphrase: str,
        ttl_minutes: int | None = None,
    ) -> tuple[bool, datetime | None]:
        """Activate break-glass for user/session if passphrase verification succeeds."""
        if not self._manager.verify_passphrase(passphrase):
            return False, None

        minutes = ttl_minutes if ttl_minutes is not None else self._default_ttl_minutes
        minutes = min(max(1, minutes), self._max_ttl_minutes)
        expires_at = datetime.now(UTC) + timedelta(minutes=minutes)
        with self._lock:
            self._active_until[(user, session_id)] = expires_at
        return True, expires_at

    def deactivate(self, *, user: str, session_id: str) -> bool:
        with self._lock:
            return self._active_until.pop((user, session_id), None) is not None

    def is_active(self, *, user: str, session_id: str) -> bool:
        with self._lock:
            expires_at = self._active_until.get((user, session_id))
        if expires_at is None:
            return False
        if datetime.now(UTC) >= expires_at:
            self.deactivate(user=user, session_id=session_id)
            return False
        return True

    def status(self, *, user: str, session_id: str) -> dict:
        with self._lock:
            expires_at = self._active_until.get((user, session_id))
        active = False
        if expires_at and datetime.now(UTC) < expires_at:
            active = True
        elif expires_at:
            self.deactivate(user=user, session_id=session_id)
            expires_at = None
        return {
            "active": active,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "locked_out": self._manager.is_locked_out(),
            "has_passphrase": self._manager.has_passphrase(),
        }
