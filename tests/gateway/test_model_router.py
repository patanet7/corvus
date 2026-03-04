"""Behavioral tests for the ModelRouter.

Tests exercise the real ModelRouter with real YAML files on disk.
No mocks, no patches -- real file I/O, real YAML parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from corvus.model_router import ModelRouter

SAMPLE_CONFIG = """\
defaults:
  model: sonnet
  params:
    temperature: 0.7

agents:
  router:
    model: haiku
  finance:
    model: opus
    params:
      temperature: 0.2
  homelab:
    model: kimi-k2
    fallbacks:
      - sonnet
  music:
    model: ollama/phi-3-mini
    fallbacks:
      - haiku

skills:
  data-transform:
    model: haiku
    params:
      temperature: 0.0
  summarize:
    model: sonnet
    params:
      temperature: 0.3
  code-review:
    model: opus
    params:
      temperature: 0.2

providers:
  ollama:
    api_base: http://localhost:11434
  openkimi:
    api_base: https://api.moonshot.cn/v1
"""


class TestModelRouter:
    """Behavioral tests for ModelRouter — real YAML files, no mocks."""

    @pytest.fixture(autouse=True)
    def _setup_tmp(self, tmp_path: Path):
        self._tmp_path = tmp_path

    def _make_router(self, config_text: str = SAMPLE_CONFIG) -> ModelRouter:
        """Write config to a real temp file and load it."""
        config_file = self._tmp_path / "models.yaml"
        config_file.write_text(config_text)
        return ModelRouter.from_file(config_file)

    def test_load_config(self):
        """Loading a valid YAML config sets the default model."""
        router = self._make_router()
        assert router.default_model == "sonnet"

    def test_get_agent_model_override(self):
        """Agents with explicit model overrides return that model."""
        router = self._make_router()
        assert router.get_model("finance") == "opus"
        assert router.get_model("router") == "haiku"

    def test_get_agent_model_inherits_default(self):
        """Agents not listed in config inherit the default model."""
        router = self._make_router()
        assert router.get_model("personal") == "sonnet"

    def test_get_agent_params(self):
        """Agent-specific params override defaults."""
        router = self._make_router()
        params = router.get_params("finance")
        assert params["temperature"] == 0.2

    def test_get_agent_params_inherits_default(self):
        """Agents without params inherit default params."""
        router = self._make_router()
        params = router.get_params("personal")
        assert params["temperature"] == 0.7

    def test_get_fallbacks(self):
        """Non-Claude models have fallback chains."""
        router = self._make_router()
        assert router.get_fallbacks("homelab") == ["sonnet"]
        assert router.get_fallbacks("music") == ["haiku"]

    def test_get_fallbacks_empty_for_sdk_native(self):
        """SDK-native models have no fallbacks by default."""
        router = self._make_router()
        assert router.get_fallbacks("finance") == []

    def test_is_sdk_native(self):
        """SDK-native check correctly identifies haiku/sonnet/opus vs external models."""
        router = self._make_router()
        assert router.is_sdk_native("finance") is True
        assert router.is_sdk_native("router") is True
        assert router.is_sdk_native("homelab") is False
        assert router.is_sdk_native("music") is False

    def test_get_sdk_model_returns_string_for_native(self):
        """get_sdk_model returns the model string for SDK-native models."""
        router = self._make_router()
        assert router.get_sdk_model("finance") == "opus"
        assert router.get_sdk_model("router") == "haiku"

    def test_get_sdk_model_returns_none_for_external(self):
        """get_sdk_model returns None for non-Claude models."""
        router = self._make_router()
        assert router.get_sdk_model("homelab") is None
        assert router.get_sdk_model("music") is None

    def test_providers(self):
        """Provider config is loaded from YAML."""
        router = self._make_router()
        assert "ollama" in router.providers
        assert router.providers["ollama"]["api_base"] == "http://localhost:11434"
        assert "openkimi" in router.providers
        assert router.providers["openkimi"]["api_base"] == "https://api.moonshot.cn/v1"

    def test_missing_config_file(self):
        """Missing config file falls back to safe defaults."""
        router = ModelRouter.from_file(Path("/nonexistent/models.yaml"))
        assert router.default_model == "sonnet"
        assert router.get_model("anything") == "sonnet"

    def test_empty_config_file(self):
        """Empty YAML file falls back to constructor defaults."""
        router = self._make_router("")
        assert router.default_model == "sonnet"
        assert router.get_model("anything") == "sonnet"

    def test_malformed_yaml_falls_back(self):
        """Malformed YAML falls back to defaults without crashing."""
        router = self._make_router("{{{{not: yaml: at: all")
        assert router.default_model == "sonnet"

    def test_params_merge_preserves_defaults(self):
        """Agent params merge with defaults, not replace them."""
        config = """\
defaults:
  model: sonnet
  params:
    temperature: 0.7
    max_tokens: 4096

agents:
  finance:
    model: opus
    params:
      temperature: 0.2
"""
        router = self._make_router(config)
        params = router.get_params("finance")
        assert params["temperature"] == 0.2
        assert params["max_tokens"] == 4096

    # --- Skill-specific routing tests ---

    def test_list_skills(self):
        """list_skills returns all configured skill names."""
        router = self._make_router()
        skills = router.list_skills()
        assert "data-transform" in skills
        assert "summarize" in skills
        assert "code-review" in skills

    def test_get_skill_model(self):
        """Skills have their own model assignments."""
        router = self._make_router()
        assert router.get_skill_model("data-transform") == "haiku"
        assert router.get_skill_model("code-review") == "opus"

    def test_get_skill_model_falls_back_to_default(self):
        """Unknown skills fall back to default model."""
        router = self._make_router()
        assert router.get_skill_model("unknown-skill") == "sonnet"

    def test_get_skill_params(self):
        """Skill-specific params override defaults."""
        router = self._make_router()
        params = router.get_skill_params("data-transform")
        assert params["temperature"] == 0.0

    def test_get_skill_params_inherits_default(self):
        """Unknown skills inherit default params."""
        router = self._make_router()
        params = router.get_skill_params("unknown-skill")
        assert params["temperature"] == 0.7

    def test_resolve_model_skill_over_agent(self):
        """resolve_model: skill takes priority over agent."""
        router = self._make_router()
        # finance agent uses opus, but data-transform skill forces haiku
        model = router.resolve_model(agent_name="finance", skill_name="data-transform")
        assert model == "haiku"

    def test_resolve_model_agent_when_no_skill(self):
        """resolve_model: falls back to agent when no skill specified."""
        router = self._make_router()
        model = router.resolve_model(agent_name="finance")
        assert model == "opus"

    def test_resolve_model_default_when_neither(self):
        """resolve_model: falls back to default when neither specified."""
        router = self._make_router()
        model = router.resolve_model()
        assert model == "sonnet"

    def test_resolve_model_unknown_skill_falls_to_agent(self):
        """resolve_model: unknown skill name falls through to agent model."""
        router = self._make_router()
        model = router.resolve_model(agent_name="finance", skill_name="nonexistent")
        assert model == "opus"

    def test_resolve_params_skill_over_agent(self):
        """resolve_params: skill params take priority over agent params."""
        router = self._make_router()
        params = router.resolve_params(agent_name="finance", skill_name="data-transform")
        assert params["temperature"] == 0.0

    def test_no_skills_section_graceful(self):
        """Config without skills section works fine."""
        config = """\
defaults:
  model: sonnet
  params:
    temperature: 0.7

agents:
  router:
    model: haiku
"""
        router = self._make_router(config)
        assert router.list_skills() == []
        assert router.get_skill_model("anything") == "sonnet"
        assert router.resolve_model(agent_name="router", skill_name="anything") == "haiku"

    def test_discovered_models_include_capability_metadata(self):
        """Discovered ModelInfo entries expose runtime capability metadata."""
        router = self._make_router()
        router.discover_models()
        models = router.list_all_models()
        assert len(models) >= 1
        for model in models:
            assert isinstance(model.supports_tools, bool)
            assert isinstance(model.supports_streaming, bool)

    def test_get_model_info_returns_match_or_none(self):
        router = self._make_router()
        router.discover_models()
        models = router.list_all_models()
        if models:
            first = models[0]
            resolved = router.get_model_info(first.id)
            assert resolved is not None
            assert resolved.id == first.id
        assert router.get_model_info("nonexistent-model-id") is None
