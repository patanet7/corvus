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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml

logger = structlog.get_logger(__name__)


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
            logger.warning("model_config_not_found", path=str(path))
            return cls(DEFAULT_CONFIG)
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
            if config is None:
                config = {}
            if not isinstance(config, dict):
                raise ValueError(f"Expected YAML mapping in {path}, got {type(config).__name__}")
            logger.info("model_config_loaded", path=str(path))
            return cls(config)
        except Exception:
            if strict:
                raise
            logger.exception("model_config_load_failed", path=str(path))
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

    def get_auth_profile(self, agent_name: str) -> str | None:
        """Return the pinned auth profile for an agent, or None."""
        agent_cfg = self._agents.get(agent_name, {})
        return agent_cfg.get("auth_profile")

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

    def discover_models(self, litellm_base_url: str = "http://127.0.0.1:4000") -> None:
        """Query LiteLLM proxy for available models.

        Falls back to config-based discovery if LiteLLM is unreachable
        (e.g. during tests without a running proxy).
        """
        models: list[ModelInfo] = []

        try:
            resp = httpx.get(f"{litellm_base_url}/models", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                for model_data in data.get("data", []):
                    model_id = model_data.get("id", "")
                    short_name = model_id
                    backend = "litellm"
                    # Match by short name OR full LiteLLM model ID
                    model_map = self._litellm_model_map()
                    if model_id in model_map:
                        # Proxy returned short name (e.g. "haiku")
                        short_name = model_id
                        backend = "claude"
                    else:
                        for name, full_id in model_map.items():
                            if model_id == full_id:
                                short_name = name
                                backend = "claude"
                                break
                    if "ollama" in model_id:
                        backend = "ollama"
                    supports_tools, supports_streaming = self._capabilities_for_backend(backend)
                    models.append(
                        ModelInfo(
                            id=short_name,
                            label=short_name.title() if "/" not in short_name else short_name,
                            backend=backend,
                            available=True,
                            description=f"via LiteLLM — {model_id}",
                            is_default=short_name == self.default_model,
                            supports_tools=supports_tools,
                            supports_streaming=supports_streaming,
                        )
                    )
                self._discovered_models = models
                logger.info("models_discovered_litellm", count=len(models))
                return
        except Exception:
            logger.warning("litellm_proxy_unreachable")

        # Fallback: populate from config (for tests and offline scenarios)
        for model_name in sorted(self._sdk_native_models - {"inherit"}):
            supports_tools, supports_streaming = self._capabilities_for_backend("claude")
            models.append(
                ModelInfo(
                    id=model_name,
                    label=model_name.title(),
                    backend="claude",
                    available=True,
                    description=f"Claude {model_name.title()}",
                    is_default=model_name == self.default_model,
                    supports_tools=supports_tools,
                    supports_streaming=supports_streaming,
                )
            )
        self._discovered_models = models
        logger.info("models_discovered_config", count=len(models))

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

    def get_agent_model_assignments(self) -> list[dict[str, Any]]:
        """Return per-agent model assignments with availability status.

        Used by /api/models endpoint to show role-aware model info.
        """
        assignments: list[dict[str, Any]] = []
        discovered = {
            m.id: m
            for m in (self._discovered_models if hasattr(self, "_discovered_models") else [])
        }

        for agent_name, agent_cfg in self._agents.items():
            model = str(agent_cfg.get("model", self.default_model))
            model_info = discovered.get(model)
            assignments.append({
                "agent": agent_name,
                "model": model,
                "backend": str(agent_cfg.get("backend", self.default_backend)),
                "available": model_info.available if model_info else False,
                "params": {**self.default_params, **agent_cfg.get("params", {})},
            })

        return assignments

    def validate_agent_assignments(self) -> list[str]:
        """Check that all agent-assigned models are available. Return warnings."""
        warnings: list[str] = []
        discovered_ids = {
            m.id for m in (self._discovered_models if hasattr(self, "_discovered_models") else [])
        }

        for agent_name, agent_cfg in self._agents.items():
            model = str(agent_cfg.get("model", self.default_model))
            if discovered_ids and model not in discovered_ids:
                warnings.append(
                    f"Agent '{agent_name}' assigned model '{model}' which is not available"
                )
        return warnings

    def resolve_best_available(self, preferred: str) -> str:
        """Return preferred model if available, else best fallback by capability tier.

        Tier order: opus > sonnet > haiku > first available.
        """
        if not hasattr(self, "_discovered_models"):
            return preferred

        available_ids = {m.id for m in self._discovered_models if m.available}
        if preferred in available_ids:
            return preferred

        # Capability tier fallback
        tier_order = ["opus", "sonnet", "haiku"]
        for tier_model in tier_order:
            if tier_model in available_ids:
                return tier_model

        # Last resort: any available model
        if available_ids:
            return next(iter(available_ids))

        return preferred

    @staticmethod
    def _litellm_model_map() -> dict[str, str]:
        """Short name -> LiteLLM model ID for SDK-native models."""
        return {
            "haiku": "anthropic/claude-haiku-4-5-20251001",
            "sonnet": "anthropic/claude-sonnet-4-20250514",
            "opus": "anthropic/claude-opus-4-20250514",
        }

    @staticmethod
    def _capabilities_for_backend(backend: str) -> tuple[bool, bool]:
        """Return effective runtime capabilities for a backend.

        With LiteLLM routing, tool calling works for Claude and Ollama
        models that support it (llama3, qwen3, mistral, etc.).
        LiteLLM handles the tool-call protocol translation.
        """
        if backend in ("claude", "ollama"):
            return True, True
        return False, True
