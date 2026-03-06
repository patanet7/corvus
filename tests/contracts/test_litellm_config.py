"""Behavioral tests for LiteLLM config generation and role-aware model discovery."""

import yaml
import pytest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from corvus.model_router import ModelRouter


class TestConfigTranslation:
    """Verify models.yaml -> litellm_config.yaml translation."""

    @staticmethod
    def _models_yaml(tmp_path: Path) -> Path:
        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "agents": {
                "finance": {"model": "opus", "params": {"temperature": 0.2}},
                "music": {"model": "haiku", "backend": "ollama"},
                "general": {"model": "sonnet", "backend": "kimi"},
            },
            "backends": {
                "claude": {"type": "sdk_native"},
                "ollama": {
                    "type": "env_swap",
                    "urls": ["http://localhost:11434"],
                    "env": {"ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": ""},
                },
                "kimi": {
                    "type": "proxy",
                    "base_url": "http://localhost:8100",
                    "env": {"ANTHROPIC_API_KEY": "not-needed"},
                },
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        return p

    def test_generates_model_list(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        assert "model_list" in result
        model_names = {m["model_name"] for m in result["model_list"]}
        assert "sonnet" in model_names
        assert "opus" in model_names
        assert "haiku" in model_names

    def test_claude_backend_uses_anthropic_prefix(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        claude_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("model", "").startswith("anthropic/")
        ]
        assert len(claude_models) >= 1

    def test_ollama_backend_uses_ollama_prefix(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        ollama_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("model", "").startswith("ollama/")
            or m["litellm_params"].get("model", "").startswith("ollama_chat/")
        ]
        assert len(ollama_models) >= 1

    def test_kimi_backend_routes_to_kimi_proxy(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        kimi_models = [
            m for m in result["model_list"]
            if m["litellm_params"].get("api_base") == "http://localhost:8100"
        ]
        assert len(kimi_models) >= 1

    def test_router_settings_present(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        assert "router_settings" in result
        rs = result["router_settings"]
        assert rs["num_retries"] >= 1
        assert "fallbacks" in rs or "routing_strategy" in rs

    def test_generates_valid_yaml_file(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        out_path = tmp_path / "litellm_config.yaml"
        out_path.write_text(yaml.dump(result, default_flow_style=False))
        reloaded = yaml.safe_load(out_path.read_text())
        assert reloaded["model_list"] == result["model_list"]

    def test_no_api_keys_in_generated_config(self, tmp_path: Path) -> None:
        """API keys must reference env vars, never contain actual values."""
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        config_str = yaml.dump(result)
        assert "sk-ant-" not in config_str
        assert "sk-" not in config_str.replace("os.environ/", "")

    def test_sdk_native_models_all_present(self, tmp_path: Path) -> None:
        """All three SDK-native models should be in the model list."""
        from corvus.litellm_manager import generate_litellm_config

        result = generate_litellm_config(self._models_yaml(tmp_path))
        model_names = {m["model_name"] for m in result["model_list"]}
        for expected in ("haiku", "sonnet", "opus"):
            assert expected in model_names, f"Missing SDK-native model: {expected}"


class TestLiteLLMManagerLifecycle:
    """Verify LiteLLMManager properties and config generation to disk."""

    def test_base_url_default(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()
        assert mgr.base_url == "http://127.0.0.1:4000"

    def test_base_url_custom_port(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager(port=5555)
        assert mgr.base_url == "http://127.0.0.1:5555"

    def test_is_running_false_before_start(self) -> None:
        from corvus.litellm_manager import LiteLLMManager

        mgr = LiteLLMManager()
        assert mgr.is_running is False

    def test_config_written_to_disk(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        models_yaml = tmp_path / "models.yaml"
        models_yaml.write_text(yaml.dump({
            "defaults": {"model": "sonnet", "backend": "claude"},
            "backends": {"claude": {"type": "sdk_native"}},
        }))

        config = generate_litellm_config(models_yaml)
        out = tmp_path / "litellm_config.yaml"
        out.write_text(yaml.dump(config, default_flow_style=False))
        assert out.exists()
        reloaded = yaml.safe_load(out.read_text())
        assert "model_list" in reloaded


class TestLiteLLMConfigFromYAML:
    """Verify litellm: section in models.yaml is read by generate_litellm_config."""

    def test_litellm_section_overrides_router_settings(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "backends": {"claude": {"type": "sdk_native"}},
            "litellm": {
                "num_retries": 7,
                "cooldown_time": 60,
                "retry_after": 10,
                "routing_strategy": "least-busy",
            },
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        result = generate_litellm_config(p)
        rs = result["router_settings"]
        assert rs["num_retries"] == 7
        assert rs["cooldown_time"] == 60
        assert rs["retry_after"] == 10
        assert rs["routing_strategy"] == "least-busy"

    def test_litellm_section_absent_uses_defaults(self, tmp_path: Path) -> None:
        from corvus.litellm_manager import generate_litellm_config

        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "backends": {"claude": {"type": "sdk_native"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        result = generate_litellm_config(p)
        rs = result["router_settings"]
        assert rs["num_retries"] == 3
        assert rs["cooldown_time"] == 30
        assert rs["routing_strategy"] == "simple-shuffle"


class TestRealModelsYaml:
    """Test config translation against the actual config/models.yaml."""

    def test_real_config_translates(self) -> None:
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        assert len(result["model_list"]) >= 3  # at least haiku/sonnet/opus
        assert "router_settings" in result

    def test_real_config_has_no_secrets(self) -> None:
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        config_str = yaml.dump(result)
        assert "sk-ant-" not in config_str

    def test_real_config_sdk_native_models_present(self) -> None:
        """All three SDK-native models must appear in the translated config."""
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        model_names = {m["model_name"] for m in result["model_list"]}
        for expected in ("haiku", "sonnet", "opus"):
            assert expected in model_names, f"Missing SDK-native model: {expected}"

    def test_real_config_roundtrips_through_yaml(self) -> None:
        """Generated config must survive YAML serialize/deserialize."""
        from corvus.litellm_manager import generate_litellm_config

        real_config = Path("config/models.yaml")
        if not real_config.exists():
            pytest.skip("config/models.yaml not found")
        result = generate_litellm_config(real_config)
        serialized = yaml.dump(result, default_flow_style=False)
        reloaded = yaml.safe_load(serialized)
        assert reloaded["model_list"] == result["model_list"]
        assert reloaded["router_settings"] == result["router_settings"]


class TestRoleAwareDiscovery:
    """Verify agent-model assignment tracking and validation."""

    @staticmethod
    def _router_with_agents(tmp_path: Path) -> "ModelRouter":
        from corvus.model_router import ModelRouter

        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "agents": {
                "finance": {"model": "opus", "params": {"temperature": 0.2}},
                "router": {"model": "haiku"},
                "music": {"model": "haiku", "backend": "ollama"},
            },
            "backends": {"claude": {"type": "sdk_native"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        return ModelRouter.from_file(p)

    def test_agent_assignments_returns_all_agents(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        assignments = router.get_agent_model_assignments()
        agent_names = {a["agent"] for a in assignments}
        assert "finance" in agent_names
        assert "router" in agent_names
        assert "music" in agent_names

    def test_agent_assignments_include_model_and_backend(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        assignments = router.get_agent_model_assignments()
        finance = next(a for a in assignments if a["agent"] == "finance")
        assert finance["model"] == "opus"
        assert finance["backend"] == "claude"

    def test_agent_assignments_include_params(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        assignments = router.get_agent_model_assignments()
        finance = next(a for a in assignments if a["agent"] == "finance")
        assert finance["params"]["temperature"] == 0.2

    def test_agent_assignments_availability_true_for_discovered(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        assignments = router.get_agent_model_assignments()
        finance = next(a for a in assignments if a["agent"] == "finance")
        # opus is in config fallback discovery
        assert finance["available"] is True

    def test_validate_warns_on_missing_model(self, tmp_path: Path) -> None:
        from corvus.model_router import ModelRouter

        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "agents": {"test_agent": {"model": "nonexistent-model"}},
            "backends": {"claude": {"type": "sdk_native"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        router = ModelRouter.from_file(p)
        router.discover_models()  # config fallback -- only haiku/opus/sonnet
        warnings = router.validate_agent_assignments()
        assert any("nonexistent-model" in w for w in warnings)

    def test_validate_no_warnings_when_all_available(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        warnings = router.validate_agent_assignments()
        assert len(warnings) == 0

    def test_resolve_best_available_returns_preferred_when_available(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        assert router.resolve_best_available("sonnet") == "sonnet"

    def test_resolve_best_available_falls_back_on_unavailable(self, tmp_path: Path) -> None:
        router = self._router_with_agents(tmp_path)
        router.discover_models()
        result = router.resolve_best_available("nonexistent")
        assert result in ("opus", "sonnet", "haiku")  # falls back to tier

    def test_resolve_best_available_without_discovery(self, tmp_path: Path) -> None:
        """Before discover_models(), resolve_best_available returns preferred as-is."""
        from corvus.model_router import ModelRouter

        config = {
            "defaults": {"model": "sonnet", "backend": "claude"},
            "agents": {},
            "backends": {"claude": {"type": "sdk_native"}},
        }
        p = tmp_path / "models.yaml"
        p.write_text(yaml.dump(config))
        router = ModelRouter.from_file(p)
        # No discover_models() call
        assert router.resolve_best_available("anything") == "anything"
