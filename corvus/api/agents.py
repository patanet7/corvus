"""Agent management and capabilities REST endpoints.

Provides CRUD for agent specs and inspection of the capabilities registry.
The router is configured at startup with references to AgentsHub and
CapabilitiesRegistry via the configure() function.

All endpoints require authentication via Depends(get_user).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from corvus.agents.hub import AgentsHub
from corvus.agents.service import AgentsService
from corvus.agents.spec import AgentSpec
from corvus.auth import get_user
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.model_router import ModelRouter
from corvus.session_manager import SessionManager

_hub: AgentsHub | None = None
_capabilities: CapabilitiesRegistry | None = None
_session_mgr: SessionManager | None = None
_model_router: ModelRouter | None = None
_service: AgentsService | None = None

router = APIRouter(prefix="/api", tags=["agents"])


def _require_hub() -> AgentsHub:
    """Return the AgentsHub or fail fast if not configured."""
    if _hub is None:
        raise HTTPException(
            status_code=503,
            detail="AgentsHub not initialized — call configure() at startup",
        )
    return _hub


def _require_capabilities() -> CapabilitiesRegistry:
    """Return the CapabilitiesRegistry or fail fast if not configured."""
    if _capabilities is None:
        raise HTTPException(
            status_code=503,
            detail="CapabilitiesRegistry not initialized — call configure() at startup",
        )
    return _capabilities


def _require_session_mgr() -> SessionManager:
    if _session_mgr is None:
        raise HTTPException(
            status_code=503,
            detail="SessionManager not initialized — call configure() at startup",
        )
    return _session_mgr


def _require_model_router() -> ModelRouter:
    """Return the ModelRouter or fail fast if not configured."""
    if _model_router is None:
        raise HTTPException(status_code=503, detail="ModelRouter not initialized")
    return _model_router


def _require_service() -> AgentsService:
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail="AgentsService not initialized — call configure() at startup",
        )
    return _service


def configure(
    hub: AgentsHub,
    capabilities: CapabilitiesRegistry,
    session_mgr: SessionManager | None = None,
    model_router: ModelRouter | None = None,
    claude_runtime_home: Path | None = None,
    claude_home_scope: str | None = None,
) -> None:
    """Wire the router to live AgentsHub and CapabilitiesRegistry instances."""
    if not isinstance(hub, AgentsHub):
        raise TypeError(f"Expected AgentsHub, got {type(hub).__name__}")
    if not isinstance(capabilities, CapabilitiesRegistry):
        raise TypeError(f"Expected CapabilitiesRegistry, got {type(capabilities).__name__}")
    if session_mgr is not None and not isinstance(session_mgr, SessionManager):
        raise TypeError(f"Expected SessionManager, got {type(session_mgr).__name__}")
    if model_router is not None and not isinstance(model_router, ModelRouter):
        raise TypeError(f"Expected ModelRouter, got {type(model_router).__name__}")
    if claude_runtime_home is not None and not isinstance(claude_runtime_home, Path):
        raise TypeError(f"Expected Path for claude_runtime_home, got {type(claude_runtime_home).__name__}")
    if claude_home_scope is not None and not isinstance(claude_home_scope, str):
        raise TypeError(f"Expected str for claude_home_scope, got {type(claude_home_scope).__name__}")
    global _hub, _capabilities
    global _session_mgr, _model_router, _service
    _hub = hub
    _capabilities = capabilities
    _session_mgr = session_mgr
    _model_router = model_router
    _service = AgentsService(
        hub=hub,
        capabilities=capabilities,
        session_mgr=session_mgr,
        model_router=model_router,
        **(
            {"claude_runtime_home": claude_runtime_home}
            if claude_runtime_home is not None
            else {}
        ),
        **(
            {"claude_home_scope": claude_home_scope}
            if claude_home_scope is not None
            else {}
        ),
    )


@router.get("/agents")
async def list_agents(user: str = Depends(get_user)):
    """List all agents with summary info."""
    return _require_service().list_agents()


@router.get("/agents/{name}")
async def get_agent(name: str, user: str = Depends(get_user)):
    """Get full agent spec by name."""
    data = _require_service().get_agent(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}")
    return data


@router.get("/agents/{name}/prompt-preview")
async def get_agent_prompt_preview(
    name: str,
    include_workspace: bool = False,
    max_chars: int = 12000,
    clip_chars: int = 1200,
    user: str = Depends(get_user),
):
    """Get a layered prompt preview for inspector UIs."""
    try:
        return _require_service().get_agent_prompt_preview(
            name,
            include_workspace_context=include_workspace,
            max_chars=max_chars,
            clip_chars=clip_chars,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc


@router.get("/agents/{name}/policy")
async def get_agent_policy(name: str, user: str = Depends(get_user)):
    """Get normalized permission matrix payload for the agent."""
    try:
        return _require_service().get_agent_policy(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc


@router.get("/agents/{agent_name}/model-config")
async def get_agent_model_config(
    agent_name: str,
    user: str = Depends(get_user),
):
    """Get model routing config for an agent."""
    model_router = _require_model_router()
    model = model_router.get_model(agent_name)
    backend = model_router.get_backend(agent_name)
    context_limit = model_router.get_context_limit(model)
    return {
        "agent": agent_name,
        "model": model,
        "backend": backend,
        "context_limit": context_limit,
    }


@router.post("/agents")
async def create_agent(request: Request, user: str = Depends(get_user)):
    """Create a new agent from a JSON spec."""
    body = await request.json()
    try:
        spec = AgentSpec.from_dict(body)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid agent spec: {exc}") from exc
    try:
        _require_service().create_agent(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"status": "created", "name": spec.name}, status_code=201)


@router.patch("/agents/{name}")
async def update_agent(name: str, request: Request, user: str = Depends(get_user)):
    """Partial update of an agent spec."""
    body = await request.json()
    try:
        updated = _require_service().update_agent(name, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.to_dict()


@router.delete("/agents/{name}")
async def deactivate_agent(name: str, user: str = Depends(get_user)):
    """Deactivate an agent (set enabled=false)."""
    try:
        _require_service().deactivate_agent(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc
    return {"status": "deactivated", "name": name}


@router.post("/agents/reload")
async def reload_agents(user: str = Depends(get_user)):
    """Reload agent specs from disk."""
    return _require_service().reload_agents()


@router.get("/agents/{agent_name}/history")
async def get_agent_history(
    agent_name: str,
    limit: int = 50,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Get run history for a specific agent."""
    session_mgr = _require_session_mgr()
    runs = session_mgr.list_runs(agent=agent_name, limit=limit, offset=offset)
    return {"agent": agent_name, "runs": runs, "total": len(runs)}


@router.get("/agents/{name}/sessions")
async def list_agent_sessions(
    name: str,
    limit: int = 50,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Return sessions where the given agent participated."""
    try:
        rows = _require_service().list_agent_sessions(name=name, user=user, limit=limit, offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(rows)


@router.get("/agents/{name}/runs")
async def list_agent_runs(
    name: str,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Return persisted runs for an agent."""
    try:
        runs = _require_service().list_agent_runs(
            name=name,
            user=user,
            status=status,
            limit=limit,
            offset=offset,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc
    return JSONResponse(runs)


@router.get("/agents/{name}/todos")
async def list_agent_todos(
    name: str,
    limit_files: int = 20,
    limit_items: int = 200,
    user: str = Depends(get_user),
):
    """Return Claude runtime todo artifacts for an agent (scoped per user)."""
    try:
        todos = _require_service().list_agent_todos(
            name=name,
            user=user,
            limit_files=limit_files,
            limit_items=limit_items,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent not found: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(todos)


@router.get("/capabilities")
async def list_capabilities(user: str = Depends(get_user)):
    """List all registered capability modules."""
    return {"modules": _require_service().list_capabilities()}


@router.get("/capabilities/{name}")
async def get_capability_health(name: str, user: str = Depends(get_user)):
    """Get health status of a capability module."""
    return _require_service().capability_health(name)


@router.get("/agents/health")
async def agents_health(user: str = Depends(get_user)):
    """Hub health: agent count, capability status, and readiness."""
    return _require_service().agents_health()
