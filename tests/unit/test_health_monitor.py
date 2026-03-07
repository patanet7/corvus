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
