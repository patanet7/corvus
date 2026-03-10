"""CapabilitiesRegistry — security-enforced tool resolution.

The registry is the security boundary for tool access. It enforces deny-wins
policy at resolution time: if an env gate fails, the module is excluded.
Hooks (corvus/hooks.py) remain for observability/audit only.
"""

import os

import structlog
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Type alias for MCP server objects returned by create_sdk_mcp_server()
McpServer = Any  # SDK returns opaque server objects

logger = structlog.get_logger(__name__)


def _has_required_env_value(var_name: str) -> bool:
    """Return True when env var exists and is non-empty after stripping."""
    value = os.environ.get(var_name)
    return value is not None and value.strip() != ""


# --- Structural contracts for duck-typed inputs ---


class _ToolConfig(Protocol):
    """Minimal tool config contract expected by resolve()."""

    modules: dict[str, dict]
    confirm_gated: list[str]


@runtime_checkable
class AgentSpecProtocol(Protocol):
    """Structural contract for agent specs passed to resolve()/confirm_gated().

    Any object with these attributes satisfies the contract, without coupling
    to the concrete AgentSpec class.
    """

    name: str
    tools: _ToolConfig


@dataclass
class ModuleHealth:
    """Health status of a registered tool module."""

    name: str
    status: str = "healthy"  # "healthy" | "unhealthy" | "degraded" | "unknown"
    detail: str = ""


@dataclass
class ToolModuleEntry:
    """Registration entry for a tool module with its lifecycle callables.

    Attributes:
        name: Unique module identifier (e.g. "paperless", "firefly").
        configure: Callable that takes module config dict and returns prepared config.
        create_tools: Callable that takes config dict and returns tool descriptors.
        create_mcp_server: Callable that takes (tools, config) and returns server descriptor.
        requires_env: List of env var names that must all be set for this module to activate.
        supports_per_agent: If True, MCP server is named {module}_{agent} for isolation.
        health_check: Optional callable returning ModuleHealth for this module.
        restart: Optional callable to restart/reinitialize this module.
    """

    name: str
    configure: Callable[[dict[str, Any]], dict[str, Any]]
    create_tools: Callable[[dict[str, Any]], list[Callable]]
    create_mcp_server: Callable[[list[Callable], dict[str, Any]], McpServer]
    requires_env: list[str] = field(default_factory=list)
    supports_per_agent: bool = False
    health_check: Callable | None = None
    restart: Callable | None = None


@dataclass
class ResolvedTools:
    """Result of resolving tool modules for an agent spec.

    Attributes:
        mcp_servers: Dict of server_name -> server descriptor for available modules.
        confirm_gated: Set of tool names that require user confirmation before execution.
        available_modules: List of module names that passed all gates and are active.
        unavailable_modules: Dict of module_name -> reason string for excluded modules.
    """

    mcp_servers: dict[str, McpServer] = field(default_factory=dict)
    confirm_gated: set[str] = field(default_factory=set)
    available_modules: list[str] = field(default_factory=list)
    unavailable_modules: dict[str, str] = field(default_factory=dict)


class CapabilitiesRegistry:
    """Security-enforced tool module registry.

    Modules are registered at startup. At resolve() time, each module requested
    by an AgentSpec is checked against env gates. If any required env var is
    missing, the module is excluded (deny-wins). This is the security boundary
    that prevents agents from accessing tools they lack credentials for.
    """

    def __init__(self) -> None:
        self._modules: dict[str, ToolModuleEntry] = {}

    def register(self, name: str, module: ToolModuleEntry) -> None:
        """Register a tool module. Raises ValueError on duplicate name."""
        if name in self._modules:
            raise ValueError(f"Module '{name}' is already registered. Duplicate module registration is not allowed.")
        self._modules[name] = module
        logger.info("tool_module_registered", module=name)

    def resolve(
        self,
        agent_spec: AgentSpecProtocol,
        skip_modules: frozenset[str] | None = None,
    ) -> ResolvedTools:
        """Resolve tool modules for the given agent spec.

        Steps:
        1. Read agent_spec.tools.modules (dict of module_name -> module_cfg).
        2. Skip modules in *skip_modules* (e.g. hub-managed ``memory``).
        3. For each module, check if entry exists in registry.
        4. Check env gates (requires_env -- all must be present and non-empty).
        5. Call entry.configure(module_cfg) to initialise the provider.
        6. Call entry.create_tools(module_cfg) then entry.create_mcp_server().
        7. If supports_per_agent, name server as {module}_{agent_name}; else {module}.
        8. Set confirm_gated from agent_spec.tools.confirm_gated.
        9. Track available vs unavailable modules with reasons.

        Args:
            agent_spec: An object satisfying AgentSpecProtocol (.name, .tools.modules,
                        .tools.confirm_gated).
            skip_modules: Module names to silently skip (handled elsewhere).

        Returns:
            ResolvedTools with populated mcp_servers, available/unavailable modules,
            and confirm_gated set.

        Raises:
            TypeError: If agent_spec does not satisfy AgentSpecProtocol.
        """
        if not isinstance(agent_spec, AgentSpecProtocol):
            raise TypeError(f"agent_spec must satisfy AgentSpecProtocol, got {type(agent_spec).__name__}")
        result = ResolvedTools()
        _skip = skip_modules or frozenset()

        # Collect confirm-gated tools from the spec
        result.confirm_gated = set(agent_spec.tools.confirm_gated)

        # Resolve each requested module
        requested_modules: dict[str, dict] = agent_spec.tools.modules
        for module_name, module_cfg in requested_modules.items():
            # Skip modules managed outside the capabilities registry
            if module_name in _skip:
                continue

            # Check if module is registered
            entry = self._modules.get(module_name)
            if entry is None:
                result.unavailable_modules[module_name] = (
                    f"Module '{module_name}' is not registered in the capabilities registry."
                )
                logger.warning("unregistered_module_requested", agent=agent_spec.name, module=module_name)
                continue

            # Check env gates (deny-wins: ALL required env vars must be present and non-empty)
            missing_env = [var for var in entry.requires_env if not _has_required_env_value(var)]
            if missing_env:
                result.unavailable_modules[module_name] = (
                    f"Missing required environment variables: {', '.join(missing_env)}"
                )
                logger.info("module_env_gate_failed", module=module_name, agent=agent_spec.name, missing_env=missing_env)
                continue

            # All gates passed — configure, create tools, and build MCP server.
            # Wrap in try/except so one module failure doesn't abort the rest.
            try:
                cfg = entry.configure(module_cfg)
                tools = entry.create_tools(cfg)
                server = entry.create_mcp_server(tools, cfg)
            except Exception as exc:
                result.unavailable_modules[module_name] = f"Module '{module_name}' failed during initialization: {exc}"
                logger.error("module_init_failed", module=module_name, agent=agent_spec.name, error=str(exc))
                continue

            # Determine server name based on per-agent isolation setting
            if entry.supports_per_agent:
                server_name = f"{module_name}_{agent_spec.name}"
            else:
                server_name = module_name

            result.mcp_servers[server_name] = server
            result.available_modules.append(module_name)
            logger.info("module_resolved", module=module_name, server=server_name, agent=agent_spec.name)

        return result

    def is_allowed(self, agent_name: str, tool_name: str) -> bool:
        """Check if a tool module is registered and its env gates are satisfied.

        This is a quick check that does not create tools or servers -- it only
        verifies that the module exists and all required env vars are set.

        Args:
            agent_name: Name of the agent requesting access (for logging).
            tool_name: Name of the tool module to check.

        Returns:
            True if the module is registered and all env gates pass; False otherwise.
        """
        entry = self._modules.get(tool_name)
        if entry is None:
            return False

        missing_env = [var for var in entry.requires_env if not _has_required_env_value(var)]
        if missing_env:
            logger.debug("is_allowed_denied", agent=agent_name, tool=tool_name, missing_env=missing_env)
            return False

        return True

    def confirm_gated(self, agent_spec: AgentSpecProtocol) -> set[str]:
        """Return the set of confirm-gated tool names from an AgentSpec.

        Args:
            agent_spec: An AgentSpec (or duck-typed object with .tools.confirm_gated).

        Returns:
            Set of tool names requiring user confirmation.
        """
        return set(agent_spec.tools.confirm_gated)

    def list_available(self) -> list[str]:
        """Return the names of all registered modules (regardless of env gates)."""
        return list(self._modules.keys())

    def health(self, name: str) -> ModuleHealth:
        """Return the health status of a registered module.

        If the module has a health_check callable, invoke it and return the result
        (overriding the name field to match the registered name). If no health_check
        is configured, return status "unknown". If the module is not registered,
        return status "unknown" with an explanatory detail.

        Args:
            name: The registered module name.

        Returns:
            ModuleHealth with current status.
        """
        entry = self._modules.get(name)
        if entry is None:
            return ModuleHealth(
                name=name,
                status="unknown",
                detail=f"Module '{name}' is not registered.",
            )

        if entry.health_check is None:
            return ModuleHealth(name=name, status="unknown")

        health_result: ModuleHealth = entry.health_check()
        # Ensure the name matches the registered name
        health_result.name = name
        return health_result

    def get_module(self, name: str) -> ToolModuleEntry | None:
        """Return the ToolModuleEntry for a registered module, or None if not found."""
        return self._modules.get(name)
