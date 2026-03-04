"""Behavioral tests for ModelRouter backend resolution.

Tests exercise the real ModelRouter with real YAML config.
No mocks. Real files, real parsing, real resolution.
"""

from pathlib import Path

import pytest
import yaml

from corvus.model_router import ModelRouter


@pytest.fixture
def config_with_backends(tmp_path: Path) -> Path:
    """Write a real YAML config with backends to a temp file."""
    config = {
        "defaults": {"model": "sonnet", "backend": "claude"},
        "agents": {
            "personal": {"model": "sonnet", "backend": "claude"},
            "homelab": {"model": "sonnet", "backend": "claude"},
            "general": {"model": "sonnet", "backend": "kimi"},
            "music": {"model": "haiku", "backend": "ollama"},
        },
        "backends": {
            "claude": {"type": "sdk_native"},
            "kimi": {
                "type": "proxy",
                "base_url": "http://localhost:8100",
                "env": {"ANTHROPIC_API_KEY": "not-needed"},
            },
            "ollama": {
                "type": "env_swap",
                "env": {
                    "ANTHROPIC_BASE_URL": "http://localhost:11434",
                    "ANTHROPIC_AUTH_TOKEN": "ollama",
                    "ANTHROPIC_API_KEY": "",
                },
            },
        },
    }
    config_file = tmp_path / "models.yaml"
    config_file.write_text(yaml.dump(config))
    return config_file


@pytest.fixture
def router(config_with_backends: Path) -> ModelRouter:
    return ModelRouter.from_file(config_with_backends)


def test_get_backend_returns_configured_backend(router: ModelRouter):
    assert router.get_backend("general") == "kimi"
    assert router.get_backend("music") == "ollama"


def test_get_backend_returns_default_for_unconfigured_agent(router: ModelRouter):
    assert router.get_backend("unknown_agent") == "claude"


def test_get_backend_returns_default_for_claude_agent(router: ModelRouter):
    assert router.get_backend("personal") == "claude"


def test_get_backend_config_returns_full_config(router: ModelRouter):
    cfg = router.get_backend_config("kimi")
    assert cfg["type"] == "proxy"
    assert cfg["base_url"] == "http://localhost:8100"
    assert "env" in cfg


def test_get_backend_config_returns_empty_for_sdk_native(router: ModelRouter):
    cfg = router.get_backend_config("claude")
    assert cfg["type"] == "sdk_native"


def test_get_backend_config_returns_none_for_unknown(router: ModelRouter):
    cfg = router.get_backend_config("nonexistent")
    assert cfg is None


def test_get_backend_env_returns_env_dict(router: ModelRouter):
    env = router.get_backend_env("ollama")
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"


def test_get_backend_env_returns_empty_for_sdk_native(router: ModelRouter):
    env = router.get_backend_env("claude")
    assert env == {}


def test_is_sdk_native_with_backend(router: ModelRouter):
    # Even though model is "sonnet" (sdk-native), backend=kimi means NOT sdk-native
    assert router.is_sdk_native("general") is False
    assert router.is_sdk_native("personal") is True


def test_list_backends(router: ModelRouter):
    backends = router.list_backends()
    assert set(backends) == {"claude", "kimi", "ollama"}
