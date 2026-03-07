"""Tests for auth profile resolution -- round-robin, cooldown, ordering."""

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
            cooldown_until=now + 60000
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
