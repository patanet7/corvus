"""Session management REST endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from corvus.auth import get_user
from corvus.session_manager import SessionManager
from corvus.sessions.service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
runs_router = APIRouter(prefix="/api", tags=["sessions"])

_session_mgr: SessionManager | None = None
_session_service: SessionService | None = None
_VALID_DISPATCH_MODES = {"router", "direct", "parallel"}
_VALID_DISPATCH_STATUSES = {"queued", "running", "done", "error", "interrupted", "cancelled"}
_VALID_RUN_STATUSES = {"queued", "routing", "planning", "executing", "compacting", "done", "error", "interrupted"}


def configure(session_mgr: SessionManager) -> None:
    """Wire router to the active SessionManager instance."""
    if not isinstance(session_mgr, SessionManager):
        raise TypeError(f"Expected SessionManager, got {type(session_mgr).__name__}")
    global _session_mgr, _session_service
    _session_mgr = session_mgr
    _session_service = SessionService(session_mgr)


def _require_session_mgr() -> SessionManager:
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="SessionManager not initialized")
    return _session_mgr


def _require_session_service() -> SessionService:
    if _session_service is None:
        raise HTTPException(status_code=503, detail="SessionService not initialized")
    return _session_service


@router.get("")
async def list_sessions(
    agent: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """List sessions for the authenticated user, optionally filtered by agent."""
    sessions = _require_session_service().list_sessions(
        user=user,
        agent=agent,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(sessions)


@router.get("/{session_id}")
async def get_session(session_id: str, user: str = Depends(get_user)):
    """Get session detail (scoped to authenticated user)."""
    session = _require_session_service().get_user_session(session_id, user=user)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(session)


@router.delete("/{session_id}")
async def delete_session(session_id: str, user: str = Depends(get_user)):
    """Delete a session (scoped to authenticated user)."""
    if not _require_session_service().delete_user_session(session_id, user=user):
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"status": "deleted"})


@router.patch("/{session_id}")
async def rename_session(session_id: str, request: Request, user: str = Depends(get_user)):
    """Rename a session (scoped to authenticated user)."""
    body = await request.json()
    name = body.get("name", "")
    if not _require_session_service().rename_user_session(session_id, user=user, name=name):
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"status": "updated", "name": name})


@router.get("/{session_id}/export")
async def export_session(session_id: str, user: str = Depends(get_user)):
    """Export session as Markdown (scoped to authenticated user)."""
    markdown = _require_session_service().export_user_session_markdown(session_id, user=user)
    if markdown is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse({"markdown": markdown})


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = 2000,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Get persisted transcript messages for a session."""
    messages = _require_session_service().list_user_session_messages(
        session_id,
        user=user,
        limit=limit,
        offset=offset,
    )
    if messages is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(messages)


@router.get("/{session_id}/events")
async def get_session_events(
    session_id: str,
    limit: int = 2000,
    offset: int = 0,
    event_type: list[str] | None = None,
    user: str = Depends(get_user),
):
    """Get persisted event stream rows for a session."""
    events = _require_session_service().list_user_session_events(
        session_id,
        user=user,
        limit=limit,
        offset=offset,
        event_types=event_type,
    )
    if events is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(events)


@runs_router.get("/runs/{run_id}")
async def get_run(run_id: str, user: str = Depends(get_user)):
    """Get a single run payload scoped to the authenticated user."""
    run = _require_session_service().get_user_run(run_id, user=user)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return JSONResponse(run)


@runs_router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = 2000,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Get persisted run events scoped to authenticated user."""
    session_mgr = _require_session_mgr()
    run = _require_session_service().get_user_run(run_id, user=user)
    if run is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    events = session_mgr.list_run_events(run_id, limit=limit, offset=offset)
    return JSONResponse(events)


@runs_router.get("/dispatch/{dispatch_id}")
async def get_dispatch(dispatch_id: str, user: str = Depends(get_user)):
    """Get dispatch metadata scoped to authenticated user."""
    dispatch = _require_session_service().get_user_dispatch(dispatch_id, user=user)
    if dispatch is None:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)
    return JSONResponse(dispatch)


@runs_router.get("/dispatch")
async def list_dispatches(
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """List dispatches scoped to authenticated user."""
    rows = _require_session_service().list_user_dispatches(
        user=user,
        session_id=session_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(rows)


@runs_router.get("/dispatch/{dispatch_id}/runs")
async def get_dispatch_runs(
    dispatch_id: str,
    limit: int = 200,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """Get dispatch child runs scoped to authenticated user."""
    dispatch = _require_session_service().get_user_dispatch(dispatch_id, user=user)
    if dispatch is None:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)
    return JSONResponse(_require_session_mgr().list_dispatch_runs(dispatch_id, limit=limit, offset=offset))


@runs_router.get("/dispatch/{dispatch_id}/events")
async def get_dispatch_events(
    dispatch_id: str,
    limit: int = 4000,
    offset: int = 0,
    event_type: list[str] | None = None,
    user: str = Depends(get_user),
):
    """Get dispatch replay events scoped to authenticated user."""
    dispatch = _require_session_service().get_user_dispatch(dispatch_id, user=user)
    if dispatch is None:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)
    events = _require_session_mgr().list_dispatch_events(
        dispatch_id,
        limit=limit,
        offset=offset,
        event_types=event_type,
    )
    return JSONResponse(events)


@runs_router.patch("/dispatch/{dispatch_id}")
async def update_dispatch(dispatch_id: str, request: Request, user: str = Depends(get_user)):
    """Update dispatch status/error fields (user-scoped)."""
    session_mgr = _require_session_mgr()
    if _require_session_service().get_user_dispatch(dispatch_id, user=user) is None:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)

    body = await request.json()
    status = str(body.get("status", "")).strip().lower()
    if status not in _VALID_DISPATCH_STATUSES:
        return JSONResponse(
            {"error": f"Invalid dispatch status: {status or '<empty>'}"},
            status_code=422,
        )
    error = body.get("error")
    error_text = str(error).strip() if isinstance(error, str) and error.strip() else None
    completed_at = datetime.now(UTC) if status in {"done", "error", "interrupted", "cancelled"} else None
    session_mgr.update_dispatch(
        dispatch_id,
        status=status,
        error=error_text,
        completed_at=completed_at,
    )
    updated = session_mgr.get_dispatch(dispatch_id)
    return JSONResponse(updated)


@runs_router.delete("/dispatch/{dispatch_id}")
async def delete_dispatch(dispatch_id: str, user: str = Depends(get_user)):
    """Delete a dispatch (and child runs/events) scoped to authenticated user."""
    session_mgr = _require_session_mgr()
    if _require_session_service().get_user_dispatch(dispatch_id, user=user) is None:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)
    session_mgr.delete_dispatch(dispatch_id)
    return JSONResponse({"status": "deleted", "dispatch_id": dispatch_id})


@runs_router.post("/dispatch")
async def create_dispatch(request: Request, user: str = Depends(get_user)):
    """Create a queued dispatch row (used by frontend planning/preview flows)."""
    session_mgr = _require_session_mgr()
    body = await request.json()
    session_id = str(body.get("session_id", "")).strip()
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=422)
    if _require_session_service().get_user_session(session_id, user=user) is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=422)

    targets_raw = body.get("target_agents", [])
    if not isinstance(targets_raw, list):
        return JSONResponse({"error": "target_agents must be a list"}, status_code=422)
    target_agents = [str(agent).strip() for agent in targets_raw if str(agent).strip()]
    if not target_agents:
        return JSONResponse({"error": "target_agents cannot be empty"}, status_code=422)

    dispatch_mode = str(body.get("dispatch_mode", "parallel")).strip().lower() or "parallel"
    if dispatch_mode not in _VALID_DISPATCH_MODES:
        return JSONResponse(
            {"error": f"dispatch_mode must be one of: {sorted(_VALID_DISPATCH_MODES)}"},
            status_code=422,
        )
    turn_id_raw = body.get("turn_id")
    turn_id = str(turn_id_raw).strip() if isinstance(turn_id_raw, str) and turn_id_raw.strip() else None

    dispatch_id = str(uuid.uuid4())
    session_mgr.create_dispatch(
        dispatch_id,
        session_id=session_id,
        user=user,
        prompt=prompt,
        dispatch_mode=dispatch_mode,
        target_agents=target_agents,
        turn_id=turn_id,
        status="queued",
    )
    dispatch = session_mgr.get_dispatch(dispatch_id)
    return JSONResponse(dispatch, status_code=201)


@runs_router.get("/runs")
async def list_runs(
    session_id: str | None = None,
    dispatch_id: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """List runs across all sessions for the authenticated user."""
    rows = _require_session_service().list_user_runs(
        user=user,
        session_id=session_id,
        dispatch_id=dispatch_id,
        agent=agent,
        status=status,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(rows)


@runs_router.patch("/runs/{run_id}")
async def update_run(run_id: str, request: Request, user: str = Depends(get_user)):
    """Update a persisted run status/summary/error scoped to authenticated user."""
    session_mgr = _require_session_mgr()
    if _require_session_service().get_user_run(run_id, user=user) is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    body = await request.json()
    status = str(body.get("status", "")).strip().lower()
    if status not in _VALID_RUN_STATUSES:
        return JSONResponse(
            {"error": f"Invalid run status: {status or '<empty>'}"},
            status_code=422,
        )
    summary = body.get("summary")
    summary_text = str(summary).strip() if isinstance(summary, str) and summary.strip() else None
    error = body.get("error")
    error_text = str(error).strip() if isinstance(error, str) and error.strip() else None
    completed_at = datetime.now(UTC) if status in {"done", "error", "interrupted"} else None

    session_mgr.update_agent_run(
        run_id,
        status=status,
        summary=summary_text,
        error=error_text,
        completed_at=completed_at,
    )
    updated = session_mgr.get_run(run_id)
    return JSONResponse(updated)


@runs_router.delete("/runs/{run_id}")
async def delete_run(run_id: str, user: str = Depends(get_user)):
    """Delete a run (and child run events) scoped to authenticated user."""
    session_mgr = _require_session_mgr()
    if _require_session_service().get_user_run(run_id, user=user) is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    session_mgr.delete_run(run_id)
    return JSONResponse({"status": "deleted", "run_id": run_id})
