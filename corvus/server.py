"""Corvus Gateway FastAPI composition root.

This module intentionally stays thin: it wires runtime dependencies,
registers API routers, and exposes legacy-compatible symbols used by
other modules (for example corvus.webhooks importing build_options/emitter).
"""

# ruff: noqa: E402, I001

from __future__ import annotations

# Load .env before importing modules that read env-backed config.
from dotenv import load_dotenv

load_dotenv()

import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from claude_agent_sdk import ClaudeAgentOptions
from fastapi import FastAPI, WebSocket

from corvus.api.agents import configure as configure_agents_api
from corvus.api.agents import router as agents_router
from corvus.api.chat import configure as configure_chat_api
from corvus.api.chat import router as chat_router
from corvus.api.control import configure as configure_control_api
from corvus.api.control import router as control_router
from corvus.api.models import configure as configure_models_api
from corvus.api.models import router as models_router
from corvus.api.memory import configure as configure_memory_api
from corvus.api.memory import router as memory_router
from corvus.api.schedules import configure as configure_schedules_api
from corvus.api.schedules import router as schedules_router
from corvus.api.sessions import configure as configure_sessions_api
from corvus.api.sessions import runs_router as session_runs_router
from corvus.api.sessions import router as sessions_router
from corvus.api.traces import configure as configure_traces_api
from corvus.api.traces import router as traces_router
from corvus.api.traces import ws_router as traces_ws_router
from corvus.api.webhooks import router as webhooks_router
from corvus.config import HOST, PORT
from corvus.gateway.options import any_llm_configured, build_options as build_runtime_options
from corvus.gateway.runtime import GatewayRuntime, build_runtime, ensure_dirs, init_credentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("corvus-gateway")

# Strip CLAUDECODE so SDK can spawn its own CLI instances.
os.environ.pop("CLAUDECODE", None)

runtime: GatewayRuntime = build_runtime()

# Legacy-compatible module exports used by existing code/tests.
emitter = runtime.emitter
session_mgr = runtime.session_mgr
scheduler = runtime.scheduler
supervisor = runtime.supervisor
model_router = runtime.model_router
router_agent = runtime.router_agent


def _init_credentials() -> None:
    """Backward-compatible alias for credential bootstrap."""
    init_credentials()


def _any_llm_configured() -> bool:
    """Backward-compatible alias for backend availability check."""
    return any_llm_configured()


def build_options(user: str, websocket: WebSocket | None = None) -> ClaudeAgentOptions:
    """Backward-compatible options builder used by webhook dispatch."""
    return build_runtime_options(runtime=runtime, user=user, websocket=websocket)


def get_memory_hub():
    """Expose active MemoryHub instance for compatibility."""
    return runtime.memory_hub


def build_system_prompt(agent_name: str = "huginn") -> str:
    """Expose system prompt composition for compatibility."""
    return runtime.agents_hub.build_system_prompt(agent_name)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Start/stop supervisor and scheduler around FastAPI lifespan."""
    del _app
    ensure_dirs()

    try:
        await runtime.litellm_manager.start(Path("config/models.yaml"))
    except Exception as exc:
        logger.warning("LiteLLM proxy failed to start, using config-based routing: %s", exc)
    runtime.model_router.discover_models()

    await runtime.supervisor.start()
    logger.info("AgentSupervisor heartbeat started")

    runtime.scheduler.load()
    await runtime.scheduler.start()
    logger.info("CronScheduler started with %d schedules", len(runtime.scheduler.schedules))

    yield

    await runtime.litellm_manager.stop()

    await runtime.scheduler.stop()
    logger.info("CronScheduler stopped")

    await runtime.supervisor.graceful_shutdown()
    logger.info("AgentSupervisor stopped")


app = FastAPI(title="Corvus Gateway", lifespan=lifespan)

configure_agents_api(
    runtime.agents_hub,
    runtime.capabilities_registry,
    runtime.session_mgr,
    runtime.model_router,
)
configure_chat_api(runtime)
configure_models_api(runtime.model_router)
configure_memory_api(runtime.memory_hub, runtime.agents_hub)
configure_schedules_api(runtime.scheduler)
configure_sessions_api(runtime.session_mgr)
configure_traces_api(runtime.session_mgr, runtime.trace_hub)
configure_control_api(runtime.session_mgr, runtime.dispatch_controls, runtime.break_glass)

app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(models_router)
app.include_router(memory_router)
app.include_router(schedules_router)
app.include_router(sessions_router)
app.include_router(control_router)
app.include_router(session_runs_router)
app.include_router(traces_router)
app.include_router(traces_ws_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health():
    """Health check endpoint with backend status summary."""
    all_models = runtime.model_router.list_all_models()
    backends_summary: dict[str, dict] = {
        backend_name: {"status": "not_configured", "models": []}
        for backend_name in runtime.model_router.list_backends()
    }
    for model in all_models:
        if model.backend not in backends_summary:
            backends_summary[model.backend] = {"status": "not_configured", "models": []}
        backends_summary[model.backend]["models"].append(model.id)
        if model.available:
            backends_summary[model.backend]["status"] = "configured"

    return {
        "status": "ok" if any_llm_configured() else "degraded",
        "service": "corvus-gateway",
        "backends": backends_summary,
    }


def main():
    """Run the Corvus Gateway server."""
    uvicorn.run(
        "corvus.server:app",
        host=HOST,
        port=PORT,
        ws_max_size=16 * 1024 * 1024,
        loop="asyncio",  # uvloop does not support SDK subprocess 'user' kwarg.
        reload=os.environ.get("CORVUS_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
