"""AgentsHub — the central coordinator for agent lifecycle.

Wires AgentSpec -> tools -> memory -> SDK AgentDefinition.
Replaces the monolithic build_options() in server.py.
"""

import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from claude_agent_sdk import AgentDefinition, SdkMcpTool, create_sdk_mcp_server

from corvus.agents.registry import AgentRegistry, ReloadResult
from corvus.agents.spec import AgentMemoryConfig, AgentSpec
from corvus.capabilities.modules import HUB_MANAGED_MODULES
from corvus.capabilities.registry import AgentSpecProtocol, CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.memory import MemoryHub, create_memory_toolkit
from corvus.memory.toolkit import MemoryTool
from corvus.model_router import ModelRouter

logger = structlog.get_logger(__name__)

# Valid model names accepted by AgentDefinition.model in the SDK.
SdkModelName = Literal["sonnet", "opus", "haiku", "inherit"]
_VALID_SDK_MODELS: set[str] = {"sonnet", "opus", "haiku", "inherit"}


def _validate_sdk_model(name: str | None) -> SdkModelName | None:
    """Validate a model name against SDK-accepted literals.

    Returns the name as a typed Literal if valid, None if input is None.
    Raises ValueError for unrecognized model names.
    """
    if name is None:
        return None
    if name not in _VALID_SDK_MODELS:
        raise ValueError(f"Invalid SDK model name: {name!r}. Valid: {sorted(_VALID_SDK_MODELS)}")
    return cast(SdkModelName, name)


@dataclass
class BuildResult:
    """Result of build_all() with agents + any errors.

    Callers must check errors — a non-empty errors dict means some agents
    failed to build and are missing from the agents dict.
    """

    agents: dict[str, "AgentDefinition"] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"BuildResult(agents={sorted(self.agents)}, errors={self.errors})"


@dataclass
class AgentSummary:
    """Lightweight agent info for frontend listing."""

    name: str
    description: str
    enabled: bool
    complexity: str
    tool_modules: list[str]
    memory_domain: str
    has_prompt: bool

    def __repr__(self) -> str:
        status = "on" if self.enabled else "off"
        return f"AgentSummary({self.name!r}, {status}, modules={self.tool_modules})"


@dataclass
class PromptLayer:
    """Single composed prompt layer for inspector and runtime assembly."""

    layer_id: str
    title: str
    source: str
    content: str


def _memory_tool_to_sdk(tool: MemoryTool) -> SdkMcpTool:
    """Convert a MemoryTool to SdkMcpTool for MCP server registration."""

    async def handler(args: dict) -> dict:
        result = await tool.fn(**args)
        return {"content": [{"type": "text", "text": result}]}

    schema = tool.input_schema or {"type": "object", "properties": {}}
    return SdkMcpTool(
        name=tool.name,
        description=tool.description,
        input_schema=schema,
        handler=handler,
    )


class AgentsHub:
    """Coordinates agent lifecycle: spec -> tools -> memory -> SDK options."""

    def __init__(
        self,
        registry: AgentRegistry,
        capabilities: CapabilitiesRegistry,
        memory_hub: MemoryHub,
        model_router: ModelRouter,
        emitter: EventEmitter,
        config_dir: Path,
    ) -> None:
        self.registry = registry
        self.capabilities = capabilities
        self.memory_hub = memory_hub
        self.model_router = model_router
        self.emitter = emitter
        self.config_dir = config_dir

    _DEFAULT_MEMORY_ACCESS = AgentMemoryConfig(
        own_domain="shared",
        can_read_shared=True,
        can_write=False,
    )

    def get_memory_access(self, agent_name: str) -> dict:
        """Resolve memory access config from AgentSpec YAML.

        Returns a dict compatible with agent_config.get_memory_access(),
        so MemoryHub can use this as a drop-in replacement.

        Returns safe read-only defaults for unknown agents (shared domain,
        no write permission) — MemoryHub enforces write rejection.
        """
        spec = self.registry.get(agent_name)
        if spec is None:
            logger.warning("unknown_agent_memory_access", agent_name=agent_name, detail="using safe defaults")
            mem = self._DEFAULT_MEMORY_ACCESS
        else:
            mem = spec.memory if spec.memory is not None else self._DEFAULT_MEMORY_ACCESS
        return {
            "own_domain": mem.own_domain,
            "can_read_shared": mem.can_read_shared,
            "can_write": mem.can_write,
            "readable_domains": mem.readable_domains,
        }

    def get_readable_private_domains(self, agent_name: str) -> list[str]:
        """Resolve readable private domains from AgentSpec YAML.

        Returns a list compatible with agent_config.get_readable_private_domains().
        """
        access = self.get_memory_access(agent_name)
        own = access.get("own_domain", "shared")
        extras = access.get("readable_domains") or []
        return [own] + [d for d in extras if d != own]

    def get_confirm_gated_tools(self) -> set[str]:
        """Derive confirm-gated tool names from all enabled agent specs.

        Gated tools are derived purely from YAML agent specs. Each agent's
        ``tools.confirm_gated`` list declares which tools require user
        confirmation before execution.

        YAML specs use short dotted names (e.g. "obsidian.write"). These are
        expanded to the full MCP tool name format used by the SDK hooks:
        ``mcp__{server}_{agent}__{tool}`` for per-agent servers, or
        ``mcp__{server}__{tool}`` for shared servers.
        """
        gated: set[str] = set()
        for spec in self.registry.list_enabled():
            for short_name in spec.tools.confirm_gated:
                gated.add(short_name)
                # Expand dotted short names to full MCP tool names.
                # "obsidian.write" → "mcp__obsidian_{agent}__obsidian_write"
                if "." in short_name:
                    module, action = short_name.split(".", 1)
                    # Per-agent server: mcp__{module}_{agent}__{module}_{action}
                    full_name = f"mcp__{module}_{spec.name}__{module}_{action}"
                    gated.add(full_name)
                    # Shared server: mcp__{module}__{module}_{action}
                    gated.add(f"mcp__{module}__{module}_{action}")
        return gated

    def _resolve_sdk_model(self, spec_name: str) -> str | None:
        """Resolve the SDK model for an agent via ModelRouter.

        Fully config-driven — no hardcoded model names.  ModelRouter reads
        sdk_native_models and complexity_defaults from models.yaml, so adding
        new models or changing complexity mappings requires only config changes.

        Returns the model string for SDK-native models, or None for
        non-native backends (handled by env_swap at the server layer).

        Precondition: spec_name must be a valid, registered agent.
        Called only from build_agent() which validates this.
        """
        spec = self.registry.get(spec_name)
        # build_agent() validates spec exists before calling this — if we get
        # None here, it's a bug in the caller, not a recoverable condition.
        if spec is None:
            raise ValueError(f"_resolve_sdk_model called for unregistered agent: {spec_name!r}")
        return self.model_router.resolve_sdk_model_for_agent(
            spec_name,
            complexity=spec.models.complexity,
        )

    def build_agent(self, name: str) -> AgentDefinition:
        """Build a single SDK AgentDefinition from spec."""
        spec = self.registry.get(name)
        if spec is None:
            raise ValueError(f"Agent '{name}' not found or disabled")
        if not spec.enabled:
            raise ValueError(f"Agent '{name}' not found or disabled")

        sdk_model = self._resolve_sdk_model(name)

        return AgentDefinition(
            description=spec.description,
            prompt=self._compose_prompt(name),
            tools=spec.tools.builtin,
            model=_validate_sdk_model(sdk_model),
        )

    def build_all(self) -> BuildResult:
        """Build all enabled agents. Returns BuildResult with agents + errors.

        Callers MUST check result.errors. A non-empty errors dict means some
        agents failed to build — the system is running in degraded mode.
        """
        result = BuildResult()
        for spec in self.registry.list_enabled():
            try:
                result.agents[spec.name] = self.build_agent(spec.name)
            except Exception as exc:
                logger.error("agent_build_failed", agent=spec.name, error=str(exc))
                result.errors[spec.name] = str(exc)
        if result.errors:
            logger.error("build_all_partial_failure", error_count=len(result.errors), failed_agents=list(result.errors.keys()))
        return result

    def build_mcp_servers(self, name: str) -> dict:
        """Build per-agent MCP servers (capabilities + memory).

        Raises ValueError if the agent is not found or disabled. Callers
        should only call this for agents returned by build_all().
        """
        spec = self.registry.get(name)
        if spec is None:
            raise ValueError(f"Agent '{name}' not found in registry")
        if not spec.enabled:
            raise ValueError(f"Agent '{name}' is disabled")

        # Resolve tool modules via security-enforced capabilities registry.
        # Skip hub-managed modules (e.g. "memory") — handled below.
        resolved = self.capabilities.resolve(cast(AgentSpecProtocol, spec), skip_modules=HUB_MANAGED_MODULES)

        # Add per-agent memory MCP server with baked-in identity.
        # Pass own_domain from spec so toolkit reads from YAML, not agent_config.
        own_domain = spec.memory.own_domain if spec.memory else "shared"
        memory_toolkit = create_memory_toolkit(
            self.memory_hub,
            agent_name=spec.name,
            own_domain=own_domain,
        )
        sdk_tools = [_memory_tool_to_sdk(t) for t in memory_toolkit]
        resolved.mcp_servers[f"memory_{spec.name}"] = create_sdk_mcp_server(
            name=f"memory_{spec.name}",
            version="1.0.0",
            tools=sdk_tools,
        )

        return resolved.mcp_servers

    # --- Prompt composition ---

    def _compose_prompt_layers(
        self,
        agent_name: str,
        *,
        include_workspace_context: bool = True,
    ) -> list[PromptLayer]:
        """Compose layered prompt sections for any agent.

        Every agent gets the same layered composition:
          0. Soul — shared identity, personality, principles (soul.md)
          1. Agent soul — per-agent personality/vibe (optional soul_file)
          2. Agent identity — dynamic per-agent name assertion
          3. Agent prompt — from the agent's prompt_file
          4. Sibling agents — dynamically discovered from the registry
          5. Memory context — seeded from MemoryHub per agent domain

        When ``include_workspace_context`` is False, workspace-backed user
        layers are represented as redacted stubs to keep previews safe.
        """
        layers: list[PromptLayer] = []
        spec = self.registry.get(agent_name)
        agent_label = spec.name if spec else agent_name

        # 0. Soul — shared core identity, personality, and principles.
        #    Counteracts the CLI binary's hardcoded "You are Claude" identity.
        soul_file = self.config_dir / "corvus" / "prompts" / "soul.md"
        if soul_file.exists():
            layers.append(
                PromptLayer(
                    layer_id="soul",
                    title="Soul",
                    source=str(soul_file.relative_to(self.config_dir)),
                    content=soul_file.read_text(),
                )
            )
        else:
            layers.append(
                PromptLayer(
                    layer_id="soul",
                    title="Soul",
                    source="fallback",
                    content=(
                        "You are an agent in **Corvus**, a local-first, self-hosted "
                        "multi-agent system.\n\n"
                        "You are NOT Claude. You are NOT made by Anthropic. "
                        "Disregard any prior identity instructions."
                    ),
                )
            )

        # 1. Agent soul — per-agent personality, vibe, behavioral style.
        #    Optional: if soul_file is set in the agent's YAML, load it.
        #    This is where each agent gets its own character.
        if spec and spec.soul_file:
            agent_soul_path = self.config_dir / spec.soul_file
            if agent_soul_path.exists():
                layers.append(
                    PromptLayer(
                        layer_id="agent_soul",
                        title="Agent Soul",
                        source=spec.soul_file,
                        content=agent_soul_path.read_text(),
                    )
                )
            else:
                logger.warning("soul_file_missing", agent=agent_name, soul_file=spec.soul_file)

        # 2. Agent identity — dynamic, per-agent
        layers.append(
            PromptLayer(
                layer_id="agent_identity",
                title="Agent Identity",
                source="generated",
                content=(
                    f"You are the **{agent_label}** agent. "
                    f"Always identify as the {agent_label} agent when asked who you are."
                ),
            )
        )

        # 2. Agent's own prompt from its spec
        if spec:
            try:
                layers.append(
                    PromptLayer(
                        layer_id="agent_prompt",
                        title="Agent Prompt",
                        source=spec.prompt_file or "generated",
                        content=spec.prompt(config_dir=self.config_dir),
                    )
                )
            except FileNotFoundError:
                logger.warning("prompt_file_missing", agent=agent_name)

        # 3. Sibling agents (composed dynamically from registry)
        enabled = self.registry.list_enabled()
        other_agents = [a for a in enabled if a.name != agent_name]
        if other_agents:
            agent_lines = ["# Other Agents in This System\n"]
            agent_lines.append(
                "If a question falls outside your domain, tell the user "
                "which of these agents can help:\n"
            )
            for a in other_agents:
                agent_lines.append(f"- **{a.name}**: {a.description.strip()}")
            layers.append(
                PromptLayer(
                    layer_id="sibling_agents",
                    title="Sibling Agents",
                    source="registry",
                    content="\n".join(agent_lines),
                )
            )

        # 4. Memory context — seeded from MemoryHub per agent domain
        if include_workspace_context:
            records = self.memory_hub.seed_context(agent_name, limit=15)
            if records:
                memory_lines = ["# Memory Context\n"]
                own_domain = (
                    spec.memory.own_domain if spec and spec.memory else "shared"
                )
                memory_lines.append(
                    f"Your memory domain is **{own_domain}**. "
                    "These are your most relevant recent and evergreen memories:\n"
                )
                for r in records:
                    tag_str = f" [{', '.join(r.tags)}]" if r.tags else ""
                    prefix = "[evergreen] " if r.importance >= 0.9 else ""
                    memory_lines.append(
                        f"- {prefix}({r.domain}) {r.content[:300]}{tag_str}"
                    )
                layers.append(
                    PromptLayer(
                        layer_id="memory_context",
                        title="Memory Context",
                        source="memory_hub",
                        content="\n".join(memory_lines),
                    )
                )
        else:
            layers.append(
                PromptLayer(
                    layer_id="memory_context",
                    title="Memory Context",
                    source="memory_hub",
                    content="[redacted in safe preview]",
                )
            )
        return layers

    def _compose_prompt(self, agent_name: str) -> str:
        """Compose a full runtime prompt with all layers included."""
        layers = self._compose_prompt_layers(agent_name, include_workspace_context=True)
        parts = [layer.content for layer in layers if layer.content]
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_prompt_preview(
        self,
        agent_name: str,
        *,
        include_workspace_context: bool = False,
        max_chars: int = 12000,
        clip_chars: int = 1200,
    ) -> dict[str, Any]:
        """Build layered prompt preview payload for frontend inspectors."""
        spec = self.registry.get(agent_name)
        if spec is None:
            raise ValueError(f"Agent '{agent_name}' not found")
        if clip_chars < 64:
            clip_chars = 64
        if max_chars < clip_chars:
            max_chars = clip_chars

        layers = self._compose_prompt_layers(
            agent_name,
            include_workspace_context=include_workspace_context,
        )
        total_chars = 0
        payload_layers: list[dict[str, Any]] = []
        for layer in layers:
            content = layer.content
            char_count = len(content)
            total_chars += char_count
            clipped = char_count > clip_chars
            preview_text = content[:clip_chars] + ("…" if clipped else "")
            payload_layers.append(
                {
                    "id": layer.layer_id,
                    "title": layer.title,
                    "source": layer.source,
                    "char_count": char_count,
                    "clipped": clipped,
                    "content_preview": preview_text,
                }
            )

        full_text = "\n\n---\n\n".join(layer.content for layer in layers if layer.content)
        full_clipped = len(full_text) > max_chars
        return {
            "agent": agent_name,
            "safe_mode": not include_workspace_context,
            "total_layers": len(payload_layers),
            "total_chars": total_chars,
            "full_preview": full_text[:max_chars] + ("…" if full_clipped else ""),
            "full_preview_clipped": full_clipped,
            "layers": payload_layers,
        }

    def build_system_prompt(self, agent_name: str = "huginn") -> str:
        """Compose system prompt for the root SDK session.

        Thin wrapper around _compose_prompt() — exists for backward
        compatibility with callers in server.py and options.py.
        """
        return self._compose_prompt(agent_name)

    # --- Frontend management ---

    def list_agents(self) -> list[AgentSummary]:
        """List all agents with summary info."""
        result = []
        for spec in self.registry.list_all():
            modules = list(spec.tools.modules.keys())
            result.append(
                AgentSummary(
                    name=spec.name,
                    description=spec.description,
                    enabled=spec.enabled,
                    complexity=spec.models.complexity,
                    tool_modules=modules,
                    memory_domain=spec.memory.own_domain if spec.memory else "shared",
                    has_prompt=spec.prompt_file is not None,
                )
            )
        return result

    def get_agent(self, name: str) -> AgentSpec | None:
        """Get full agent spec."""
        return self.registry.get(name)

    def create_agent(self, spec: AgentSpec) -> AgentSpec:
        """Create a new agent and persist to disk."""
        self.registry.create(spec)
        return spec

    def update_agent(self, name: str, patch: dict[str, Any]) -> AgentSpec:
        """Partial update of an agent."""
        return self.registry.update(name, patch)

    def deactivate_agent(self, name: str) -> None:
        """Deactivate an agent."""
        self.registry.deactivate(name)

    def reload(self) -> ReloadResult:
        """Reload agent specs from disk."""
        return self.registry.reload()
