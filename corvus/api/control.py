"""Control-plane REST endpoints (interrupts + break-glass lifecycle)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from corvus.auth import get_user
from corvus.gateway.control_plane import BreakGlassSessionRegistry, DispatchControlRegistry
from corvus.session_manager import SessionManager

router = APIRouter(prefix="/api", tags=["control"])

_session_mgr: SessionManager | None = None
_dispatch_controls: DispatchControlRegistry | None = None
_break_glass: BreakGlassSessionRegistry | None = None
_TERMINAL_DISPATCH_STATUSES = {"done", "error", "interrupted", "cancelled"}
_TERMINAL_RUN_STATUSES = {"done", "error", "interrupted"}


def configure(
    session_mgr: SessionManager,
    dispatch_controls: DispatchControlRegistry,
    break_glass: BreakGlassSessionRegistry,
) -> None:
    """Wire control endpoints to runtime dependencies."""
    if not isinstance(session_mgr, SessionManager):
        raise TypeError(f"Expected SessionManager, got {type(session_mgr).__name__}")
    if not isinstance(dispatch_controls, DispatchControlRegistry):
        raise TypeError(f"Expected DispatchControlRegistry, got {type(dispatch_controls).__name__}")
    if not isinstance(break_glass, BreakGlassSessionRegistry):
        raise TypeError(f"Expected BreakGlassSessionRegistry, got {type(break_glass).__name__}")
    global _session_mgr, _dispatch_controls, _break_glass
    _session_mgr = session_mgr
    _dispatch_controls = dispatch_controls
    _break_glass = break_glass


def _require_session_mgr() -> SessionManager:
    if _session_mgr is None:
        raise HTTPException(status_code=503, detail="SessionManager not initialized")
    return _session_mgr


def _require_dispatch_controls() -> DispatchControlRegistry:
    if _dispatch_controls is None:
        raise HTTPException(status_code=503, detail="DispatchControlRegistry not initialized")
    return _dispatch_controls


def _require_break_glass() -> BreakGlassSessionRegistry:
    if _break_glass is None:
        raise HTTPException(status_code=503, detail="BreakGlassSessionRegistry not initialized")
    return _break_glass


def _require_user_session(session_mgr: SessionManager, session_id: str, user: str) -> dict:
    session = session_mgr.get(session_id)
    if not session or session.get("user") != user:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/dispatch/active")
async def list_active_dispatches(user: str = Depends(get_user)):
    """List active in-memory dispatches scoped to current user."""
    rows = _require_dispatch_controls().list_active(user=user)
    return JSONResponse(rows)


@router.post("/dispatch/{dispatch_id}/interrupt")
async def interrupt_dispatch(dispatch_id: str, user: str = Depends(get_user)):
    """Request interrupt for an active dispatch."""
    session_mgr = _require_session_mgr()
    dispatch = session_mgr.get_dispatch(dispatch_id)
    if not dispatch:
        return JSONResponse({"error": "Dispatch not found"}, status_code=404)
    _require_user_session(session_mgr, dispatch["session_id"], user)

    status = str(dispatch.get("status") or "").lower()
    if status in _TERMINAL_DISPATCH_STATUSES:
        return JSONResponse(
            {
                "status": "already_terminal",
                "dispatch_id": dispatch_id,
                "dispatch_status": status,
                "active": False,
            }
        )

    active = _require_dispatch_controls().request_interrupt(dispatch_id, user=user, source="api")
    if active:
        session_mgr.update_dispatch(
            dispatch_id,
            status="interrupted",
            error="interrupt_requested",
            completed_at=datetime.now(UTC),
        )
        return JSONResponse(
            {
                "status": "interrupt_requested",
                "dispatch_id": dispatch_id,
                "active": True,
            }
        )

    return JSONResponse(
        {
            "status": "not_active",
            "dispatch_id": dispatch_id,
            "active": False,
            "dispatch_status": status or "unknown",
        }
    )


@router.post("/runs/{run_id}/interrupt")
async def interrupt_run(run_id: str, user: str = Depends(get_user)):
    """Request interrupt for a run by interrupting its parent dispatch."""
    session_mgr = _require_session_mgr()
    run = session_mgr.get_run(run_id)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    _require_user_session(session_mgr, run["session_id"], user)

    run_status = str(run.get("status") or "").lower()
    if run_status in _TERMINAL_RUN_STATUSES:
        return JSONResponse(
            {
                "status": "already_terminal",
                "run_id": run_id,
                "run_status": run_status,
                "active": False,
            }
        )

    active = _require_dispatch_controls().request_interrupt(run["dispatch_id"], user=user, source="api")
    if active:
        session_mgr.update_agent_run(
            run_id,
            status="interrupted",
            summary="Interrupted by API request",
            completed_at=datetime.now(UTC),
        )
        return JSONResponse(
            {
                "status": "interrupt_requested",
                "run_id": run_id,
                "dispatch_id": run["dispatch_id"],
                "active": True,
            }
        )

    return JSONResponse(
        {
            "status": "not_active",
            "run_id": run_id,
            "dispatch_id": run["dispatch_id"],
            "active": False,
            "run_status": run_status or "unknown",
        }
    )


@router.post("/break-glass/activate")
async def activate_break_glass(request: Request, user: str = Depends(get_user)):
    """Activate break-glass for a user/session with passphrase validation."""
    body = await request.json()
    session_id = str(body.get("session_id", "")).strip()
    passphrase = str(body.get("passphrase", ""))
    ttl_minutes_raw = body.get("ttl_minutes")
    ttl_minutes = int(ttl_minutes_raw) if isinstance(ttl_minutes_raw, int) else None

    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=422)
    if not passphrase:
        return JSONResponse({"error": "passphrase is required"}, status_code=422)

    session_mgr = _require_session_mgr()
    _require_user_session(session_mgr, session_id, user)

    ok, expires_at = _require_break_glass().activate(
        user=user,
        session_id=session_id,
        passphrase=passphrase,
        ttl_minutes=ttl_minutes,
    )
    if not ok:
        status = _require_break_glass().status(user=user, session_id=session_id)
        return JSONResponse(
            {
                "status": "denied",
                "session_id": session_id,
                "locked_out": status["locked_out"],
            },
            status_code=403,
        )

    return JSONResponse(
        {
            "status": "active",
            "session_id": session_id,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
    )


@router.post("/break-glass/deactivate")
async def deactivate_break_glass(request: Request, user: str = Depends(get_user)):
    """Deactivate break-glass for a user/session."""
    body = await request.json()
    session_id = str(body.get("session_id", "")).strip()
    if not session_id:
        return JSONResponse({"error": "session_id is required"}, status_code=422)

    session_mgr = _require_session_mgr()
    _require_user_session(session_mgr, session_id, user)

    removed = _require_break_glass().deactivate(user=user, session_id=session_id)
    return JSONResponse(
        {
            "status": "deactivated" if removed else "inactive",
            "session_id": session_id,
        }
    )


@router.get("/break-glass/status")
async def break_glass_status(session_id: str, user: str = Depends(get_user)):
    """Get break-glass status for a user/session."""
    session_mgr = _require_session_mgr()
    _require_user_session(session_mgr, session_id, user)
    status = _require_break_glass().status(user=user, session_id=session_id)
    return JSONResponse(
        {
            "session_id": session_id,
            **status,
        }
    )
