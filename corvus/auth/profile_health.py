"""Profile health -- failure recording, cooldown, and health status.

Tracks failures per profile and applies escalating cooldowns.
Permanent auth failures disable the profile until manual intervention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from corvus.auth.profiles import AuthProfileStore, ProfileUsageStats, evaluate_credential_eligibility

# (failure_count_threshold, cooldown_ms)
COOLDOWN_THRESHOLDS: list[tuple[int, int]] = [
    (3, 60_000),       # 3 failures -> 1 min cooldown
    (6, 300_000),      # 6 failures -> 5 min cooldown
    (10, 900_000),     # 10 failures -> 15 min cooldown
    (15, 3_600_000),   # 15 failures -> 1 hour cooldown
]

# Permanent auth failure disables for 24 hours
PERMANENT_DISABLE_MS = 86_400_000


@dataclass
class ProfileHealth:
    """Health status of a single profile."""

    status: str  # "healthy", "cooldown", "disabled", "expired", "missing"
    reason: str = ""
    cooldown_remaining_ms: int = 0


def record_profile_failure(
    store: AuthProfileStore,
    profile_id: str,
    *,
    reason: str,
    now: int | None = None,
) -> None:
    """Record a failure for a profile and apply cooldown if threshold is met."""
    if now is None:
        now = int(time.time() * 1000)

    if profile_id not in store.usage_stats:
        store.usage_stats[profile_id] = ProfileUsageStats()

    stats = store.usage_stats[profile_id]
    stats.error_count += 1
    stats.last_failure_at = now
    stats.disabled_reason = reason

    # Permanent auth failure -> disable immediately
    if reason == "auth_permanent":
        stats.disabled_until = now + PERMANENT_DISABLE_MS
        return

    # Escalating cooldown
    for threshold, cooldown_ms in COOLDOWN_THRESHOLDS:
        if stats.error_count >= threshold:
            stats.cooldown_until = now + cooldown_ms


def record_profile_success(
    store: AuthProfileStore,
    profile_id: str,
    *,
    now: int | None = None,
) -> None:
    """Record a successful use -- resets error count and cooldown."""
    if now is None:
        now = int(time.time() * 1000)

    if profile_id not in store.usage_stats:
        store.usage_stats[profile_id] = ProfileUsageStats()

    stats = store.usage_stats[profile_id]
    stats.error_count = 0
    stats.cooldown_until = 0
    stats.last_used = now
    store.last_good[profile_id.split(":")[0] if ":" in profile_id else profile_id] = profile_id


def get_profile_health(
    store: AuthProfileStore,
    profile_id: str,
    *,
    now: int | None = None,
) -> ProfileHealth:
    """Return the current health status of a profile."""
    if now is None:
        now = int(time.time() * 1000)

    if profile_id not in store.profiles:
        return ProfileHealth(status="missing", reason="profile_not_found")

    stats = store.usage_stats.get(profile_id)
    if stats:
        if stats.disabled_until > 0 and now < stats.disabled_until:
            return ProfileHealth(
                status="disabled",
                reason=stats.disabled_reason,
                cooldown_remaining_ms=stats.disabled_until - now,
            )
        if stats.cooldown_until > 0 and now < stats.cooldown_until:
            return ProfileHealth(
                status="cooldown",
                reason=stats.disabled_reason,
                cooldown_remaining_ms=stats.cooldown_until - now,
            )

    cred = store.profiles[profile_id]
    eligibility = evaluate_credential_eligibility(cred, now=now)
    if not eligibility.eligible:
        return ProfileHealth(status=eligibility.reason, reason=eligibility.reason)

    return ProfileHealth(status="healthy")
