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
