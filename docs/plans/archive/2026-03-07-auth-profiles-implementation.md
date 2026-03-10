---
title: "Auth Profiles Implementation Plan"
type: plan
status: implemented
date: 2026-03-07
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Auth Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenClaw-style auth profiles to Corvus — multiple credentials per provider, round-robin rotation, failure tracking with auto-cooldown, per-agent profile overrides, and credential health monitoring. All SOPS-encrypted at rest.

**Architecture:** New `AuthProfileStore` class sits between `CredentialStore` (raw SOPS storage) and `ModelRouter` (model selection). Profiles are stored as a new `_auth_profiles` section in the existing SOPS-encrypted `credentials.json`. The model router gains an `auth_profile` field per agent. At inject time, the auth profile store resolves which credential to use based on profile ordering, cooldown state, and agent overrides.

**Tech Stack:** Python 3.13, dataclasses, existing CredentialStore + SOPS+age, existing ModelRouter

**Design reference:** OpenClaw's `src/agents/auth-profiles/` (types.ts, credential-state.ts, store.ts, usage.ts, order.ts)

**Project rules:**
- NO MOCKS in tests (no MagicMock, monkeypatch, @patch, unittest.mock)
- NO LAZY IMPORTS — all imports at module top
- NO RELATIVE IMPORTS — always `from corvus.x import y`
- Tests must be behavioral — exercise real code
- Use `uv run python` not bare `python3`
- Test output goes to `tests/output/` with timestamps

---

### Task 12: Auth profile types and data model

Define the core types for auth profiles. These mirror OpenClaw's type system but are Python dataclasses stored in SOPS.

**Files:**
- Create: `corvus/auth/profiles.py`
- Create: `tests/unit/test_auth_profile_types.py`

**Step 1: Write the failing tests**

```python
"""Tests for auth profile types."""

from corvus.auth.profiles import (
    ApiKeyCredential,
    AuthProfileStore,
    OAuthCredential,
    TokenCredential,
)


class TestCredentialTypes:
    def test_api_key_credential(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="sk-ant-api3...")
        assert cred.type == "api_key"
        assert cred.provider == "anthropic"
        assert cred.key == "sk-ant-api3..."

    def test_token_credential(self) -> None:
        cred = TokenCredential(provider="anthropic", token="sk-ant-oat01-...")
        assert cred.type == "token"
        assert cred.expires is None

    def test_token_credential_with_expiry(self) -> None:
        cred = TokenCredential(provider="anthropic", token="tok", expires=1700000000000)
        assert cred.expires == 1700000000000

    def test_oauth_credential(self) -> None:
        cred = OAuthCredential(
            provider="codex",
            access_token="eyJ...",
            refresh_token="eyJ...",
            expires=1700000000000,
        )
        assert cred.type == "oauth"

    def test_store_empty(self) -> None:
        store = AuthProfileStore()
        assert store.profiles == {}
        assert store.order == {}
        assert store.usage_stats == {}

    def test_store_add_profile(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-..."
        )
        assert "anthropic:default" in store.profiles

    def test_store_serialization_roundtrip(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-..."
        )
        data = store.to_dict()
        restored = AuthProfileStore.from_dict(data)
        assert restored.profiles["anthropic:default"].key == "sk-ant-..."
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_auth_profile_types.py -v`
Expected: FAIL — module not found

**Step 3: Implement the types**

Create `corvus/auth/profiles.py`:

```python
"""Auth profile types — multi-credential per-provider storage.

Profiles are named credentials (e.g. 'anthropic:default', 'anthropic:backup')
that support round-robin rotation, failure tracking, and per-agent overrides.
All stored SOPS-encrypted in the credential store.

Modeled after OpenClaw's auth profile system, with SOPS encryption at rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiKeyCredential:
    """Static API key credential (e.g. sk-ant-api3...)."""

    provider: str
    key: str = ""
    email: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    type: str = field(default="api_key", init=False)


@dataclass
class TokenCredential:
    """Static bearer token (e.g. setup-token from claude setup-token).

    Not refreshable — treated like an API key but with optional expiry.
    """

    provider: str
    token: str = ""
    expires: int | None = None
    email: str = ""
    type: str = field(default="token", init=False)


@dataclass
class OAuthCredential:
    """OAuth credential with access/refresh tokens (e.g. Codex PKCE flow)."""

    provider: str
    access_token: str = ""
    refresh_token: str = ""
    expires: int = 0
    account_id: str = ""
    client_id: str = ""
    email: str = ""
    type: str = field(default="oauth", init=False)


AuthProfileCredential = ApiKeyCredential | TokenCredential | OAuthCredential


@dataclass
class ProfileUsageStats:
    """Per-profile usage statistics for rotation and cooldown tracking."""

    last_used: int = 0
    cooldown_until: int = 0
    disabled_until: int = 0
    disabled_reason: str = ""
    error_count: int = 0
    last_failure_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_used": self.last_used,
            "cooldown_until": self.cooldown_until,
            "disabled_until": self.disabled_until,
            "disabled_reason": self.disabled_reason,
            "error_count": self.error_count,
            "last_failure_at": self.last_failure_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileUsageStats:
        return cls(
            last_used=data.get("last_used", 0),
            cooldown_until=data.get("cooldown_until", 0),
            disabled_until=data.get("disabled_until", 0),
            disabled_reason=data.get("disabled_reason", ""),
            error_count=data.get("error_count", 0),
            last_failure_at=data.get("last_failure_at", 0),
        )


@dataclass
class AuthProfileStore:
    """In-memory store of all auth profiles with ordering and usage stats.

    Serialized to/from a dict for SOPS-encrypted storage in credentials.json
    under the '_auth_profiles' key.
    """

    profiles: dict[str, AuthProfileCredential] = field(default_factory=dict)
    order: dict[str, list[str]] = field(default_factory=dict)
    last_good: dict[str, str] = field(default_factory=dict)
    usage_stats: dict[str, ProfileUsageStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"version": 1, "profiles": {}, "order": self.order, "last_good": self.last_good, "usage_stats": {}}
        for pid, cred in self.profiles.items():
            if isinstance(cred, ApiKeyCredential):
                result["profiles"][pid] = {
                    "type": "api_key", "provider": cred.provider,
                    "key": cred.key, "email": cred.email, "metadata": cred.metadata,
                }
            elif isinstance(cred, TokenCredential):
                result["profiles"][pid] = {
                    "type": "token", "provider": cred.provider,
                    "token": cred.token, "expires": cred.expires, "email": cred.email,
                }
            elif isinstance(cred, OAuthCredential):
                result["profiles"][pid] = {
                    "type": "oauth", "provider": cred.provider,
                    "access_token": cred.access_token, "refresh_token": cred.refresh_token,
                    "expires": cred.expires, "account_id": cred.account_id,
                    "client_id": cred.client_id, "email": cred.email,
                }
        for pid, stats in self.usage_stats.items():
            result["usage_stats"][pid] = stats.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthProfileStore:
        store = cls()
        store.order = data.get("order", {})
        store.last_good = data.get("last_good", {})
        for pid, cred_data in data.get("profiles", {}).items():
            cred_type = cred_data.get("type", "api_key")
            if cred_type == "api_key":
                store.profiles[pid] = ApiKeyCredential(
                    provider=cred_data.get("provider", ""),
                    key=cred_data.get("key", ""),
                    email=cred_data.get("email", ""),
                    metadata=cred_data.get("metadata", {}),
                )
            elif cred_type == "token":
                store.profiles[pid] = TokenCredential(
                    provider=cred_data.get("provider", ""),
                    token=cred_data.get("token", ""),
                    expires=cred_data.get("expires"),
                    email=cred_data.get("email", ""),
                )
            elif cred_type == "oauth":
                store.profiles[pid] = OAuthCredential(
                    provider=cred_data.get("provider", ""),
                    access_token=cred_data.get("access_token", ""),
                    refresh_token=cred_data.get("refresh_token", ""),
                    expires=cred_data.get("expires", 0),
                    account_id=cred_data.get("account_id", ""),
                    client_id=cred_data.get("client_id", ""),
                    email=cred_data.get("email", ""),
                )
        for pid, stats_data in data.get("usage_stats", {}).items():
            store.usage_stats[pid] = ProfileUsageStats.from_dict(stats_data)
        return store
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_auth_profile_types.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add corvus/auth/profiles.py tests/unit/test_auth_profile_types.py
git commit -m "feat: add auth profile types — multi-credential per-provider data model"
```

---

### Task 13: Credential eligibility evaluation

Determine if a credential is usable: check for missing keys, expired tokens, invalid expiry values.

**Files:**
- Modify: `corvus/auth/profiles.py` — add `evaluate_credential_eligibility()`
- Create: `tests/unit/test_credential_eligibility.py`

**Step 1: Write the failing tests**

```python
"""Tests for credential eligibility evaluation."""

import time

from corvus.auth.profiles import (
    ApiKeyCredential,
    OAuthCredential,
    TokenCredential,
    evaluate_credential_eligibility,
)


class TestEvaluateCredentialEligibility:
    def test_api_key_with_key_is_eligible(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="sk-ant-...")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True
        assert result.reason == "ok"

    def test_api_key_without_key_is_ineligible(self) -> None:
        cred = ApiKeyCredential(provider="anthropic", key="")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is False
        assert result.reason == "missing_credential"

    def test_token_valid_no_expiry(self) -> None:
        cred = TokenCredential(provider="anthropic", token="sk-ant-oat01-...")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_token_expired(self) -> None:
        cred = TokenCredential(provider="anthropic", token="tok", expires=1000)
        result = evaluate_credential_eligibility(cred, now=2000)
        assert result.eligible is False
        assert result.reason == "expired"

    def test_token_valid_future_expiry(self) -> None:
        future = int(time.time() * 1000) + 3600000
        cred = TokenCredential(provider="anthropic", token="tok", expires=future)
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_oauth_with_access_token(self) -> None:
        future = int(time.time() * 1000) + 3600000
        cred = OAuthCredential(
            provider="codex", access_token="eyJ...", expires=future
        )
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is True

    def test_oauth_expired(self) -> None:
        cred = OAuthCredential(
            provider="codex", access_token="eyJ...", expires=1000
        )
        result = evaluate_credential_eligibility(cred, now=2000)
        assert result.eligible is False
        assert result.reason == "expired"

    def test_oauth_missing_tokens(self) -> None:
        cred = OAuthCredential(provider="codex")
        result = evaluate_credential_eligibility(cred)
        assert result.eligible is False
        assert result.reason == "missing_credential"
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_credential_eligibility.py -v`

**Step 3: Implement**

Add to `corvus/auth/profiles.py`:

```python
@dataclass
class EligibilityResult:
    """Result of credential eligibility check."""
    eligible: bool
    reason: str  # "ok", "missing_credential", "expired", "invalid_expires"


def evaluate_credential_eligibility(
    credential: AuthProfileCredential,
    now: int | None = None,
) -> EligibilityResult:
    """Check if a credential is usable right now.

    Args:
        credential: The credential to evaluate.
        now: Current time in milliseconds since epoch. Defaults to time.time() * 1000.

    Returns:
        EligibilityResult with eligible=True/False and reason code.
    """
    if now is None:
        now = int(time.time() * 1000)

    if isinstance(credential, ApiKeyCredential):
        if not credential.key:
            return EligibilityResult(eligible=False, reason="missing_credential")
        return EligibilityResult(eligible=True, reason="ok")

    if isinstance(credential, TokenCredential):
        if not credential.token:
            return EligibilityResult(eligible=False, reason="missing_credential")
        if credential.expires is not None:
            if credential.expires <= 0:
                return EligibilityResult(eligible=False, reason="invalid_expires")
            if now >= credential.expires:
                return EligibilityResult(eligible=False, reason="expired")
        return EligibilityResult(eligible=True, reason="ok")

    if isinstance(credential, OAuthCredential):
        if not credential.access_token and not credential.refresh_token:
            return EligibilityResult(eligible=False, reason="missing_credential")
        if credential.expires > 0 and now >= credential.expires:
            return EligibilityResult(eligible=False, reason="expired")
        return EligibilityResult(eligible=True, reason="ok")

    return EligibilityResult(eligible=False, reason="missing_credential")
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_credential_eligibility.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add corvus/auth/profiles.py tests/unit/test_credential_eligibility.py
git commit -m "feat: add credential eligibility evaluation"
```

---

### Task 14: Round-robin profile resolution with cooldown

Resolve which profile to use for a provider, considering ordering, cooldown state, and last-good tracking.

**Files:**
- Create: `corvus/auth/profile_resolver.py`
- Create: `tests/unit/test_profile_resolver.py`

**Step 1: Write the failing tests**

```python
"""Tests for auth profile resolution — round-robin, cooldown, ordering."""

import time

from corvus.auth.profile_resolver import resolve_profile
from corvus.auth.profiles import (
    ApiKeyCredential,
    AuthProfileStore,
    ProfileUsageStats,
)


class TestResolveProfile:
    def test_single_profile(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        result = resolve_profile(store, provider="anthropic")
        assert result == "anthropic:default"

    def test_respects_explicit_order(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:primary"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:backup"] = ApiKeyCredential(provider="anthropic", key="sk-2")
        store.order["anthropic"] = ["anthropic:backup", "anthropic:primary"]
        result = resolve_profile(store, provider="anthropic")
        assert result == "anthropic:backup"

    def test_skips_cooled_down_profile(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:primary"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:backup"] = ApiKeyCredential(provider="anthropic", key="sk-2")
        store.usage_stats["anthropic:primary"] = ProfileUsageStats(
            cooldown_until=now + 60000  # cooled down for 60s
        )
        result = resolve_profile(store, provider="anthropic")
        assert result == "anthropic:backup"

    def test_skips_disabled_profile(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:a"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:b"] = ApiKeyCredential(provider="anthropic", key="sk-2")
        store.usage_stats["anthropic:a"] = ProfileUsageStats(
            disabled_until=now + 60000, disabled_reason="auth"
        )
        result = resolve_profile(store, provider="anthropic")
        assert result == "anthropic:b"

    def test_round_robin_by_last_used(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:a"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:b"] = ApiKeyCredential(provider="anthropic", key="sk-2")
        store.usage_stats["anthropic:a"] = ProfileUsageStats(last_used=now - 1000)
        store.usage_stats["anthropic:b"] = ProfileUsageStats(last_used=now - 5000)
        # b was used longer ago, so it should be picked
        result = resolve_profile(store, provider="anthropic")
        assert result == "anthropic:b"

    def test_returns_none_when_no_profiles(self) -> None:
        store = AuthProfileStore()
        result = resolve_profile(store, provider="anthropic")
        assert result is None

    def test_returns_none_when_all_cooled_down(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:a"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.usage_stats["anthropic:a"] = ProfileUsageStats(cooldown_until=now + 60000)
        result = resolve_profile(store, provider="anthropic")
        assert result is None

    def test_agent_override(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:max-sub"] = ApiKeyCredential(provider="anthropic", key="sk-2")
        store.order["anthropic:homelab"] = ["anthropic:max-sub"]
        result = resolve_profile(store, provider="anthropic", agent_name="homelab")
        assert result == "anthropic:max-sub"
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_profile_resolver.py -v`

**Step 3: Implement**

Create `corvus/auth/profile_resolver.py`:

```python
"""Auth profile resolution — round-robin selection with cooldown and ordering.

Given a provider name and optional agent name, resolves which auth profile
to use based on: agent-specific order > provider order > round-robin by
least-recently-used, skipping cooled-down and disabled profiles.
"""

from __future__ import annotations

import time

from corvus.auth.profiles import (
    AuthProfileStore,
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
        # Use explicit order, filtering to existing candidates
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
```

Add missing import at top:

```python
from corvus.auth.profiles import ProfileUsageStats
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_profile_resolver.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add corvus/auth/profile_resolver.py tests/unit/test_profile_resolver.py
git commit -m "feat: add round-robin profile resolution with cooldown and agent overrides"
```

---

### Task 15: Failure recording and auto-cooldown

When an API call fails with a rate limit or auth error, record the failure and apply cooldown thresholds.

**Files:**
- Create: `corvus/auth/profile_health.py`
- Create: `tests/unit/test_profile_health.py`

**Step 1: Write the failing tests**

```python
"""Tests for profile failure recording and auto-cooldown."""

import time

from corvus.auth.profile_health import (
    COOLDOWN_THRESHOLDS,
    record_profile_failure,
    record_profile_success,
    get_profile_health,
)
from corvus.auth.profiles import AuthProfileStore, ApiKeyCredential, ProfileUsageStats


class TestRecordProfileFailure:
    def test_first_failure_increments_count(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        record_profile_failure(store, "anthropic:default", reason="rate_limit")
        stats = store.usage_stats["anthropic:default"]
        assert stats.error_count == 1
        assert stats.disabled_reason == "rate_limit"

    def test_three_failures_triggers_cooldown(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        for _ in range(3):
            record_profile_failure(store, "anthropic:default", reason="rate_limit")
        stats = store.usage_stats["anthropic:default"]
        assert stats.cooldown_until > 0

    def test_auth_permanent_disables_immediately(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        record_profile_failure(store, "anthropic:default", reason="auth_permanent")
        stats = store.usage_stats["anthropic:default"]
        assert stats.disabled_until > int(time.time() * 1000)
        assert stats.disabled_reason == "auth_permanent"


class TestRecordProfileSuccess:
    def test_success_resets_error_count(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.usage_stats["anthropic:default"] = ProfileUsageStats(error_count=5)
        record_profile_success(store, "anthropic:default")
        stats = store.usage_stats["anthropic:default"]
        assert stats.error_count == 0
        assert stats.cooldown_until == 0
        assert stats.last_used > 0


class TestGetProfileHealth:
    def test_healthy_profile(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        health = get_profile_health(store, "anthropic:default")
        assert health.status == "healthy"

    def test_cooled_down_profile(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.usage_stats["anthropic:default"] = ProfileUsageStats(cooldown_until=now + 60000)
        health = get_profile_health(store, "anthropic:default")
        assert health.status == "cooldown"

    def test_disabled_profile(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.usage_stats["anthropic:default"] = ProfileUsageStats(
            disabled_until=now + 60000, disabled_reason="auth_permanent"
        )
        health = get_profile_health(store, "anthropic:default")
        assert health.status == "disabled"
        assert health.reason == "auth_permanent"
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_profile_health.py -v`

**Step 3: Implement**

Create `corvus/auth/profile_health.py`:

```python
"""Profile health — failure recording, cooldown, and health status.

Tracks failures per profile and applies escalating cooldowns.
Permanent auth failures disable the profile until manual intervention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from corvus.auth.profiles import AuthProfileStore, ProfileUsageStats

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
    """Record a successful use — resets error count and cooldown."""
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

    # Check credential eligibility
    from corvus.auth.profiles import evaluate_credential_eligibility

    cred = store.profiles[profile_id]
    eligibility = evaluate_credential_eligibility(cred, now=now)
    if not eligibility.eligible:
        return ProfileHealth(status=eligibility.reason, reason=eligibility.reason)

    return ProfileHealth(status="healthy")
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_profile_health.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add corvus/auth/profile_health.py tests/unit/test_profile_health.py
git commit -m "feat: add failure recording and auto-cooldown for auth profiles"
```

---

### Task 16: SOPS persistence — store/load auth profiles in credential store

Wire `AuthProfileStore` into the existing `CredentialStore` so profiles are SOPS-encrypted alongside service credentials.

**Files:**
- Modify: `corvus/credential_store.py` — add `auth_profiles` property, load/save auth profile data
- Create: `tests/unit/test_auth_profile_persistence.py`

**Step 1: Write the failing tests**

```python
"""Tests for auth profile persistence in credential store."""

from corvus.auth.profiles import ApiKeyCredential, AuthProfileStore
from corvus.credential_store import CredentialStore


class TestAuthProfilePersistence:
    def test_empty_store_returns_empty_profiles(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}
        profiles = store.get_auth_profiles()
        assert profiles.profiles == {}

    def test_set_and_get_auth_profiles(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}

        profiles = AuthProfileStore()
        profiles.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-ant-test"
        )
        store.set_auth_profiles(profiles)

        restored = store.get_auth_profiles()
        assert "anthropic:default" in restored.profiles
        assert restored.profiles["anthropic:default"].key == "sk-ant-test"

    def test_auth_profiles_stored_under_reserved_key(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}

        profiles = AuthProfileStore()
        profiles.profiles["openai:default"] = ApiKeyCredential(
            provider="openai", key="sk-test"
        )
        store.set_auth_profiles(profiles)

        assert "_auth_profiles" in store._data
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_auth_profile_persistence.py -v`

**Step 3: Implement**

Add to `corvus/credential_store.py` (after `credential_values()` method):

```python
def get_auth_profiles(self) -> AuthProfileStore:
    """Return the auth profile store from credential data."""
    raw = self._data.get("_auth_profiles", {})
    return AuthProfileStore.from_dict(raw)

def set_auth_profiles(self, profiles: AuthProfileStore) -> None:
    """Save auth profiles to credential data and re-encrypt if backed by file."""
    self._data["_auth_profiles"] = profiles.to_dict()
    if self._path is not None:
        self._save()
```

Add import at top of file:

```python
from corvus.auth.profiles import AuthProfileStore
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_auth_profile_persistence.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add corvus/credential_store.py tests/unit/test_auth_profile_persistence.py
git commit -m "feat: persist auth profiles in SOPS credential store"
```

---

### Task 17: Per-agent profile overrides in ModelRouter

Add `auth_profile` field to the per-agent config in `models.yaml` so agents can pin specific profiles.

**Files:**
- Modify: `corvus/model_router.py` — add `get_auth_profile()` method
- Create: `tests/unit/test_model_router_auth_profile.py`

**Step 1: Write the failing tests**

```python
"""Tests for per-agent auth profile resolution in ModelRouter."""

from corvus.model_router import ModelRouter


class TestModelRouterAuthProfile:
    def test_returns_none_when_not_configured(self) -> None:
        router = ModelRouter({"agents": {"homelab": {"model": "sonnet"}}})
        assert router.get_auth_profile("homelab") is None

    def test_returns_profile_when_configured(self) -> None:
        router = ModelRouter({
            "agents": {
                "homelab": {"model": "sonnet", "auth_profile": "anthropic:max-sub"},
            }
        })
        assert router.get_auth_profile("homelab") == "anthropic:max-sub"

    def test_returns_none_for_unknown_agent(self) -> None:
        router = ModelRouter({"agents": {}})
        assert router.get_auth_profile("nonexistent") is None
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_model_router_auth_profile.py -v`

**Step 3: Implement**

Add to `ModelRouter` class in `corvus/model_router.py`, after `get_backend()`:

```python
def get_auth_profile(self, agent_name: str) -> str | None:
    """Return the pinned auth profile for an agent, or None."""
    agent_cfg = self._agents.get(agent_name, {})
    return agent_cfg.get("auth_profile")
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_model_router_auth_profile.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add corvus/model_router.py tests/unit/test_model_router_auth_profile.py
git commit -m "feat: add per-agent auth_profile to ModelRouter"
```

---

### Task 18: Credential health monitoring — status endpoint and dashboard data

Provide a function that returns health status for all profiles, suitable for the setup wizard dashboard and the `/health` API endpoint.

**Files:**
- Create: `corvus/auth/health_monitor.py`
- Create: `tests/unit/test_health_monitor.py`

**Step 1: Write the failing tests**

```python
"""Tests for credential health monitoring."""

import time

from corvus.auth.health_monitor import get_all_profile_health
from corvus.auth.profiles import (
    ApiKeyCredential,
    AuthProfileStore,
    ProfileUsageStats,
    TokenCredential,
)


class TestGetAllProfileHealth:
    def test_all_healthy(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["openai:default"] = ApiKeyCredential(provider="openai", key="sk-2")
        health = get_all_profile_health(store)
        assert len(health) == 2
        assert all(h.status == "healthy" for h in health.values())

    def test_mixed_health(self) -> None:
        now = int(time.time() * 1000)
        store = AuthProfileStore()
        store.profiles["anthropic:a"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["anthropic:b"] = ApiKeyCredential(provider="anthropic", key="")
        store.profiles["anthropic:c"] = ApiKeyCredential(provider="anthropic", key="sk-3")
        store.usage_stats["anthropic:c"] = ProfileUsageStats(cooldown_until=now + 60000)
        health = get_all_profile_health(store)
        assert health["anthropic:a"].status == "healthy"
        assert health["anthropic:b"].status == "missing_credential"
        assert health["anthropic:c"].status == "cooldown"

    def test_groups_by_provider(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:default"] = ApiKeyCredential(provider="anthropic", key="sk-1")
        store.profiles["openai:default"] = ApiKeyCredential(provider="openai", key="sk-2")
        health = get_all_profile_health(store)
        providers = {h.split(":")[0] for h in health.keys()}
        assert providers == {"anthropic", "openai"}

    def test_expired_token_shows_expired(self) -> None:
        store = AuthProfileStore()
        store.profiles["anthropic:setup"] = TokenCredential(
            provider="anthropic", token="sk-ant-oat01-...", expires=1000
        )
        health = get_all_profile_health(store)
        assert health["anthropic:setup"].status == "expired"
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_health_monitor.py -v`

**Step 3: Implement**

Create `corvus/auth/health_monitor.py`:

```python
"""Credential health monitoring — aggregate health status for all profiles.

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
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_health_monitor.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add corvus/auth/health_monitor.py tests/unit/test_health_monitor.py
git commit -m "feat: add credential health monitoring for all profiles"
```

---

### Task 19: Wire profile resolution into inject()

Update `CredentialStore.inject()` to use auth profiles when available, falling back to legacy flat credentials.

**Files:**
- Modify: `corvus/credential_store.py` — update inject() to check auth profiles first
- Create: `tests/unit/test_inject_with_profiles.py`

**Step 1: Write the failing tests**

```python
"""Tests for inject() with auth profile support."""

import os

from corvus.auth.profiles import ApiKeyCredential, AuthProfileStore, TokenCredential
from corvus.credential_store import CredentialStore


class TestInjectWithProfiles:
    def test_inject_uses_profile_over_flat_credential(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {
            "anthropic": {"api_key": "sk-flat-key"},
        }
        profiles = AuthProfileStore()
        profiles.profiles["anthropic:default"] = ApiKeyCredential(
            provider="anthropic", key="sk-profile-key"
        )
        store.set_auth_profiles(profiles)

        store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-profile-key"

    def test_inject_falls_back_to_flat_when_no_profiles(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {"anthropic": {"api_key": "sk-flat-key"}}

        store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-flat-key"

    def test_inject_setup_token_as_api_key(self) -> None:
        store = CredentialStore.__new__(CredentialStore)
        store._path = None
        store._age_key_file = ""
        store._data = {}
        profiles = AuthProfileStore()
        profiles.profiles["anthropic:setup"] = TokenCredential(
            provider="anthropic", token="sk-ant-oat01-test-token"
        )
        store.set_auth_profiles(profiles)

        store.inject()
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-oat01-test-token"
```

**Step 2: Run tests, verify fail**

Run: `uv run python -m pytest tests/unit/test_inject_with_profiles.py -v`

**Step 3: Implement**

At the top of `inject()` in `credential_store.py`, add profile-based injection before the flat credential blocks:

```python
def inject(self) -> None:
    # --- Auth profiles (preferred) ---
    auth_profiles = self.get_auth_profiles()
    if auth_profiles.profiles:
        self._inject_from_profiles(auth_profiles)
        # Still run service injection below (HA, Paperless, etc.)
    else:
        # --- Legacy flat credentials ---
        self._inject_flat_credentials()

    # Service injection (always runs)
    self._inject_services()
```

Extract the existing flat injection into `_inject_flat_credentials()` and service injection into `_inject_services()`. Add `_inject_from_profiles()`:

```python
def _inject_from_profiles(self, auth_profiles: AuthProfileStore) -> None:
    """Inject credentials from auth profiles into environment."""
    from corvus.auth.profile_resolver import resolve_profile

    # Map provider -> env var + credential extraction
    provider_env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "ollama": "OLLAMA_BASE_URL",
        "kimi": "KIMI_BOT_TOKEN",
        "codex": "CODEX_API_KEY",
    }

    for provider, env_var in provider_env_map.items():
        profile_id = resolve_profile(auth_profiles, provider=provider)
        if profile_id is None:
            continue
        cred = auth_profiles.profiles[profile_id]
        if isinstance(cred, ApiKeyCredential) and cred.key:
            os.environ[env_var] = cred.key
        elif isinstance(cred, TokenCredential) and cred.token:
            os.environ[env_var] = cred.token
        elif isinstance(cred, OAuthCredential) and cred.access_token:
            os.environ[env_var] = cred.access_token
```

**Step 4: Run tests**

Run: `uv run python -m pytest tests/unit/test_inject_with_profiles.py -v`
Expected: PASS (3 tests)

**Step 5: Run full test suite to check for regressions**

Run: `uv run python -m pytest tests/unit/ -v --timeout=30`

**Step 6: Commit**

```bash
git add corvus/credential_store.py tests/unit/test_inject_with_profiles.py
git commit -m "feat: wire auth profile resolution into inject()"
```

---

### Task 20: Setup wizard integration — manage profiles in dashboard

Update the setup wizard dashboard to create/edit auth profiles instead of flat credentials. Each provider row maps to a profile.

**Files:**
- Modify: `corvus/cli/screens/dashboard.py` — read from auth profiles, create profiles on save
- Modify: `corvus/cli/setup.py` — save to auth profiles instead of flat credentials

**Step 1: Update dashboard to read from auth profiles**

When building provider rows, check `AuthProfileStore` first. If profiles exist for a provider, show profile count and health. If not, fall back to flat credential display.

In `_get_provider_status()`:

```python
# Check auth profiles first
profiles = self._auth_profiles
provider_profiles = {
    pid: cred for pid, cred in profiles.profiles.items()
    if cred.provider == provider_id or (provider_id == "claude" and cred.provider == "anthropic")
}
if provider_profiles:
    # Show count and health summary
    healthy = sum(1 for pid in provider_profiles if ...)
    return "configured", f"{healthy}/{len(provider_profiles)} profiles healthy"
```

**Step 2: Update save_provider_credentials to create profiles**

In `CorvusSetupApp.save_provider_credentials()`, create auth profiles instead of flat credentials:

```python
def save_provider_credentials(self, store_key: str, data: dict[str, str]) -> None:
    store = self._get_or_create_store()
    profiles = store.get_auth_profiles()

    # Create a profile from the data
    profile_id = f"{store_key}:default"
    if "api_key" in data:
        profiles.profiles[profile_id] = ApiKeyCredential(
            provider=store_key, key=data["api_key"]
        )
    elif "setup_token" in data:
        profiles.profiles[profile_id] = TokenCredential(
            provider=store_key, token=data["setup_token"]
        )
    elif "base_url" in data:
        # URL-based providers (Ollama, OpenAI-compat) — store as metadata on ApiKeyCredential
        profiles.profiles[profile_id] = ApiKeyCredential(
            provider=store_key,
            key=data.get("api_key", ""),
            metadata={"base_url": data.get("base_url", "")},
        )

    store.set_auth_profiles(profiles)
    # Also maintain flat credentials for backward compat during migration
    for key, value in data.items():
        store.set(store_key, key, value)
```

**Step 3: Test manually**

Run: `uv run python -m corvus.cli.setup`

Verify:
1. Dashboard loads
2. Configure a provider
3. Check that `_auth_profiles` section appears in credential store

**Step 4: Commit**

```bash
git add corvus/cli/screens/dashboard.py corvus/cli/setup.py
git commit -m "feat: wire setup wizard to create auth profiles on save"
```

---

### Task 21: Full test suite verification and cleanup

Run all tests, fix failures, lint, verify end-to-end.

**Files:**
- All test files from previous tasks

**Step 1: Run full test suite**

```bash
uv run python -m pytest tests/unit/ -v --timeout=30 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_auth_profiles_results.log
```

**Step 2: Run lint**

```bash
uv run ruff check corvus/ tests/
```

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "test: verify auth profiles full test suite"
```
