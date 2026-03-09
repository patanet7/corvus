"""Memory REST endpoints for frontend memory workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from corvus.agents.hub import AgentsHub
from corvus.auth import get_user
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord

router = APIRouter(prefix="/api/memory", tags=["memory"])

_memory_hub: MemoryHub | None = None
_agents_hub: AgentsHub | None = None


def configure(memory_hub: MemoryHub, agents_hub: AgentsHub) -> None:
    """Wire router to runtime memory + agents hubs."""
    if not isinstance(memory_hub, MemoryHub):
        raise TypeError(f"Expected MemoryHub, got {type(memory_hub).__name__}")
    if not isinstance(agents_hub, AgentsHub):
        raise TypeError(f"Expected AgentsHub, got {type(agents_hub).__name__}")
    global _memory_hub, _agents_hub
    _memory_hub = memory_hub
    _agents_hub = agents_hub


def _require_memory_hub() -> MemoryHub:
    if _memory_hub is None:
        raise HTTPException(status_code=503, detail="MemoryHub not initialized")
    return _memory_hub


def _require_agents_hub() -> AgentsHub:
    if _agents_hub is None:
        raise HTTPException(status_code=503, detail="AgentsHub not initialized")
    return _agents_hub


def _default_agent_name() -> str:
    summaries = [summary for summary in _require_agents_hub().list_agents() if summary.enabled]
    if not summaries:
        return "general"
    for preferred in ("huginn", "general"):
        if any(summary.name == preferred for summary in summaries):
            return preferred
    return summaries[0].name


def _resolve_agent_name(raw: object) -> str:
    if isinstance(raw, str) and raw.strip():
        name = raw.strip()
        if _require_agents_hub().get_agent(name) is None:
            raise HTTPException(status_code=404, detail=f"Agent not found: {name}")
        return name
    return _default_agent_name()


def _normalize_tags(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="tags must be a list")
    tags: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized:
            tags.append(normalized)
    return tags


@router.get("/agents")
async def list_memory_agents(user: str = Depends(get_user)):
    """List enabled agents with memory access metadata."""
    del user
    hub = _require_agents_hub()
    memory_hub = _require_memory_hub()
    rows: list[dict] = []
    for summary in hub.list_agents():
        if not summary.enabled:
            continue
        access = memory_hub.get_memory_access(summary.name)
        rows.append(
            {
                "id": summary.name,
                "label": summary.name.title(),
                "memory_domain": access.get("own_domain", "shared"),
                "can_write": bool(access.get("can_write", False)),
                "can_read_shared": bool(access.get("can_read_shared", True)),
                "readable_private_domains": hub.get_readable_private_domains(summary.name),
            }
        )
    return JSONResponse(rows)


@router.get("/backends")
async def list_memory_backends(user: str = Depends(get_user)):
    """Expose memory backend health/configuration for observability UI."""
    del user
    status = await _require_memory_hub().backend_status()
    return JSONResponse(status)


@router.get("/records")
async def list_memory_records(
    agent: str | None = None,
    domain: str | None = None,
    limit: int = 40,
    offset: int = 0,
    user: str = Depends(get_user),
):
    """List visible memory records for an agent context."""
    del user
    agent_name = _resolve_agent_name(agent)
    rows = await _require_memory_hub().list_memories(
        agent_name=agent_name,
        domain=domain,
        limit=limit,
        offset=offset,
    )
    return JSONResponse([row.to_dict() for row in rows])


@router.get("/records/search")
async def search_memory_records(
    q: str,
    agent: str | None = None,
    domain: str | None = None,
    limit: int = 20,
    user: str = Depends(get_user),
):
    """Search visible memory records for an agent context."""
    del user
    query = q.strip()
    if not query:
        return JSONResponse({"error": "q is required"}, status_code=422)
    agent_name = _resolve_agent_name(agent)
    rows = await _require_memory_hub().search(
        query,
        agent_name=agent_name,
        limit=limit,
        domain=domain,
    )
    return JSONResponse([row.to_dict() for row in rows])


@router.get("/records/{record_id}")
async def get_memory_record(
    record_id: str,
    agent: str | None = None,
    user: str = Depends(get_user),
):
    """Get one memory record if visible to the agent context."""
    del user
    agent_name = _resolve_agent_name(agent)
    try:
        row = await _require_memory_hub().get(record_id, agent_name=agent_name)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    if row is None:
        return JSONResponse({"error": "Record not found"}, status_code=404)
    return JSONResponse(row.to_dict())


@router.post("/records")
async def create_memory_record(request: Request, user: str = Depends(get_user)):
    """Create a memory record in the selected agent's writable domain."""
    body = await request.json()
    agent_name = _resolve_agent_name(body.get("agent"))
    content = str(body.get("content", "")).strip()
    if not content:
        return JSONResponse({"error": "content is required"}, status_code=422)

    visibility = str(body.get("visibility", "private")).strip().lower() or "private"
    importance_raw = body.get("importance", 0.5)
    try:
        importance = float(importance_raw)
    except (TypeError, ValueError):
        return JSONResponse({"error": "importance must be numeric"}, status_code=422)
    importance = max(0.0, min(1.0, importance))
    tags = _normalize_tags(body.get("tags"))
    metadata = body.get("metadata")
    if metadata is None:
        metadata_dict: dict = {}
    elif isinstance(metadata, dict):
        metadata_dict = metadata
    else:
        return JSONResponse({"error": "metadata must be an object"}, status_code=422)

    memory_hub = _require_memory_hub()
    access = memory_hub.get_memory_access(agent_name)
    own_domain = str(access.get("own_domain", "shared"))
    domain_raw = body.get("domain")
    domain = own_domain
    if isinstance(domain_raw, str) and domain_raw.strip():
        requested_domain = domain_raw.strip()
        # SEC-009: If an agent was explicitly provided, enforce that the
        # requested domain matches the agent's own_domain.  This prevents
        # cross-domain writes where e.g. the "personal" agent tries to
        # write into the "work" domain.
        if body.get("agent") and requested_domain != own_domain:
            return JSONResponse(
                {
                    "error": (
                        f"Domain mismatch: agent '{agent_name}' owns domain "
                        f"'{own_domain}' but request targets '{requested_domain}'"
                    )
                },
                status_code=403,
            )
        domain = requested_domain

    record = MemoryRecord(
        id=str(uuid4()),
        content=content,
        domain=domain,
        visibility=visibility,  # validated in MemoryRecord.__post_init__
        importance=importance,
        tags=tags,
        source=f"ui:{user}",
        created_at=datetime.now(UTC).isoformat(),
        metadata=metadata_dict,
    )

    try:
        await memory_hub.save(record, agent_name=agent_name)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    return JSONResponse(record.to_dict(), status_code=201)


@router.patch("/records/{record_id}")
async def update_memory_record(
    record_id: str,
    request: Request,
    user: str = Depends(get_user),
):
    """Update mutable fields on a memory record."""
    del user
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "request body must be a JSON object"}, status_code=422)

    agent_name = _resolve_agent_name(body.get("agent"))
    has_content = "content" in body
    has_visibility = "visibility" in body
    has_importance = "importance" in body
    has_tags = "tags" in body
    has_metadata = "metadata" in body
    if not any((has_content, has_visibility, has_importance, has_tags, has_metadata)):
        return JSONResponse(
            {"error": "At least one of content, visibility, importance, tags, metadata is required"},
            status_code=422,
        )

    content: str | None = None
    if has_content:
        content = str(body.get("content", "")).strip()
        if not content:
            return JSONResponse({"error": "content must be non-empty when provided"}, status_code=422)

    visibility: str | None = None
    if has_visibility:
        visibility = str(body.get("visibility", "")).strip().lower()
        if not visibility:
            return JSONResponse({"error": "visibility must be non-empty when provided"}, status_code=422)

    importance: float | None = None
    if has_importance:
        try:
            importance = float(body.get("importance"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "importance must be numeric"}, status_code=422)
        importance = max(0.0, min(1.0, importance))

    tags = _normalize_tags(body.get("tags")) if has_tags else None

    metadata: dict | None = None
    if has_metadata:
        raw = body.get("metadata")
        if raw is None:
            metadata = {}
        elif isinstance(raw, dict):
            metadata = raw
        else:
            return JSONResponse({"error": "metadata must be an object"}, status_code=422)

    try:
        row = await _require_memory_hub().update(
            record_id,
            agent_name=agent_name,
            content=content,
            visibility=visibility,
            importance=importance,
            tags=tags,
            metadata=metadata,
        )
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    if row is None:
        return JSONResponse({"error": "Record not found"}, status_code=404)
    return JSONResponse(row.to_dict())


@router.delete("/records/{record_id}")
async def forget_memory_record(
    record_id: str,
    agent: str | None = None,
    user: str = Depends(get_user),
):
    """Soft-delete a memory record."""
    del user
    agent_name = _resolve_agent_name(agent)
    try:
        deleted = await _require_memory_hub().forget(record_id, agent_name=agent_name)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    if not deleted:
        return JSONResponse({"error": "Record not found"}, status_code=404)
    return JSONResponse({"status": "forgotten", "record_id": record_id})
