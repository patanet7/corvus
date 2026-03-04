"""SDKClientPool — manages Claude SDK client instances per backend.

Each backend (claude, kimi, ollama) gets its own set of env overrides.
For proxy backends (kimi), the ANTHROPIC_BASE_URL is set to the proxy URL.
For env-swap backends (ollama), the URL is resolved via probe with fallback.
For sdk-native backends (claude), no env changes needed.
"""

from __future__ import annotations

import logging
import os

from corvus.model_router import ModelRouter
from corvus.ollama_probe import resolve_ollama_url

logger = logging.getLogger("corvus-gateway.client-pool")


class SDKClientPool:
    """Resolves backend config for agents. Manages env overrides per backend.

    Does NOT manage SDK client lifecycle directly — that's handled by
    server.py which creates ClaudeSDKClient instances with the right env.
    """

    # Backend availability checks: env var that must be set for each backend type
    _BACKEND_ENV_CHECKS: dict[str, str] = {
        "claude": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "kimi": "KIMI_BOT_TOKEN",
        "openai_compat": "OPENAI_COMPAT_BASE_URL",
    }

    def __init__(self, model_router: ModelRouter) -> None:
        self._router = model_router

    def _backend_available(self, backend_name: str) -> bool:
        """Check if a backend has the required credentials/connectivity."""
        # Ollama: check via probe (env_swap type)
        cfg = self._router.get_backend_config(backend_name)
        if cfg and cfg.get("type") == "env_swap":
            candidate_urls = cfg.get("urls", [])
            if candidate_urls:
                resolved = resolve_ollama_url(candidate_urls)
                return resolved is not None
            return bool(os.environ.get("OLLAMA_BASE_URL"))
        # Others: check for required env var
        env_key = self._BACKEND_ENV_CHECKS.get(backend_name)
        if env_key:
            return bool(os.environ.get(env_key))
        # Unknown backend — assume available
        return True

    def resolve_backend(self, agent_name: str) -> str:
        """Return the backend name for an agent, with fallback if unavailable."""
        preferred = self._router.get_backend(agent_name)
        if self._backend_available(preferred):
            return preferred
        # Fallback: try other configured backends in priority order
        fallback_order = ["ollama", "openai", "openai_compat", "kimi", "claude"]
        for candidate in fallback_order:
            if candidate != preferred and self._backend_available(candidate):
                logger.info(
                    "Backend '%s' unavailable for agent '%s', falling back to '%s'",
                    preferred,
                    agent_name,
                    candidate,
                )
                return candidate
        logger.warning(
            "No available backend for agent '%s' (preferred: %s) — using '%s' anyway",
            agent_name,
            preferred,
            preferred,
        )
        return preferred

    def build_env(self, backend_name: str) -> dict[str, str]:
        """Build environment variable overrides for a backend.

        For proxy backends: sets ANTHROPIC_BASE_URL to the proxy URL.
        For env-swap backends with ``urls`` list: probes candidates in order,
            uses the first reachable URL (cached 5 min).
        For sdk-native backends: returns empty dict (no overrides).
        """
        cfg = self._router.get_backend_config(backend_name)
        if cfg is None:
            if backend_name != "claude":
                logger.warning("Unknown backend '%s' — returning empty env overrides", backend_name)
            return {}

        backend_type = cfg.get("type", "sdk_native")
        env = dict(cfg.get("env", {}))

        if backend_type == "proxy":
            base_url = cfg.get("base_url", "")
            if base_url:
                env["ANTHROPIC_BASE_URL"] = base_url

        if backend_type == "env_swap":
            # Resolve URL from candidate list with fallback
            candidate_urls = cfg.get("urls", [])
            if candidate_urls:
                resolved = resolve_ollama_url(candidate_urls)
                if resolved:
                    env["ANTHROPIC_BASE_URL"] = resolved
                else:
                    # All candidates down — use first as hopeful default
                    env["ANTHROPIC_BASE_URL"] = candidate_urls[0]
                    logger.warning(
                        "No reachable Ollama URL, falling back to %s",
                        candidate_urls[0],
                    )
            # Legacy: single ANTHROPIC_BASE_URL in env dict (already in env)
            # or override from environment variable
            base_url_key = cfg.get("base_url_env", "")
            if base_url_key:
                override = os.environ.get(base_url_key)
                if override:
                    env["ANTHROPIC_BASE_URL"] = override

        return env

    def get_base_url(self, backend_name: str) -> str | None:
        """Return the base URL for a proxy backend, or None for others."""
        cfg = self._router.get_backend_config(backend_name)
        if cfg is None:
            return None
        if cfg.get("type") == "proxy":
            return cfg.get("base_url")
        return None
