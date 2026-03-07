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
