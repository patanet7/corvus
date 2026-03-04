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
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from corvus.config import ALLOWED_USERS
from corvus.gateway.chat_session import ChatSession
from corvus.gateway.runtime import GatewayRuntime
from corvus.session import extract_session_memories

logger = logging.getLogger("corvus-gateway")

router = APIRouter(tags=["chat"])

_runtime: GatewayRuntime | None = None


def configure(runtime: GatewayRuntime) -> None:
    """Wire router to the active gateway runtime."""
    if not isinstance(runtime, GatewayRuntime):
        raise TypeError(f"Expected GatewayRuntime, got {type(runtime).__name__}")
    global _runtime
    _runtime = runtime


def _require_runtime() -> GatewayRuntime:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Gateway runtime not initialized")
    return _runtime


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for persistent chat sessions."""
    # TODO(phase2): Replace serial interrupt handling with async queue orchestration.
    runtime = _require_runtime()

    # Auth BEFORE accept — reject unauthorized connections at protocol level.
    user = websocket.headers.get("X-Remote-User") or websocket.headers.get("Remote-User")
    if not user:
        client_host = websocket.client.host if websocket.client else None
        if client_host in ("127.0.0.1", "::1", "localhost"):
            user = ALLOWED_USERS[0]
            logger.debug("Local dev WebSocket: defaulting user to %s", user)
    if not user or user not in ALLOWED_USERS:
        await websocket.close(code=4401, reason="Unauthorized")
        return

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
