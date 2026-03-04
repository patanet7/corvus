"""Behavioral tests for model routing fallback chains.

Exercises the real ModelRouter with in-memory configs and the real
config/models.yaml file.  No mocks, no patches -- real dict configs,
real YAML parsing, real file I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from corvus.model_router import ModelRouter

# Path to the real production config
REAL_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


class TestFallbackChain:
    """Verify fallback chain resolution for model routing."""

    def test_fallback_chain_returns_correct_models(self):
        """Agent with fallbacks returns them in declared order."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet", "haiku"]},
                },
            }
        )
        fallbacks = router.get_fallbacks("homelab")
        assert fallbacks == ["sonnet", "haiku"]

    def test_single_fallback(self):
        """Agent with a single fallback returns a one-element list."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet"]},
                },
            }
        )
        fallbacks = router.get_fallbacks("homelab")
        assert fallbacks == ["sonnet"]
        assert len(fallbacks) == 1

    def test_primary_model_resolves_for_agent(self):
        """Primary model for an agent resolves correctly via get_model."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet"]},
                },
            }
        )
        model = router.get_model("homelab")
        assert model == "kimi-k2"

    def test_primary_model_resolves_via_resolve_model(self):
        """Primary model for an agent resolves correctly via resolve_model."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet"]},
                },
            }
        )
        model = router.resolve_model(agent_name="homelab")
        assert model == "kimi-k2"

    def test_fallbacks_are_ordered(self):
        """Fallbacks preserve insertion order from config."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {
                        "model": "kimi-k2",
                        "fallbacks": ["opus", "sonnet", "haiku"],
                    },
                },
            }
        )
        fallbacks = router.get_fallbacks("homelab")
        assert fallbacks == ["opus", "sonnet", "haiku"]
        # First fallback is the highest-priority alternative
        assert fallbacks[0] == "opus"
        # Last fallback is the lowest-priority alternative
        assert fallbacks[-1] == "haiku"

    def test_agent_without_fallbacks_returns_empty(self):
        """Agent configured without fallbacks returns empty list."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "music": {"model": "haiku"},
                },
            }
        )
        fallbacks = router.get_fallbacks("music")
        assert fallbacks == []

    def test_unconfigured_agent_fallbacks_returns_empty(self):
        """Agent not present in config at all returns empty fallback list."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {},
            }
        )
        fallbacks = router.get_fallbacks("unknown-agent")
        assert fallbacks == []

    def test_unconfigured_agent_uses_default_model(self):
        """Agent not in config uses the default model."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {},
            }
        )
        model = router.get_model("unknown-agent")
        assert model == "sonnet"

    def test_sdk_native_for_claude_model(self):
        """Claude models (haiku/sonnet/opus) are SDK-native when using default backend."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet", "backend": "claude"},
                "agents": {
                    "personal": {"model": "sonnet"},
                    "router": {"model": "haiku"},
                    "finance": {"model": "opus"},
                },
                "backends": {
                    "claude": {"type": "sdk_native"},
                },
            }
        )
        assert router.is_sdk_native("personal") is True
        assert router.is_sdk_native("router") is True
        assert router.is_sdk_native("finance") is True

    def test_not_sdk_native_for_external_model(self):
        """Non-Claude models are not SDK-native."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet", "backend": "claude"},
                "agents": {
                    "homelab": {"model": "kimi-k2"},
                },
            }
        )
        assert router.is_sdk_native("homelab") is False

    def test_not_sdk_native_when_backend_is_not_claude(self):
        """Even a Claude model name is not SDK-native when backend is non-claude."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet", "backend": "claude"},
                "agents": {
                    "general": {"model": "sonnet", "backend": "kimi"},
                },
                "backends": {
                    "claude": {"type": "sdk_native"},
                    "kimi": {"type": "proxy", "base_url": "http://localhost:8100"},
                },
            }
        )
        assert router.is_sdk_native("general") is False

    def test_fallback_primary_model_not_in_fallback_list(self):
        """The primary model should not appear in the fallback list (convention check)."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet", "haiku"]},
                },
            }
        )
        primary = router.get_model("homelab")
        fallbacks = router.get_fallbacks("homelab")
        assert primary not in fallbacks

    def test_full_chain_primary_plus_fallbacks(self):
        """Primary + fallbacks form the complete model resolution chain."""
        router = ModelRouter(
            {
                "defaults": {"model": "sonnet"},
                "agents": {
                    "homelab": {"model": "kimi-k2", "fallbacks": ["sonnet", "haiku"]},
                },
            }
        )
        primary = router.get_model("homelab")
        fallbacks = router.get_fallbacks("homelab")
        full_chain = [primary] + fallbacks
        assert full_chain == ["kimi-k2", "sonnet", "haiku"]
        assert len(full_chain) == 3


class TestFallbackChainFromRealConfig:
    """Verify fallback chain behavior against the real config/models.yaml."""

    @pytest.fixture(autouse=True)
    def _load_real_config(self):
        """Load the real config file and make it available."""
        assert REAL_CONFIG_PATH.exists(), f"Real config not found at {REAL_CONFIG_PATH}"
        self.router = ModelRouter.from_file(REAL_CONFIG_PATH)
        with open(REAL_CONFIG_PATH) as f:
            self.raw_config = yaml.safe_load(f)

    def test_real_config_parses_without_error(self):
        """The production config/models.yaml parses and creates a valid router."""
        assert self.router.default_model == "sonnet"

    def test_real_config_default_model(self):
        """Default model in production config is sonnet."""
        assert self.router.default_model == "sonnet"

    def test_real_config_agents_resolve(self):
        """All agents listed in production config resolve to their assigned models."""
        for agent_name, agent_cfg in self.raw_config.get("agents", {}).items():
            expected_model = agent_cfg.get("model", "sonnet")
            actual_model = self.router.get_model(agent_name)
            assert actual_model == expected_model, (
                f"Agent {agent_name!r}: expected {expected_model!r}, got {actual_model!r}"
            )

    def test_real_config_unconfigured_agent_uses_default(self):
        """An agent not in the real config falls back to default."""
        model = self.router.get_model("nonexistent-agent-xyz")
        assert model == "sonnet"

    def test_real_config_fallbacks_match_yaml(self):
        """Any fallbacks declared in real config are returned correctly."""
        for agent_name, agent_cfg in self.raw_config.get("agents", {}).items():
            expected_fallbacks = agent_cfg.get("fallbacks", [])
            actual_fallbacks = self.router.get_fallbacks(agent_name)
            assert actual_fallbacks == expected_fallbacks, (
                f"Agent {agent_name!r}: expected fallbacks {expected_fallbacks!r}, got {actual_fallbacks!r}"
            )

    def test_real_config_skills_resolve(self):
        """All skills in the real config resolve to their assigned models."""
        for skill_name, skill_cfg in self.raw_config.get("skills", {}).items():
            expected_model = skill_cfg.get("model", "sonnet")
            actual_model = self.router.get_skill_model(skill_name)
            assert actual_model == expected_model, (
                f"Skill {skill_name!r}: expected {expected_model!r}, got {actual_model!r}"
            )

    def test_real_config_backends_loaded(self):
        """Backend definitions from the real config are loaded."""
        backends = self.router.list_backends()
        # The real config has claude, kimi, ollama backends
        assert "claude" in backends
