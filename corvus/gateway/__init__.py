"""Gateway runtime and option builders for the FastAPI server."""

from corvus.gateway.chat_session import ChatSession, TurnContext
from corvus.gateway.dispatch_metrics import DispatchRunSummary, summarize_dispatch_runs
from corvus.gateway.dispatch_runtime import execute_dispatch_runs
from corvus.gateway.options import (
    any_llm_configured,
    build_backend_options,
    build_hooks,
    build_options,
    resolve_backend_and_model,
    ui_default_model,
    ui_model_id,
)
from corvus.gateway.runtime import GatewayRuntime, build_runtime, ensure_dirs, init_credentials

__all__ = [
    "ChatSession",
    "GatewayRuntime",
    "TurnContext",
    "DispatchRunSummary",
    "any_llm_configured",
    "build_backend_options",
    "build_hooks",
    "build_options",
    "build_runtime",
    "ensure_dirs",
    "execute_dispatch_runs",
    "init_credentials",
    "resolve_backend_and_model",
    "summarize_dispatch_runs",
    "ui_default_model",
    "ui_model_id",
]
