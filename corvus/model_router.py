"""Model routing -- per-agent and per-skill model assignment with provider abstraction.

Reads config/models.yaml to determine which model each agent or skill uses.
SDK-native models (haiku, sonnet, opus) are passed directly to AgentDefinition.
Non-Claude models (ollama/*, kimi-*) route through provider adapters.

Skills are reusable task types (e.g., data-transform, summarize) that any agent
can invoke.  Each skill can specify its own model + params, independent of the
calling agent.  Resolution order: skill override > agent override > default.

Adding a new provider: add to providers: section in config/models.yaml + set env var.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from corvus.ollama_probe import probe_ollama_models, resolve_ollama_url

logger = logging.getLogger("corvus-gateway.model_router")


@dataclass
class ModelInfo:
    """Model info for frontend display and availability tracking."""

    id: str
    label: str
    backend: str  # "claude", "ollama", "openai", etc.
    available: bool = True
    description: str = ""
    is_default: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "backend": self.backend,
            "available": self.available,
            "description": self.description,
            "isDefault": self.is_default,
            "capabilities": {
                "supports_tools": self.supports_tools,
                "supports_streaming": self.supports_streaming,
            },
        }


_DEFAULT_SDK_NATIVE = {"haiku", "sonnet", "opus", "inherit"}

_DEFAULT_COMPLEXITY_MAP: dict[str, str] = {
    "high": "opus",
    "medium": "sonnet",
    "low": "haiku",
}


@dataclass
class ModelRouterConfig:
    """Typed config for ModelRouter. Constructed from YAML or used as defaults."""

    defaults: dict[str, Any] = field(default_factory=lambda: {"model": "sonnet", "params": {"temperature": 0.7}})
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    backends: dict[str, dict[str, Any]] = field(default_factory=dict)
    context_limits: dict[str, int] = field(default_factory=dict)
    sdk_native_models: list[str] = field(default_factory=lambda: list(_DEFAULT_SDK_NATIVE))
    complexity_defaults: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_COMPLEXITY_MAP))

    def to_dict(self) -> dict[str, Any]:
        """Convert to plain dict for ModelRouter.__init__."""
        from dataclasses import asdict

        return asdict(self)


DEFAULT_CONFIG: dict[str, Any] = ModelRouterConfig().to_dict()


class ModelRouter:
    """Resolves per-agent model assignments from YAML config.

    Usage::

        router = ModelRouter.from_file(Path("config/models.yaml"))
        model = router.get_model("finance")      # "opus"
        params = router.get_params("finance")     # {"temperature": 0.2}
        native = router.is_sdk_native("finance")  # True
    """

    def __init__(self, config: dict[str, Any]) -> None:
        defaults = config.get("defaults", {})
        self.default_model: str = defaults.get("model", "sonnet")
        self.default_params: dict[str, Any] = defaults.get("params", {})
        self.default_backend: str = defaults.get("backend", "claude")
        self.default_context_limit: int = defaults.get("context_limit", 200000)
        self._agents: dict[str, dict[str, Any]] = config.get("agents", {})
        self._skills: dict[str, dict[str, Any]] = config.get("skills", {})
        self.providers: dict[str, dict[str, Any]] = config.get("providers", {})
        self._backends: dict[str, dict[str, Any]] = config.get("backends", {})
        self._context_limits: dict[str, int] = config.get("context_limits", {})
        # Config-driven: which model strings the SDK accepts natively
        raw_native = config.get("sdk_native_models")
        self._sdk_native_models: set[str] = set(raw_native) if raw_native else set(_DEFAULT_SDK_NATIVE)
        # Config-driven: complexity → model mapping
        raw_complexity = config.get("complexity_defaults")
        self._complexity_defaults: dict[str, str] = (
            dict(raw_complexity) if raw_complexity else dict(_DEFAULT_COMPLEXITY_MAP)
        )

    @classmethod
    def from_file(cls, path: Path, *, strict: bool = False) -> ModelRouter:
        """Load model config from a YAML file.

        Args:
            path: Path to the YAML config file.
            strict: If True, raise on parse failure instead of falling back
                to defaults. Use strict=True in production to fail fast.
        """
        if not path.exists():
            if strict:
                raise FileNotFoundError(f"Model config not found at {path}")
            logger.warning("Model config not found at %s, using defaults", path)
            return cls(DEFAULT_CONFIG)
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            if config is None:
                config = {}
            if not isinstance(config, dict):
                raise ValueError(f"Expected YAML mapping in {path}, got {type(config).__name__}")
            logger.info("Loaded model config from %s", path)
            return cls(config)
        except Exception:
            if strict:
                raise
            logger.exception("Failed to load model config from %s, using defaults", path)
            return cls(DEFAULT_CONFIG)

    def get_model(self, agent_name: str) -> str:
        """Return the model string for an agent (or the default)."""
        agent_cfg = self._agents.get(agent_name, {})
        return str(agent_cfg.get("model", self.default_model))

    def get_params(self, agent_name: str) -> dict[str, Any]:
        """Return merged params (default + agent-specific overrides)."""
        agent_cfg = self._agents.get(agent_name, {})
        params = dict(self.default_params)
        params.update(agent_cfg.get("params", {}))
        return params

    def get_fallbacks(self, agent_name: str) -> list[str]:
        """Return fallback model chain for an agent (empty for SDK-native)."""
        agent_cfg = self._agents.get(agent_name, {})
        return list(agent_cfg.get("fallbacks", []))

    # --- Backend resolution ---

    def get_backend(self, agent_name: str) -> str:
        """Return the backend name for an agent (or the default)."""
        agent_cfg = self._agents.get(agent_name, {})
        return str(agent_cfg.get("backend", self.default_backend))

    def get_backend_config(self, backend_name: str) -> dict[str, Any] | None:
        """Return full config dict for a backend, or None if unknown."""
        return self._backends.get(backend_name)

    def get_backend_env(self, backend_name: str) -> dict[str, Any]:
        """Return env var overrides for a backend (empty dict for sdk-native)."""
        cfg = self._backends.get(backend_name, {})
        return dict(cfg.get("env", {}))

    def list_backends(self) -> list[str]:
        """Return all configured backend names."""
        return list(self._backends.keys())

    def get_context_limit(self, model_name: str) -> int:
        """Return context window size for a model (falls back to default)."""
        return self._context_limits.get(model_name, self.default_context_limit)

    def is_sdk_native(self, agent_name: str) -> bool:
        """Check if the agent uses an SDK-native backend (direct Claude API)."""
        backend = self.get_backend(agent_name)
        if backend != "claude" and backend in self._backends:
            return False
        model = self.get_model(agent_name)
        return model in self._sdk_native_models

    def get_sdk_model(self, agent_name: str) -> str | None:
        """Return the model string if SDK-native, else None."""
        model = self.get_model(agent_name)
        if model in self._sdk_native_models:
            return model
        return None

    def resolve_for_complexity(self, complexity: str) -> str:
        """Map a complexity level to a model name via config.

        Falls back to the default model if the complexity is not in the mapping.
        """
        return self._complexity_defaults.get(complexity, self.default_model)

    def resolve_sdk_model_for_agent(
        self,
        agent_name: str,
        complexity: str | None = None,
    ) -> str | None:
        """Resolve the SDK model for an agent, with complexity fallback.

        Resolution order: agent model override > complexity mapping > default.
        Returns None for non-SDK-native models (handled by env_swap).
        """
        model = self.get_model(agent_name)
        # If model is just the default and complexity is provided, use
        # the complexity mapping for a more specific default.
        if model == self.default_model and complexity:
            model = self._complexity_defaults.get(complexity, model)
        if model in self._sdk_native_models:
            return model
        return None

    # --- Skill-specific routing ---

    def list_skills(self) -> list[str]:
        """Return all configured skill names."""
        return list(self._skills.keys())

    def get_skill_model(self, skill_name: str) -> str:
        """Return the model for a skill (falls back to default)."""
        skill_cfg = self._skills.get(skill_name, {})
        return str(skill_cfg.get("model", self.default_model))

    def get_skill_params(self, skill_name: str) -> dict[str, Any]:
        """Return merged params for a skill (default + skill-specific)."""
        skill_cfg = self._skills.get(skill_name, {})
        params = dict(self.default_params)
        params.update(skill_cfg.get("params", {}))
        return params

    def resolve_model(self, agent_name: str | None = None, skill_name: str | None = None) -> str:
        """Resolve model with priority: skill > agent > default.

        When a skill is invoked by an agent, the skill's model takes precedence.
        This lets reusable skills (e.g., data-transform) always use their
        preferred model regardless of which agent dispatches them.
        """
        if skill_name and skill_name in self._skills:
            return self.get_skill_model(skill_name)
        if agent_name:
            return self.get_model(agent_name)
        return self.default_model

    def resolve_params(self, agent_name: str | None = None, skill_name: str | None = None) -> dict[str, Any]:
        """Resolve params with priority: skill > agent > default."""
        if skill_name and skill_name in self._skills:
            return self.get_skill_params(skill_name)
        if agent_name:
            return self.get_params(agent_name)
        return dict(self.default_params)

    # --- Dynamic model discovery ---

    def discover_models(self) -> None:
        """Probe all configured backends and populate available models.

        Call this at startup and periodically to refresh.  Results are
        cached in ``self._discovered_models``.
        """
        models: list[ModelInfo] = []

        # 1. SDK-native models (Claude) — available if ANTHROPIC_API_KEY is set
        claude_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
        for model_name in sorted(self._sdk_native_models - {"inherit"}):
            supports_tools, supports_streaming = self._capabilities_for_backend("claude")
            models.append(
                ModelInfo(
                    id=model_name,
                    label=model_name.title(),
                    backend="claude",
                    available=claude_available,
                    description=f"Claude {model_name.title()}",
                    is_default=model_name == self.default_model,
                    supports_tools=supports_tools,
                    supports_streaming=supports_streaming,
                )
            )

        # 2. Ollama models — probe configured URLs
        ollama_cfg = self._backends.get("ollama", {})
        if ollama_cfg.get("type") == "env_swap":
            candidate_urls = ollama_cfg.get("urls", [])
            if not candidate_urls:
                env_url = os.environ.get("OLLAMA_BASE_URL")
                if env_url:
                    candidate_urls = [env_url]
            resolved = resolve_ollama_url(candidate_urls) if candidate_urls else None
            if resolved:
                supports_tools, supports_streaming = self._capabilities_for_backend("ollama")
                for name in probe_ollama_models(resolved):
                    if not self._is_chat_ollama_model(name):
                        continue
                    models.append(
                        ModelInfo(
                            id=f"ollama/{name}",
                            label=name,
                            backend="ollama",
                            available=True,
                            description=f"Ollama — {resolved}",
                            supports_tools=supports_tools,
                            supports_streaming=supports_streaming,
                        )
                    )

        # 3. OpenAI — available if key is set
        if "openai" in self._backends and os.environ.get("OPENAI_API_KEY"):
            supports_tools, supports_streaming = self._capabilities_for_backend("openai")
            models.append(
                ModelInfo(
                    id="openai/gpt-4o",
                    label="GPT-4o",
                    backend="openai",
                    available=True,
                    description="OpenAI GPT-4o",
                    supports_tools=supports_tools,
                    supports_streaming=supports_streaming,
                )
            )

        self._discovered_models = models
        logger.info(
            "Discovered %d models (%d available)",
            len(models),
            sum(1 for m in models if m.available),
        )

    def list_available_models(self) -> list[ModelInfo]:
        """Return all discovered models. Call discover_models() first."""
        if not hasattr(self, "_discovered_models"):
            self.discover_models()
        return [m for m in self._discovered_models if m.available]

    def list_all_models(self) -> list[ModelInfo]:
        """Return all models including unavailable ones."""
        if not hasattr(self, "_discovered_models"):
            self.discover_models()
        return list(self._discovered_models)

    def get_model_info(self, model_id: str) -> ModelInfo | None:
        """Return discovered model metadata by frontend model id."""
        if not hasattr(self, "_discovered_models"):
            self.discover_models()
        for model in self._discovered_models:
            if model.id == model_id:
                return model
        return None

    @staticmethod
    def _is_chat_ollama_model(name: str) -> bool:
        """Heuristic filter for chat-capable Ollama models in UI selection."""
        lowered = name.lower()
        # Hide known embedding-only models from chat model selector.
        return "embed" not in lowered

    @staticmethod
    def _capabilities_for_backend(backend: str) -> tuple[bool, bool]:
        """Return effective runtime capabilities for a backend."""
        # Current runtime wiring only enables tools/hooks on Claude.
        if backend == "claude":
            return True, True
        return False, True
