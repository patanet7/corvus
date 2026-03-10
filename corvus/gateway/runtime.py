"""Runtime wiring for the Corvus gateway.

This module owns startup-time object construction (registries, hubs,
scheduler, supervisor) so server.py can stay as a thin composition root.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass
from pathlib import Path

from fastapi import WebSocket

from corvus.acp.registry import AcpAgentRegistry
from corvus.agents.hub import AgentsHub
from corvus.agents.registry import AgentRegistry
from corvus.break_glass import BreakGlassManager
from corvus.capabilities.config import CapabilitiesConfig
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.config import (
    CAPABILITIES_CONFIG,
    CLAUDE_RUNTIME_HOME,
    EVENTS_LOG,
    ISOLATE_CLAUDE_HOME,
    MEMORY_CONFIG,
    MEMORY_DB,
    MEMORY_DIR,
    SCHEDULES_CONFIG,
    TASK_ROUTING_CONFIG,
    WORKSPACE_DIR,
)
from corvus.credential_store import get_credential_store
from corvus.events import EventEmitter, JSONLFileSink
from corvus.gateway.control_plane import BreakGlassSessionRegistry, DispatchControlRegistry
from corvus.gateway.sdk_client_manager import SDKClientManager
from corvus.gateway.task_planner import TaskPlanner
from corvus.gateway.trace_hub import TraceHub
from corvus.litellm_manager import LiteLLMManager
from corvus.memory import MemoryConfig, MemoryHub
from corvus.memory.backends.protocol import MemoryBackend
from corvus.model_router import ModelRouter
from corvus.router import RouterAgent
from corvus.sanitize import register_credential_patterns
from corvus.scheduler import CronScheduler
from corvus.session_manager import SessionManager
from corvus.supervisor import AgentSupervisor

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class GatewayRuntime:
    """All long-lived runtime components used by route handlers."""

    emitter: EventEmitter
    model_router: ModelRouter
    litellm_manager: LiteLLMManager
    agent_registry: AgentRegistry
    capabilities_registry: CapabilitiesRegistry
    memory_hub: MemoryHub
    agents_hub: AgentsHub
    router_agent: RouterAgent
    session_mgr: SessionManager
    scheduler: CronScheduler
    supervisor: AgentSupervisor
    task_planner: TaskPlanner
    trace_hub: TraceHub
    dispatch_controls: DispatchControlRegistry
    break_glass: BreakGlassSessionRegistry
    acp_registry: AcpAgentRegistry
    sdk_client_manager: SDKClientManager
    active_connections: set[WebSocket]


def init_credentials() -> None:
    """Load credentials and register sanitization patterns."""
    try:
        store = get_credential_store()
        store.inject()
        register_credential_patterns(store.credential_values())
        logger.info(
            "credentials_loaded",
            source="sops",
            pattern_count=len(store.credential_values()),
        )
    except (FileNotFoundError, OSError) as exc:
        logger.info("no_sops_store_found", error_type=type(exc).__name__)
    except ValueError as exc:
        logger.warning("sops_store_malformed", error=str(exc))


def _build_router_agent(agent_registry: AgentRegistry, model_router: ModelRouter) -> RouterAgent:
    """Build RouterAgent.

    LiteLLM handles backend routing and fallbacks, so no Ollama probing needed.
    """
    del model_router  # Unused — LiteLLM handles backend selection.
    return RouterAgent(registry=agent_registry)


def ensure_dirs() -> None:
    """Create all required directories for local dev / first run."""
    paths = [MEMORY_DB.parent, MEMORY_DIR, WORKSPACE_DIR, EVENTS_LOG.parent]
    if ISOLATE_CLAUDE_HOME:
        paths.extend(
            [
                CLAUDE_RUNTIME_HOME,
                CLAUDE_RUNTIME_HOME / ".claude",
                CLAUDE_RUNTIME_HOME / ".config",
                CLAUDE_RUNTIME_HOME / ".cache",
                CLAUDE_RUNTIME_HOME / ".local" / "state",
                CLAUDE_RUNTIME_HOME / ".local" / "share",
            ]
        )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def _load_memory_config() -> MemoryConfig:
    """Load memory config from YAML, defaulting to current MEMORY_DB."""
    return MemoryConfig.from_file(
        MEMORY_CONFIG,
        default_db_path=MEMORY_DB,
    )


def _build_memory_overlays(memory_config: MemoryConfig) -> list[MemoryBackend]:
    """Instantiate enabled overlay backends from memory config."""
    overlays: list[MemoryBackend] = []
    for overlay_cfg in memory_config.enabled_overlays():
        name = overlay_cfg.name.strip().lower()
        try:
            if name == "cognee":
                from corvus.memory.backends.cognee import CogneeBackend

                overlays.append(
                    CogneeBackend(
                        weight=overlay_cfg.weight,
                        **overlay_cfg.settings,
                    )
                )
            else:
                logger.warning("unsupported_memory_overlay", overlay=overlay_cfg.name)
        except Exception:
            logger.exception("memory_overlay_init_failed", overlay=overlay_cfg.name)
    return overlays


def build_runtime() -> GatewayRuntime:
    """Construct all runtime dependencies and validate startup readiness."""
    emitter = EventEmitter()
    emitter.register_sink(JSONLFileSink(EVENTS_LOG))

    model_router = ModelRouter.from_file(Path("config/models.yaml"))
    litellm_manager = LiteLLMManager()
    init_credentials()

    agent_registry = AgentRegistry(config_dir=Path("config/agents"))
    agent_registry.load()
    logger.info("agent_registry_loaded", agent_count=len(agent_registry.list_all()))

    capabilities_registry = CapabilitiesRegistry()
    module_defs_by_name = {module_def.name: module_def for module_def in TOOL_MODULE_DEFS}
    module_order = [module_def.name for module_def in TOOL_MODULE_DEFS]
    capabilities_cfg = CapabilitiesConfig.from_file(CAPABILITIES_CONFIG, available_modules=module_order)
    enabled_modules = capabilities_cfg.enabled_modules(module_order)
    for module_name in enabled_modules:
        capabilities_registry.register(module_name, module_defs_by_name[module_name])
    logger.info(
        "capabilities_registry_loaded",
        module_count=len(capabilities_registry.list_available()),
        config_path=str(CAPABILITIES_CONFIG),
        modules=enabled_modules,
    )

    supervisor = AgentSupervisor(registry=capabilities_registry, emitter=emitter)

    memory_config = _load_memory_config()
    memory_overlays = _build_memory_overlays(memory_config)
    memory_hub = MemoryHub(memory_config, overlays=memory_overlays)
    logger.info(
        "memory_hub_initialized",
        primary_db=str(memory_config.primary_db_path),
        overlay_count=len(memory_overlays),
        configured_count=len(memory_config.enabled_overlays()),
    )
    agents_hub = AgentsHub(
        registry=agent_registry,
        capabilities=capabilities_registry,
        memory_hub=memory_hub,
        model_router=model_router,
        emitter=emitter,
        config_dir=Path(__file__).resolve().parent.parent.parent,
    )
    memory_hub.set_resolvers(
        get_memory_access_fn=agents_hub.get_memory_access,
        get_readable_domains_fn=agents_hub.get_readable_private_domains,
    )

    hub_errors = memory_hub.validate_ready()
    if hub_errors:
        for err in hub_errors:
            logger.error("startup_validation_failed", error=err)
        raise RuntimeError(f"AgentsHub startup validation failed: {'; '.join(hub_errors)}")
    logger.info("agents_hub_initialized")

    router_agent = _build_router_agent(agent_registry=agent_registry, model_router=model_router)
    session_mgr = SessionManager(db_path=MEMORY_DB)

    scheduler = CronScheduler(
        config_path=SCHEDULES_CONFIG,
        db_path=MEMORY_DB,
        emitter=emitter,
    )
    task_planner = TaskPlanner.from_file(TASK_ROUTING_CONFIG, model_router=model_router)
    trace_hub = TraceHub()
    dispatch_controls = DispatchControlRegistry()
    break_glass_mgr = BreakGlassManager()
    break_glass = BreakGlassSessionRegistry(break_glass_mgr)

    acp_registry = AcpAgentRegistry(config_dir=Path("config"))
    acp_registry.load()
    logger.info("acp_registry_loaded", agent_count=len(acp_registry.list_agents()))

    sdk_client_manager = SDKClientManager(runtime=None)

    active_connections: set[WebSocket] = set()
    scheduler.set_connections(active_connections)

    rt = GatewayRuntime(
        emitter=emitter,
        model_router=model_router,
        litellm_manager=litellm_manager,
        agent_registry=agent_registry,
        capabilities_registry=capabilities_registry,
        memory_hub=memory_hub,
        agents_hub=agents_hub,
        router_agent=router_agent,
        session_mgr=session_mgr,
        scheduler=scheduler,
        supervisor=supervisor,
        task_planner=task_planner,
        trace_hub=trace_hub,
        dispatch_controls=dispatch_controls,
        break_glass=break_glass,
        acp_registry=acp_registry,
        sdk_client_manager=sdk_client_manager,
        active_connections=active_connections,
    )
    sdk_client_manager.set_runtime(rt)
    return rt
