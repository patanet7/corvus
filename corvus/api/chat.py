"""WebSocket chat endpoint — thin router that delegates to ChatSession.

Protocol contract (enforced by ChatSession, verified by source tests):
  - "type": "routing"      — agent routing notification after classification
  - "type": "error"        — error messages sent to frontend
  - "tokens_used"          — included in done message
  - "context_pct"          — included in done message
  - "interrupt"            — client interrupt handling
  - "ping" / "pong"        — keepalive
  - "confirm_response"     — user confirmation flow
  - json.JSONDecodeError   — "Invalid JSON" error on malformed input
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from corvus.config import ALLOWED_USERS
from corvus.gateway.chat_session import ChatSession
from corvus.gateway.runtime import GatewayRuntime
from corvus.security.session_auth import SessionAuthManager
from corvus.session import extract_session_memories

logger = logging.getLogger("corvus-gateway")

router = APIRouter(tags=["chat"])

_runtime: GatewayRuntime | None = None
_session_auth: SessionAuthManager | None = None


def _build_session_auth() -> SessionAuthManager:
    """Build SessionAuthManager from environment.

    Uses CORVUS_SESSION_SECRET env var (must be >= 32 bytes).
    Falls back to os.urandom(64) for dev/testing — logs a warning.
    """
    secret_env = os.environ.get("CORVUS_SESSION_SECRET", "")
    if secret_env:
        secret = secret_env.encode()
    else:
        logger.warning(
            "CORVUS_SESSION_SECRET not set — generating ephemeral secret. "
            "Set this env var for persistent session tokens across restarts."
        )
        secret = os.urandom(64)
    return SessionAuthManager(secret=secret, allowed_users=ALLOWED_USERS)


def configure(runtime: GatewayRuntime) -> None:
    """Wire router to the active gateway runtime."""
    if not isinstance(runtime, GatewayRuntime):
        raise TypeError(f"Expected GatewayRuntime, got {type(runtime).__name__}")
    global _runtime, _session_auth
    _runtime = runtime
    _session_auth = _build_session_auth()


def _require_runtime() -> GatewayRuntime:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Gateway runtime not initialized")
    return _runtime


def _require_session_auth() -> SessionAuthManager:
    if _session_auth is None:
        raise HTTPException(status_code=503, detail="Session auth not initialized")
    return _session_auth


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for persistent chat sessions."""
    # TODO(phase2): Replace serial interrupt handling with async queue orchestration.
    runtime = _require_runtime()

    # Auth BEFORE accept — reject unauthorized connections at protocol level.
    session_auth = _require_session_auth()
    token = websocket.query_params.get("token")
    headers = {k.lower(): v for k, v in websocket.headers.items()}
    client_host = websocket.client.host if websocket.client else None

    auth_result = session_auth.authenticate(
        client_host=client_host,
        token=token,
        headers=headers,
    )
    if not auth_result.authenticated:
        logger.debug(
            "WebSocket auth denied for %s: %s", client_host, auth_result.reason
        )
        await websocket.close(code=4401, reason=auth_result.reason or "Unauthorized")
        return
    user = auth_result.user

    await websocket.accept()
    runtime.active_connections.add(websocket)

    requested_session_id = websocket.query_params.get("session_id")
    resumed = False
    resumed_session: dict | None = None
    if requested_session_id:
        resumed_session = runtime.session_mgr.get(requested_session_id)
        if resumed_session and resumed_session.get("user") == user:
            session_id = requested_session_id
            resumed = True
        else:
            requested_session_id = None
            resumed_session = None

    if resumed:
        started_at = datetime.now(UTC)
        logger.info("Resumed chat session for user=%s session_id=%s", user, session_id)
    else:
        session_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        logger.info("Chat session started for user=%s session_id=%s", user, session_id)
        runtime.session_mgr.start(session_id, user=user, started_at=started_at)

    await runtime.emitter.emit("session_start", user=user, session_id=session_id)

    session = ChatSession(
        runtime=runtime,
        websocket=websocket,
        user=user,
        session_id=session_id,
    )

    try:
        await session.run(started_at=started_at, resumed_session=resumed_session)
    except WebSocketDisconnect:
        runtime.active_connections.discard(websocket)
        logger.info("Chat session ended for user=%s session_id=%s", user, session_id)
        await runtime.emitter.emit(
            "session_end",
            user=user,
            session_id=session_id,
            message_count=session.transcript.message_count(),
            duration_seconds=(datetime.now(UTC) - started_at).total_seconds(),
        )

        try:
            runtime.session_mgr.end(
                session_id=session_id,
                ended_at=datetime.now(UTC),
                message_count=session.transcript.message_count(),
                tool_count=session.transcript.tool_count,
                agents_used=list(session.transcript.agents_used),
            )
        except Exception:
            logger.exception("Failed to end session %s", session_id)

        try:
            memories = await extract_session_memories(
                session.transcript,
                runtime.memory_hub,
                agent_name=session.transcript.primary_agent(),
            )
            if memories:
                logger.info("Extracted %d memories from session for user=%s", len(memories), user)
        except Exception:
            logger.exception("Session memory extraction failed for user=%s", user)

    except Exception:
        runtime.active_connections.discard(websocket)
        logger.exception("Error in chat session")
        await websocket.close(code=1011, reason="Internal error")


@router.post("/api/auth/token")
async def create_auth_token(request: Request):
    """Create a session token for WebSocket authentication.

    Authenticates the caller via trusted reverse-proxy headers
    (X-Remote-User / Remote-User) or localhost origin, then issues
    a signed session token for subsequent WebSocket connections.

    This endpoint is the bootstrap mechanism: it allows localhost
    or proxy-authenticated users to obtain a token without already
    having one.
    """
    session_auth = _require_session_auth()
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Allow token bootstrap via trusted headers
    user = headers.get("x-remote-user") or headers.get("remote-user")

    # Allow localhost to bootstrap tokens (this is the only place
    # localhost trust remains — the WebSocket path no longer auto-auths)
    if not user:
        client_host = request.client.host if request.client else None
        if client_host in ("127.0.0.1", "::1", "localhost"):
            if ALLOWED_USERS:
                user = ALLOWED_USERS[0]

    if not user or user not in ALLOWED_USERS:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = session_auth.create_session_token(user)
    return {"token": token, "user": user}
