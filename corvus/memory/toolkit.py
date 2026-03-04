"""MemoryToolkit — SDK tools with closure-injected agent identity.

Created per-agent at spawn time. The agent_name is captured in closures
and cannot be overridden by the agent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord

logger = logging.getLogger(__name__)


@dataclass
class MemoryTool:
    """A single memory tool with name, async function, description, and schema."""

    name: str
    fn: Callable[..., Awaitable[str]]  # async callable
    description: str
    input_schema: dict | None = None


def create_memory_toolkit(
    hub: MemoryHub,
    agent_name: str,
    own_domain: str | None = None,
) -> list[MemoryTool]:
    """Create memory tools with identity baked into closures.

    Called by the gateway when spawning an agent. agent_name is captured
    in the closure — the agent cannot override it.

    Args:
        hub: The MemoryHub instance for storage operations.
        agent_name: The agent identity baked into closures.
        own_domain: The agent's memory domain, read from AgentSpec YAML
            by AgentsHub. Defaults to "shared" if not provided.

    Returns a list of MemoryTool objects ready for SDK registration.
    """
    if own_domain is None:
        own_domain = hub.get_memory_access(agent_name).get("own_domain", "shared")

    async def memory_search(
        query: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> str:
        """Search memories by query. Returns ranked results with BM25 scoring."""
        results = await hub.search(
            query,
            agent_name=agent_name,
            limit=limit,
            domain=domain,
        )
        return json.dumps([r.to_dict() for r in results])

    async def memory_save(
        content: str,
        visibility: str = "private",
        tags: str = "",
        importance: float = 0.5,
    ) -> str:
        """Save a new memory. Domain is auto-set from your identity.

        Args:
            content: The memory text to save.
            visibility: "private" (only you can see) or "shared" (all agents).
            tags: Comma-separated tags (e.g., "docker,deploy").
            importance: 0.0-1.0. Set >= 0.9 for evergreen (never decays).
        """
        valid_visibility = {"private", "shared"}
        if visibility not in valid_visibility:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"visibility must be one of {sorted(valid_visibility)}, got {visibility!r}",
                }
            )

        importance = max(0.0, min(1.0, importance))

        record = MemoryRecord(
            id=str(uuid4()),
            content=content,
            domain=own_domain,
            visibility=cast(Literal["private", "shared"], visibility),
            importance=importance,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            source="agent",
            created_at=datetime.now(UTC).isoformat(),
        )
        # Let PermissionError propagate so SDK marks tool call as failed.
        # The LLM will see a clear error instead of a JSON string that might be
        # misinterpreted as success.
        record_id = await hub.save(record, agent_name=agent_name)
        return json.dumps({"id": record_id, "status": "saved"})

    async def memory_get(record_id: str) -> str:
        """Retrieve a specific memory by its ID."""
        record = await hub.get(record_id, agent_name=agent_name)
        if record is None:
            return json.dumps({"error": "not found"})
        return json.dumps(record.to_dict())

    async def memory_list(
        domain: str | None = None,
        limit: int = 20,
    ) -> str:
        """List recent memories, optionally filtered by domain."""
        records = await hub.list_memories(
            agent_name=agent_name,
            domain=domain,
            limit=limit,
        )
        return json.dumps([r.to_dict() for r in records])

    async def memory_forget(record_id: str) -> str:
        """Soft-delete a memory by ID. Only works for your own domain's memories."""
        try:
            ok = await hub.forget(record_id, agent_name=agent_name)
            return json.dumps(
                {"status": "forgotten" if ok else "not found"},
            )
        except PermissionError as e:
            return json.dumps({"status": "error", "error": str(e)})

    return [
        MemoryTool(
            "memory_search",
            memory_search,
            "Search memories by query. Returns ranked results.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                    "domain": {"type": "string", "description": "Filter by domain (optional)"},
                },
                "required": ["query"],
            },
        ),
        MemoryTool(
            "memory_save",
            memory_save,
            "Save a new memory. Domain is auto-set. Choose visibility: "
            "private (default, only you) or shared (all agents).",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory text to save"},
                    "visibility": {"type": "string", "enum": ["private", "shared"], "default": "private"},
                    "tags": {"type": "string", "description": "Comma-separated tags", "default": ""},
                    "importance": {"type": "number", "description": "0.0-1.0, >= 0.9 for evergreen", "default": 0.5},
                },
                "required": ["content"],
            },
        ),
        MemoryTool(
            "memory_get",
            memory_get,
            "Retrieve a specific memory by ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "The memory record ID"},
                },
                "required": ["record_id"],
            },
        ),
        MemoryTool(
            "memory_list",
            memory_list,
            "List recent memories, optionally filtered by domain.",
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Filter by domain (optional)"},
                    "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                },
            },
        ),
        MemoryTool(
            "memory_forget",
            memory_forget,
            "Soft-delete a memory by ID. Only works for your own domain.",
            input_schema={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "The memory record ID to forget"},
                },
                "required": ["record_id"],
            },
        ),
    ]
