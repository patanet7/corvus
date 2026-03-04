"""MemoryHub — central coordinator for the memory system.

Handles:
- Write enforcement (domain ownership check)
- Write fan-out to primary + overlays
- Search merge across backends
- Temporal decay (exponential, with evergreen exemption)
- Audit trail
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from corvus.memory.backends.fts5 import FTS5Backend
from corvus.memory.backends.protocol import HealthStatus, MemoryBackend
from corvus.memory.config import MemoryConfig
from corvus.memory.record import MemoryRecord


@runtime_checkable
class MemoryAccessResolver(Protocol):
    """Protocol for functions that resolve memory access for an agent."""

    def __call__(self, agent_name: str) -> dict[str, Any]: ...


logger = logging.getLogger(__name__)


def _safe_memory_access(agent_name: str) -> dict[str, Any]:
    """Safe default: shared domain, read-only, no cross-domain access."""
    return {
        "own_domain": "shared",
        "can_read_shared": True,
        "can_write": False,
        "readable_domains": None,
    }


def _safe_readable_domains(agent_name: str) -> list[str]:
    """Safe default: own domain only."""
    return ["shared"]


class MemoryHub:
    """Central memory coordinator.

    Primary + Overlay architecture:
    - Primary (FTS5): always on, source of truth
    - Overlays: optional, fan-out writes, merge search results
    """

    def __init__(
        self,
        config: MemoryConfig,
        overlays: list[MemoryBackend] | None = None,
        get_memory_access_fn: MemoryAccessResolver | None = None,
        get_readable_domains_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.config = config
        self.primary = FTS5Backend(db_path=config.primary_db_path)
        self.overlays: list[MemoryBackend] = overlays or []
        self._get_memory_access = get_memory_access_fn or _safe_memory_access
        self._get_readable_domains = get_readable_domains_fn or _safe_readable_domains
        self._resolvers_set = get_memory_access_fn is not None
        self._overlay_failures: dict[int, int] = {}  # id(overlay) -> consecutive failures

    def set_resolvers(
        self,
        get_memory_access_fn: MemoryAccessResolver,
        get_readable_domains_fn: Callable[[str], list[str]],
    ) -> None:
        """Replace the memory-access and readable-domain resolver functions.

        Used by AgentsHub two-phase init to rewire resolvers from hardcoded
        agent_config to spec-based lookups without breaking encapsulation.
        """
        self._get_memory_access = get_memory_access_fn
        self._get_readable_domains = get_readable_domains_fn
        self._resolvers_set = True

    def get_memory_access(self, agent_name: str) -> dict[str, Any]:
        """Return the memory access config for an agent.

        Public accessor for the resolver — used by toolkit to derive
        own_domain when not explicitly provided.
        """
        return self._get_memory_access(agent_name)

    def validate_ready(self) -> list[str]:
        """Validate that the hub is properly configured. Returns error list.

        An empty list means the hub is ready. Used by startup validation
        to catch init sequencing bugs.
        """
        errors: list[str] = []
        if not self._resolvers_set:
            errors.append("MemoryHub resolvers not set — set_resolvers() was never called")
        if self.config.primary_db_path is None:
            errors.append("MemoryHub primary_db_path is None")
        return errors

    async def save(
        self,
        record: MemoryRecord,
        *,
        agent_name: str,
    ) -> str:
        """Save a memory record with write enforcement.

        Raises PermissionError if agent tries to write cross-domain.
        """
        access = self._get_memory_access(agent_name)

        # Unknown agents cannot write
        if not access.get("can_write", False):
            msg = f"Agent '{agent_name}' does not have write permission"
            raise PermissionError(msg)

        # Domain ownership check
        own_domain = access["own_domain"]
        if record.domain != own_domain and record.domain != "shared":
            msg = f"Agent '{agent_name}' owns domain '{own_domain}' but tried to write to domain '{record.domain}'"
            raise PermissionError(msg)

        # Save to primary (must succeed)
        record_id = await self.primary.save(record)

        # Fan out to overlays (best-effort with failure tracking)
        for overlay in self.overlays:
            try:
                await overlay.save(record)
                self._overlay_failures.pop(id(overlay), None)
            except Exception:
                count = self._overlay_failures.get(id(overlay), 0) + 1
                self._overlay_failures[id(overlay)] = count
                logger.warning(
                    "Overlay save failed for record %s (consecutive failures: %d)",
                    record.id,
                    count,
                    exc_info=True,
                )

        # Audit
        self._audit(agent_name, "save", record.id, record.domain, record.visibility)

        return record_id

    async def update(
        self,
        record_id: str,
        *,
        agent_name: str,
        content: str | None = None,
        visibility: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord | None:
        """Update a memory record with write enforcement."""
        existing = await self.primary.get(record_id)
        if existing is None:
            return None

        access = self._get_memory_access(agent_name)
        if not access.get("can_write", False):
            msg = f"Agent '{agent_name}' does not have write permission"
            raise PermissionError(msg)

        own_domain = access["own_domain"]
        if existing.domain != own_domain and existing.domain != "shared":
            msg = f"Agent '{agent_name}' cannot update records in domain '{existing.domain}'"
            raise PermissionError(msg)

        now = datetime.now(UTC).isoformat()
        updated = MemoryRecord(
            id=existing.id,
            content=content if content is not None else existing.content,
            domain=existing.domain,
            visibility=visibility if visibility is not None else existing.visibility,
            importance=importance if importance is not None else existing.importance,
            tags=list(tags) if tags is not None else list(existing.tags),
            source=existing.source,
            created_at=existing.created_at,
            updated_at=now,
            deleted_at=existing.deleted_at,
            metadata=dict(metadata) if metadata is not None else dict(existing.metadata),
        )

        ok = await self.primary.update(updated)
        if not ok:
            return None

        for overlay in self.overlays:
            try:
                await overlay.update(updated)
                self._overlay_failures.pop(id(overlay), None)
            except Exception:
                count = self._overlay_failures.get(id(overlay), 0) + 1
                self._overlay_failures[id(overlay)] = count
                logger.warning(
                    "Overlay update failed for %s (consecutive failures: %d)",
                    record_id,
                    count,
                    exc_info=True,
                )

        self._audit(agent_name, "update", record_id, updated.domain, updated.visibility)
        return updated

    async def search(
        self,
        query: str,
        *,
        agent_name: str,
        limit: int = 10,
        domain: str | None = None,
    ) -> list[MemoryRecord]:
        """Search with visibility filtering, temporal decay, and result merge."""
        readable = self._get_readable_domains(agent_name)

        # Collect from primary
        results = await self.primary.search(
            query,
            limit=limit * 2,
            domain=domain,
            readable_domains=readable,
        )

        # Collect from overlays and merge
        for overlay in self.overlays:
            try:
                overlay_results = await overlay.search(
                    query,
                    limit=limit * 2,
                    domain=domain,
                    readable_domains=readable,
                )
                results = self._merge_results(results, overlay_results)
                self._overlay_failures.pop(id(overlay), None)
            except Exception:
                count = self._overlay_failures.get(id(overlay), 0) + 1
                self._overlay_failures[id(overlay)] = count
                logger.warning(
                    "Overlay search failed (consecutive failures: %d)",
                    count,
                    exc_info=True,
                )

        # Apply temporal decay
        results = self._apply_temporal_decay(results)

        # TODO: MMR diversity re-ranking (config.mmr_lambda) — deferred to follow-up

        # Sort by final score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def get(
        self,
        record_id: str,
        *,
        agent_name: str,
    ) -> MemoryRecord | None:
        """Get a record by ID with visibility enforcement."""
        record = await self.primary.get(record_id)
        if record is None:
            return None

        # Visibility check
        if record.visibility == "private":
            readable = self._get_readable_domains(agent_name)
            if record.domain not in readable:
                raise PermissionError(f"Agent '{agent_name}' does not have access to domain '{record.domain}'")

        return record

    async def list_memories(
        self,
        *,
        agent_name: str,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memories with visibility filtering."""
        readable = self._get_readable_domains(agent_name)
        return await self.primary.list_memories(
            domain=domain,
            limit=limit,
            offset=offset,
            readable_domains=readable,
        )

    async def forget(
        self,
        record_id: str,
        *,
        agent_name: str,
    ) -> bool:
        """Soft-delete a memory. Only domain owner can forget."""
        record = await self.primary.get(record_id)
        if record is None:
            return False

        # Permission check: only domain owner can forget
        access = self._get_memory_access(agent_name)
        own_domain = access["own_domain"]
        if record.domain != own_domain and record.domain != "shared":
            msg = f"Agent '{agent_name}' cannot forget records in domain '{record.domain}'"
            raise PermissionError(msg)

        ok = await self.primary.forget(record_id)

        # Fan out to overlays
        for overlay in self.overlays:
            try:
                await overlay.forget(record_id)
                self._overlay_failures.pop(id(overlay), None)
            except Exception:
                count = self._overlay_failures.get(id(overlay), 0) + 1
                self._overlay_failures[id(overlay)] = count
                logger.warning(
                    "Overlay forget failed for %s (consecutive failures: %d)",
                    record_id,
                    count,
                    exc_info=True,
                )

        if ok:
            self._audit(
                agent_name,
                "forget",
                record_id,
                record.domain,
                record.visibility,
            )

        return ok

    def _merge_results(
        self,
        primary: list[MemoryRecord],
        overlay: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        """Merge results from primary and overlay. Dedup by ID, keep highest score."""
        by_id: dict[str, MemoryRecord] = {}
        for r in primary:
            by_id[r.id] = r
        for r in overlay:
            if r.id in by_id:
                if r.score > by_id[r.id].score:
                    by_id[r.id] = r
            else:
                by_id[r.id] = r
        return list(by_id.values())

    def _apply_temporal_decay(
        self,
        results: list[MemoryRecord],
    ) -> list[MemoryRecord]:
        """Apply exponential temporal decay. Evergreen records are exempt.

        Uses config.evergreen_threshold as the single source of truth
        for the evergreen cutoff (not record.is_evergreen).
        """
        half_life = self.config.decay_half_life_days
        threshold = self.config.evergreen_threshold
        lam = math.log(2) / half_life
        now = datetime.now(UTC)

        for r in results:
            if r.importance >= threshold:
                continue
            try:
                created = datetime.fromisoformat(r.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = (now - created).total_seconds() / 86400
                if age_days > 0:
                    r.score *= math.exp(-lam * age_days)
            except (ValueError, TypeError):
                logger.debug("Skipping decay for record %s: bad created_at=%r", r.id, r.created_at)

        return results

    def seed_context(
        self,
        agent_name: str,
        *,
        limit: int = 15,
    ) -> list[MemoryRecord]:
        """Synchronously fetch recent + evergreen memories for prompt seeding.

        Returns up to ``limit`` records the agent can read, ordered by
        importance (evergreen first) then recency.  Uses the sync path
        on the primary backend — safe to call from non-async prompt
        composition.
        """
        readable = self._get_readable_domains(agent_name)
        try:
            records = self.primary._list_sync(
                domain=None,
                limit=limit * 2,
                offset=0,
                readable_domains=readable,
            )
        except Exception:
            logger.warning("seed_context failed for %s", agent_name, exc_info=True)
            return []

        # Apply temporal decay to sort by relevance
        records = self._apply_temporal_decay(records)

        # Evergreen first, then by score
        records.sort(key=lambda r: (r.importance >= self.config.evergreen_threshold, r.score), reverse=True)
        return records[:limit]

    async def backend_status(self) -> dict[str, Any]:
        """Return health + configuration status for primary and overlay backends."""
        primary_health = await self.primary.health_check()
        overlay_statuses: list[dict[str, Any]] = []

        for overlay in self.overlays:
            name = overlay.__class__.__name__
            try:
                health = await overlay.health_check()
            except Exception as exc:
                health = HealthStatus(name=name, status="unhealthy", detail=str(exc))
            overlay_statuses.append(
                {
                    "name": health.name,
                    "status": health.status,
                    "detail": health.detail,
                    "consecutive_failures": self._overlay_failures.get(id(overlay), 0),
                }
            )

        configured_overlays = [
            {
                "name": cfg.name,
                "enabled": cfg.enabled,
                "weight": cfg.weight,
                "settings": dict(cfg.settings),
            }
            for cfg in self.config.overlays
        ]

        return {
            "primary": {
                "name": primary_health.name,
                "status": primary_health.status,
                "detail": primary_health.detail,
            },
            "overlays": overlay_statuses,
            "configured_overlays": configured_overlays,
        }

    def _audit(
        self,
        agent_name: str,
        operation: str,
        record_id: str | None,
        domain: str | None,
        visibility: str | None,
    ) -> None:
        """Write an audit event via the primary backend (uses WAL)."""
        if not self.config.audit_enabled:
            return
        try:
            self.primary.write_audit(
                agent_name,
                operation,
                record_id,
                domain,
                visibility,
            )
        except Exception:
            logger.error("Audit write failed", exc_info=True)
