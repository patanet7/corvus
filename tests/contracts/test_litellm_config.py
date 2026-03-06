"""Behavioral tests for LiteLLM config generation from models.yaml."""

import yaml
import pytest
from pathlib import Path


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
