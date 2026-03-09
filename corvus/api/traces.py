"""Trace observability REST + WebSocket endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from corvus.auth import get_user
from corvus.gateway.trace_hub import TraceHub
from corvus.security.session_auth import SessionAuthManager
from corvus.session_manager import SessionManager

logger = logging.getLogger("corvus-gateway")

router = APIRouter(prefix="/api", tags=["traces"])
ws_router = APIRouter(tags=["traces"])

_session_mgr: SessionManager | None = None
_trace_hub: TraceHub | None = None
_session_auth: SessionAuthManager | None = None


def configure(
    session_mgr: SessionManager,
    trace_hub: TraceHub,
    session_auth: SessionAuthManager | None = None,
) -> None:
    """Wire trace routes to runtime dependencies."""
    if not isinstance(session_mgr, SessionManager):
        raise TypeError(f"Expected SessionManager, got {type(session_mgr).__name__}")
    if not isinstance(trace_hub, TraceHub):
        raise TypeError(f"Expected TraceHub, got {type(trace_hub).__name__}")
    global _session_mgr, _trace_hub, _session_auth
    _session_mgr = session_mgr
    _trace_hub = trace_hub
    _session_auth = session_auth


def _require_session_mgr() -> SessionManager:
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="SessionManager not initialized")
    return _session_mgr


def _require_trace_hub() -> TraceHub:
    if _trace_hub is None:
        raise HTTPException(status_code=503, detail="TraceHub not initialized")
    return _trace_hub


def _normalize_csv(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    normalized = [value.strip() for value in values if value and value.strip()]
    return normalized or None


@router.get("/traces/recent")
async def list_recent_traces(
    limit: int = 300,
    offset: int = 0,
    source_app: list[str] | None = Query(default=None),
    session_id: list[str] | None = Query(default=None),
    dispatch_id: str | None = None,
    run_id: str | None = None,
    hook_event_type: list[str] | None = Query(default=None),
    user: str = Depends(get_user),
):
    """Return recent hook-style trace events scoped to the authenticated user."""
    rows = _require_session_mgr().list_trace_events(
        user=user,
        source_apps=_normalize_csv(source_app),
        session_ids=_normalize_csv(session_id),
        dispatch_id=dispatch_id,
        run_id=run_id,
        hook_event_types=_normalize_csv(hook_event_type),
        limit=limit,
        offset=offset,
    )
    return JSONResponse(rows)


@router.get("/traces/filter-options")
async def get_trace_filter_options(user: str = Depends(get_user)):
    """Return distinct source/session/event values for trace UI filters."""
    options = _require_session_mgr().get_trace_filter_options(user=user)
    return JSONResponse(options)


@router.get("/traces/{trace_id}")
async def get_trace_event(trace_id: int, user: str = Depends(get_user)):
    """Return a single trace event row by id (user-scoped)."""
    row = _require_session_mgr().get_trace_event(trace_id, user=user)
    if row is None:
        return JSONResponse({"error": "Trace event not found"}, status_code=404)
    return JSONResponse(row)


@router.post("/traces/events")
async def ingest_trace_event(request: Request, user: str = Depends(get_user)):
    """Ingest a hook-style trace event and fan out to timeline subscribers."""
    session_mgr = _require_session_mgr()
    trace_hub = _require_trace_hub()
    body = await request.json()

    source_app = str(body.get("source_app", "")).strip()
    session_id = str(body.get("session_id", "")).strip()
    hook_event_type = str(body.get("hook_event_type", "")).strip()
    payload = body.get("payload")
    if not source_app:
        return JSONResponse({"error": "source_app is required"}, status_code=422)
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=422)
    if not hook_event_type:
        return JSONResponse({"error": "hook_event_type is required"}, status_code=422)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "payload must be an object"}, status_code=422)

    session = session_mgr.get(session_id)
    if session is None or session.get("user") != user:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    trace_row = session_mgr.add_trace_event(
        source_app=source_app,
        session_id=session_id,
        dispatch_id=str(body["dispatch_id"]).strip() if body.get("dispatch_id") else None,
        run_id=str(body["run_id"]).strip() if body.get("run_id") else None,
        turn_id=str(body["turn_id"]).strip() if body.get("turn_id") else None,
        hook_event_type=hook_event_type,
        payload=payload,
        summary=str(body["summary"]).strip() if body.get("summary") else None,
        model_name=str(body["model_name"]).strip() if body.get("model_name") else None,
    )
    await trace_hub.publish(user=user, event=trace_row)
    return JSONResponse(trace_row, status_code=201)


@router.get("/sessions/{session_id}/traces")
async def list_session_traces(
    session_id: str,
    limit: int = 1000,
    offset: int = 0,
    hook_event_type: list[str] | None = Query(default=None),
    user: str = Depends(get_user),
):
    """Return trace rows for a single session (user-scoped)."""
    session_mgr = _require_session_mgr()
    session = session_mgr.get(session_id)
    if not session or session.get("user") != user:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    rows = session_mgr.list_trace_events(
        user=user,
        session_ids=[session_id],
        hook_event_types=_normalize_csv(hook_event_type),
        limit=limit,
        offset=offset,
    )
    return JSONResponse(rows)


@ws_router.websocket("/ws/traces")
async def websocket_trace_stream(websocket: WebSocket):
    """Live trace stream for frontend observability dashboards."""
    session_mgr = _require_session_mgr()
    trace_hub = _require_trace_hub()

    if _session_auth is None:
        logger.error("/ws/traces: SessionAuthManager not configured — rejecting connection")
        await websocket.close(code=4401, reason="Auth not configured")
        return

    token = websocket.query_params.get("token")
    headers = {k.lower(): v for k, v in websocket.headers.items()}
    client_host = websocket.client.host if websocket.client else None

    auth_result = _session_auth.authenticate(
        client_host=client_host,
        token=token,
        headers=headers,
    )
    if not auth_result.authenticated:
        logger.debug(
            "/ws/traces auth denied for %s: %s", client_host, auth_result.reason
        )
        await websocket.close(code=4401, reason=auth_result.reason or "Unauthorized")
        return
    user = auth_result.user

    await websocket.accept()

    limit_raw = websocket.query_params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw else 200
    except ValueError:
        limit = 200
    limit = max(1, min(limit, 2000))

    recent = session_mgr.list_trace_events(user=user, limit=limit, offset=0)
    options = session_mgr.get_trace_filter_options(user=user)
    await websocket.send_json({"type": "trace_init", "events": recent, "filter_options": options})

    queue = trace_hub.subscribe()
    try:
        while True:
            envelope = await queue.get()
            if envelope.user != user:
                continue
            await websocket.send_json({"type": "trace_event", "data": envelope.event})
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        raise
    finally:
        trace_hub.unsubscribe(queue)
