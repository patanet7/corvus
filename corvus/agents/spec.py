"""AgentSpec dataclasses — config-driven agent definitions.

Four dataclasses define the shape of an agent specification:
- AgentModelConfig: LLM model preferences and routing hints
- AgentToolConfig: allowed tools, MCP modules, gated confirmations
- AgentMemoryConfig: domain isolation and cross-domain read policies
- AgentSpec: the top-level specification combining all of the above

All classes are plain dataclasses (not pydantic) and support:
- Construction with sensible defaults
- Serialization via to_dict() / from_dict()
- YAML loading via from_yaml()
"""

import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

logger = logging.getLogger("corvus-gateway")


def _filter_known_fields(cls: type, data: dict) -> dict:
    """Filter dict to only keys that match dataclass field names.

    Logs a warning for unknown keys so YAML typos surface in logs
    instead of crashing with a cryptic TypeError.
    """
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        logger.warning("Ignoring unknown %s fields: %s", cls.__name__, sorted(unknown))
    return {k: v for k, v in data.items() if k in known}


@dataclass
class AgentModelConfig:
    """LLM model preferences and routing configuration for an agent."""

    preferred: str | None = None
    fallback: str | None = None
    auto: bool = True
    complexity: str = "medium"  # "high" | "medium" | "low"

    def __post_init__(self):
        valid = {"high", "medium", "low"}
        if self.complexity not in valid:
            raise ValueError(f"complexity must be one of {sorted(valid)}, got {self.complexity!r}")


@dataclass
class AgentToolConfig:
    """Allowed tools and MCP module bindings for an agent."""

    builtin: list[str] = field(default_factory=list)
    modules: dict[str, dict] = field(default_factory=dict)
    confirm_gated: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
    permission_tier: str = "default"  # "strict" | "default" | "break_glass"
    extra_deny: list[str] = field(default_factory=list)

    def __post_init__(self):
        valid_tiers = {"strict", "default", "break_glass"}
        if self.permission_tier not in valid_tiers:
            raise ValueError(
                f"permission_tier must be one of {sorted(valid_tiers)}, "
                f"got {self.permission_tier!r}"
            )


@dataclass
class AgentMemoryConfig:
    """Memory domain isolation policy for an agent."""

    own_domain: str
    readable_domains: list[str] | None = None
    can_read_shared: bool = True
    can_write: bool = True


@dataclass
class AgentSpec:
    """Top-level agent specification combining model, tool, and memory config.

    Supports construction from dicts, YAML files, and serialization back
    to dicts for YAML/JSON output.
    """

    name: str
    description: str
    enabled: bool = True
    models: AgentModelConfig = field(default_factory=AgentModelConfig)
    prompt_file: str | None = None
    soul_file: str | None = None
    tools: AgentToolConfig = field(default_factory=AgentToolConfig)
    memory: AgentMemoryConfig | None = None
    metadata: dict = field(default_factory=dict)

    def prompt(self, config_dir: Path) -> str:
        """Resolve prompt content, anchored to config_dir (not CWD).

        If prompt_file is set, its content is returned from config_dir.
        Raises FileNotFoundError if the file doesn't exist.
        Otherwise a default prompt string is generated.
        """
        if self.prompt_file:
            path = config_dir / self.prompt_file
            if not path.exists():
                raise FileNotFoundError(f"Prompt file not found: {path}")
            return path.read_text()
        return f"You are the {self.name} agent. Help the user with {self.name}-related tasks."

    def to_dict(self) -> dict:
        """Serialize to dict for YAML/JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec":
        """Deserialize from a plain dict, handling nested dataclasses.

        Raises ``KeyError`` if required fields (name, description) are missing.
        Raises ``TypeError`` if nested config sections are not dicts.
        """
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data).__name__}")
        for required in ("name", "description"):
            if required not in data:
                raise KeyError(f"Missing required field: {required!r}")

        models_data = data.get("models", {})
        if models_data and not isinstance(models_data, dict):
            raise TypeError(f"'models' must be a dict, got {type(models_data).__name__}")
        tools_data = data.get("tools", {})
        if tools_data and not isinstance(tools_data, dict):
            raise TypeError(f"'tools' must be a dict, got {type(tools_data).__name__}")
        memory_data = data.get("memory")
        if memory_data is not None and not isinstance(memory_data, dict):
            raise TypeError(f"'memory' must be a dict or null, got {type(memory_data).__name__}")

        return cls(
            name=data["name"],
            description=data["description"],
            enabled=data.get("enabled", True),
            models=AgentModelConfig(**_filter_known_fields(AgentModelConfig, models_data))
            if models_data
            else AgentModelConfig(),
            prompt_file=data.get("prompt_file"),
            soul_file=data.get("soul_file"),
            tools=AgentToolConfig(**_filter_known_fields(AgentToolConfig, tools_data))
            if tools_data
            else AgentToolConfig(),
            memory=AgentMemoryConfig(**_filter_known_fields(AgentMemoryConfig, memory_data)) if memory_data else None,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentSpec":
        """Load spec from a YAML file on disk.

        Raises ``ValueError`` if the YAML does not contain a mapping (dict).
        """
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping in {path.name}, got {type(data).__name__}")
        return cls.from_dict(data)
