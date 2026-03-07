"""Auth profile resolution -- round-robin selection with cooldown and ordering.

Given a provider name and optional agent name, resolves which auth profile
to use based on: agent-specific order > provider order > round-robin by
least-recently-used, skipping cooled-down and disabled profiles.
"""

from __future__ import annotations

import time

from corvus.auth.profiles import (
    AuthProfileStore,
    ProfileUsageStats,
    evaluate_credential_eligibility,
)


def resolve_profile(
    store: AuthProfileStore,
    *,
    provider: str,
    agent_name: str | None = None,
    now: int | None = None,
) -> str | None:
    """Resolve the best auth profile for a provider.

    Resolution order:
    1. Agent-specific order (store.order['{provider}:{agent}'])
    2. Provider order (store.order['{provider}'])
    3. Round-robin by least-recently-used

    Profiles are skipped if:
    - Credential is not eligible (missing, expired)
    - Profile is in cooldown (cooldown_until > now)
    - Profile is disabled (disabled_until > now)

    Returns the profile ID, or None if no eligible profile is found.
    """
    if now is None:
        now = int(time.time() * 1000)

    # Collect all profiles for this provider
    candidates = [
        pid for pid, cred in store.profiles.items()
        if cred.provider == provider
    ]
    if not candidates:
        return None

    # Check for agent-specific order
    agent_order_key = f"{provider}:{agent_name}" if agent_name else ""
    ordered: list[str] | None = None
    if agent_order_key and agent_order_key in store.order:
        ordered = store.order[agent_order_key]
    elif provider in store.order:
        ordered = store.order[provider]

    if ordered:
        candidates = [pid for pid in ordered if pid in candidates]

    # Filter to eligible + not cooled down + not disabled
    eligible: list[str] = []
    for pid in candidates:
        cred = store.profiles[pid]
        result = evaluate_credential_eligibility(cred, now=now)
        if not result.eligible:
            continue
        stats = store.usage_stats.get(pid)
        if stats:
            if stats.cooldown_until > 0 and now < stats.cooldown_until:
                continue
            if stats.disabled_until > 0 and now < stats.disabled_until:
                continue
        eligible.append(pid)

    if not eligible:
        return None

    # If explicit order, return first eligible
    if ordered:
        return eligible[0]

    # Round-robin: pick least-recently-used
    eligible.sort(key=lambda pid: (store.usage_stats.get(pid) or ProfileUsageStats()).last_used)
    return eligible[0]
