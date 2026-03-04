"""Memory backend protocol — the contract all backends must satisfy.

Both the primary backend (SQLite FTS5) and overlay backends (Cognee, sqlite-vec,
CORPGEN extraction) implement this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from corvus.memory.record import MemoryRecord


@dataclass
class HealthStatus:
    """Health check result from a backend."""

    name: str
    status: Literal["healthy", "unhealthy"]
    detail: str | None = None


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for pluggable memory backends.

    All methods accept `readable_domains` so visibility filtering
    happens at the storage level (SQL WHERE), not in Python.
    """

    async def save(self, record: MemoryRecord) -> str:
        """Persist a memory record. Returns the record ID."""
        ...

    async def update(self, record: MemoryRecord) -> bool:
        """Update an existing memory record. Returns True when updated."""
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search memories. readable_domains enables SQL-level visibility filtering."""
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        ...

    async def list_memories(
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        ...

    async def forget(self, record_id: str) -> bool:
        """Soft-delete: set deleted_at. Returns True if found and soft-deleted."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check backend health."""
        ...
