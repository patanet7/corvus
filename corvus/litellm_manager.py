"""LiteLLM proxy manager — config generation and subprocess lifecycle.

Generates litellm_config.yaml from config/models.yaml at startup.
Manages LiteLLM proxy as a subprocess on 127.0.0.1:4000.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger("corvus-gateway.litellm")

# SDK-native model names -> LiteLLM model identifiers
_SDK_MODEL_MAP: dict[str, str] = {
    "haiku": "anthropic/claude-haiku-4-5-20251001",
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "opus": "anthropic/claude-opus-4-20250514",
}

_DEFAULT_PORT = 4000
_DEFAULT_HOST = "127.0.0.1"
_HEALTH_TIMEOUT = 30.0
_HEALTH_POLL_INTERVAL = 0.5


def generate_litellm_config(models_yaml_path: Path) -> dict[str, Any]:
    """Translate config/models.yaml into a LiteLLM config dict.

    Args:
        models_yaml_path: Path to the models.yaml configuration file.

    Returns:
        Dictionary suitable for writing as litellm_config.yaml. API keys are
        referenced via ``os.environ/VAR_NAME`` — never inlined.
    """
    with open(models_yaml_path) as f:
        config = yaml.safe_load(f) or {}

    backends = config.get("backends", {})
    model_list: list[dict[str, Any]] = []
    seen_models: set[str] = set()

    # 1. SDK-native Claude models
    for short_name, litellm_model in _SDK_MODEL_MAP.items():
        if short_name not in seen_models:
            model_list.append({
                "model_name": short_name,
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": "os.environ/ANTHROPIC_API_KEY",
                },
            })
            seen_models.add(short_name)

    # 2. Ollama models from config
    ollama_cfg = backends.get("ollama", {})
    if ollama_cfg.get("type") == "env_swap":
        urls = ollama_cfg.get("urls", [])
        api_base = urls[0] if urls else "http://localhost:11434"
        # Resolve env var references like ${OLLAMA_API_BASE:-default}
        if api_base.startswith("${") and ":-" in api_base:
            env_var = api_base.split(":-")[0].lstrip("${")
            default = api_base.split(":-")[1].rstrip("}")
            api_base = os.environ.get(env_var, default)

        # Add a generic ollama entry; LiteLLM discovers models dynamically
        model_list.append({
            "model_name": "ollama/*",
            "litellm_params": {
                "model": "ollama/*",
                "api_base": api_base,
            },
        })

    # 3. Kimi via KimiProxy
    kimi_cfg = backends.get("kimi", {})
    if kimi_cfg.get("type") == "proxy":
        base_url = kimi_cfg.get("base_url", "http://localhost:8100")
        model_list.append({
            "model_name": "kimi",
            "litellm_params": {
                "model": "openai/kimi-k2",
                "api_base": base_url,
                "api_key": "not-needed",
            },
        })

    # 4. OpenAI
    openai_cfg = backends.get("openai", {})
    if openai_cfg:
        model_list.append({
            "model_name": "openai/gpt-4o",
            "litellm_params": {
                "model": "openai/gpt-4o",
                "api_key": "os.environ/OPENAI_API_KEY",
            },
        })

    # 5. OpenAI-compatible
    compat_cfg = backends.get("openai_compat", {})
    if compat_cfg:
        model_list.append({
            "model_name": "openai-compat",
            "litellm_params": {
                "model": "openai/custom",
                "api_base": "os.environ/OPENAI_COMPAT_BASE_URL",
                "api_key": "os.environ/OPENAI_COMPAT_API_KEY",
            },
        })

    # Router settings — read from litellm: section with hardcoded fallbacks
    litellm_cfg = config.get("litellm", {})
    router_settings: dict[str, Any] = {
        "routing_strategy": litellm_cfg.get("routing_strategy", "simple-shuffle"),
        "num_retries": litellm_cfg.get("num_retries", 3),
        "allowed_fails": litellm_cfg.get("allowed_fails", 3),
        "cooldown_time": litellm_cfg.get("cooldown_time", 30),
        "retry_after": litellm_cfg.get("retry_after", 5),
    }

    # Build fallback chains from config
    fallbacks: list[dict[str, list[str]]] = []
    if "ollama/*" in {m["model_name"] for m in model_list}:
        for sdk_model in _SDK_MODEL_MAP:
            fallbacks.append({sdk_model: ["ollama/*"]})
    if fallbacks:
        router_settings["fallbacks"] = fallbacks

    return {
        "model_list": model_list,
        "router_settings": router_settings,
    }


class LiteLLMManager:
    """Manages LiteLLM proxy subprocess lifecycle.

    Generates a litellm_config.yaml from the project's models.yaml, starts
    the LiteLLM proxy as a subprocess, polls for health, and sets
    ANTHROPIC_BASE_URL so the claude-agent-sdk routes through the proxy.
    """

    def __init__(
        self,
        port: int = _DEFAULT_PORT,
        host: str = _DEFAULT_HOST,
    ) -> None:
        self._port = port
        self._host = host
        self._process: subprocess.Popen[bytes] | None = None
        self._config_path: Path | None = None

    @property
    def base_url(self) -> str:
        """Return the base URL for the running LiteLLM proxy."""
        return f"http://{self._host}:{self._port}"

    async def start(self, models_yaml: Path, output_dir: Path | None = None) -> None:
        """Generate config, start proxy, wait for health check.

        Args:
            models_yaml: Path to config/models.yaml.
            output_dir: Directory for generated litellm_config.yaml.
                        Defaults to same directory as models_yaml.
        """
        config = generate_litellm_config(models_yaml)
        out_dir = output_dir or models_yaml.parent
        self._config_path = out_dir / "litellm_config.yaml"
        self._config_path.write_text(
            yaml.dump(config, default_flow_style=False)
        )
        logger.info("Generated LiteLLM config at %s", self._config_path)

        self._process = subprocess.Popen(
            [
                "litellm",
                "--config", str(self._config_path),
                "--host", self._host,
                "--port", str(self._port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(
            "LiteLLM proxy starting on %s:%d (pid=%d)",
            self._host, self._port, self._process.pid,
        )

        await self._wait_healthy()
        os.environ["ANTHROPIC_BASE_URL"] = self.base_url
        logger.info("ANTHROPIC_BASE_URL set to %s", self.base_url)

    async def _wait_healthy(self) -> None:
        """Poll /health until LiteLLM is ready."""
        deadline = time.monotonic() + _HEALTH_TIMEOUT
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{self.base_url}/health", timeout=2.0)
                if resp.status_code == 200:
                    logger.info("LiteLLM proxy is healthy")
                    return
            except httpx.ConnectError:
                pass
            # Check if process died
            if self._process and self._process.poll() is not None:
                stderr = (
                    self._process.stderr.read().decode()
                    if self._process.stderr
                    else ""
                )
                raise RuntimeError(
                    f"LiteLLM proxy exited with code "
                    f"{self._process.returncode}: {stderr[:500]}"
                )
            await asyncio.sleep(_HEALTH_POLL_INTERVAL)
        raise TimeoutError(
            f"LiteLLM proxy did not become healthy within {_HEALTH_TIMEOUT}s"
        )

    async def stop(self) -> None:
        """Gracefully shut down the proxy subprocess."""
        if self._process is None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=10)
            logger.info("LiteLLM proxy stopped (pid=%d)", self._process.pid)
        except subprocess.TimeoutExpired:
            self._process.kill()
            logger.warning("LiteLLM proxy killed (pid=%d)", self._process.pid)
        finally:
            self._process = None

    @property
    def is_running(self) -> bool:
        """Return True if the proxy subprocess is alive."""
        return self._process is not None and self._process.poll() is None
