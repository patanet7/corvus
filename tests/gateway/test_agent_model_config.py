"""Contract test for agent model-config resolution."""

from corvus.model_router import ModelRouter, DEFAULT_CONFIG


class TestAgentModelConfig:
    """Verify model router correctly resolves per-agent config."""

    def test_get_model_returns_default_for_unknown_agent(self) -> None:
        router = ModelRouter(DEFAULT_CONFIG)
        model = router.get_model("nonexistent-agent")
        assert model == router.default_model

    def test_get_backend_returns_default_for_unknown_agent(self) -> None:
        router = ModelRouter(DEFAULT_CONFIG)
        backend = router.get_backend("nonexistent-agent")
        assert backend == router.default_backend

    def test_get_context_limit_returns_default_for_unknown_model(self) -> None:
        router = ModelRouter(DEFAULT_CONFIG)
        limit = router.get_context_limit("nonexistent-model")
        assert limit == router.default_context_limit
