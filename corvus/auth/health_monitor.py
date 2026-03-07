"""Credential health monitoring -- aggregate health status for all profiles.

Provides data for the setup wizard dashboard and /health API endpoint.
"""

from __future__ import annotations

from corvus.auth.profile_health import ProfileHealth, get_profile_health
from corvus.auth.profiles import AuthProfileStore


def get_all_profile_health(
    store: AuthProfileStore,
    *,
    now: int | None = None,
) -> dict[str, ProfileHealth]:
    """Return health status for every profile in the store.

    Returns a dict mapping profile_id -> ProfileHealth.
    """
    result: dict[str, ProfileHealth] = {}
    for profile_id in store.profiles:
        result[profile_id] = get_profile_health(store, profile_id, now=now)
    return result
