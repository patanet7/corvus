"""Cognee overlay backend for MemoryHub.

This backend is optional and degrades gracefully when the `cognee` package
is unavailable. It is intended as a search/index overlay, not source-of-truth
storage (FTS5 remains primary).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from corvus.memory.backends.protocol import HealthStatus
from corvus.memory.record import MemoryRecord
import structlog
from corvus.ollama_probe import resolve_ollama_url

logger = structlog.get_logger(__name__)

_RECORD_ID_PREFIX = "__corvus_record_id__:"
_DEFAULT_OLLAMA_URLS = [
    "http://localhost:11434",
    "http://localhost:11434",
]


class CogneeBackend:
    """Overlay backend using Cognee knowledge graph recall."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        weight: float = 0.3,
    ) -> None:
        self.data_dir = Path(data_dir or os.environ.get("COGNEE_DATA_DIR", "/data/cognee"))
        self.weight = max(0.0, float(weight))
        self._initialized = False

    @property
    def is_available(self) -> bool:
        """Whether the cognee package is importable."""
        try:
            import cognee  # noqa: F401
        except ImportError:
            return False
        return True

    def _configure(self) -> None:
        """Initialize Cognee process config once."""
        if self._initialized:
            return

        import cognee

        os.environ.setdefault("COGNEE_DB_PROVIDER", "sqlite")
        os.environ.setdefault("COGNEE_VECTOR_DB_PROVIDER", "lancedb")
        os.environ.setdefault("COGNEE_DB_PATH", str(self.data_dir / "cognee.db"))
        os.environ.setdefault("COGNEE_VECTOR_DB_PATH", str(self.data_dir / "lancedb"))

        try:
            llm_cfg: dict[str, str] = {}
            llm_provider = os.environ.get("COGNEE_LLM_PROVIDER")
            if llm_provider:
                llm_cfg["llm_provider"] = llm_provider
            llm_model = os.environ.get("COGNEE_LLM_MODEL")
            if llm_model:
                llm_cfg["llm_model"] = llm_model
            endpoint = os.environ.get("COGNEE_LLM_ENDPOINT")
            if llm_provider == "ollama" and not endpoint:
                endpoint = resolve_ollama_url(_DEFAULT_OLLAMA_URLS)
            if endpoint:
                llm_cfg["llm_endpoint"] = endpoint
            if llm_provider == "ollama":
                llm_cfg["llm_api_key"] = "ollama"
            if llm_cfg:
                cognee.config.set_llm_config(llm_cfg)
            cognee.config.set_vector_db_config(
                {
                    "vector_db_provider": "lancedb",
                    "vector_db_url": str(self.data_dir / "lancedb"),
                }
            )
            cognee.config.set_relational_db_config(
                {
                    "db_provider": "sqlite",
                    "db_path": str(self.data_dir / "cognee.db"),
                }
            )
        except AttributeError:
            logger.debug("cognee_config_api_unavailable")

        self._initialized = True

    async def save(self, record: MemoryRecord) -> str:
        """Index a record into Cognee by domain dataset (best effort)."""
        if not self.is_available:
            return record.id

        import cognee

        self._configure()
        dataset = _dataset_name(record.domain)
        payload = f"{_RECORD_ID_PREFIX}{record.id}\n{record.content}"
        await cognee.add([payload], dataset_name=dataset)
        await cognee.cognify(dataset_name=dataset)
        return record.id

    async def update(self, record: MemoryRecord) -> bool:
        """Best-effort update by re-indexing latest content."""
        if not self.is_available:
            return False
        await self.save(record)
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search Cognee datasets and convert results to MemoryRecord."""
        if not self.is_available:
            return []

        import cognee

        self._configure()
        datasets = _resolve_datasets(domain=domain, readable_domains=readable_domains)
        if not datasets:
            return []

        merged: dict[str, MemoryRecord] = {}
        for dataset in datasets:
            try:
                raw_results = await cognee.search(query, dataset_name=dataset)
            except TypeError:
                raw_results = await cognee.search(query)
            for item in list(raw_results or [])[:limit]:
                record = _to_memory_record(item=item, dataset=dataset, weight=self.weight)
                existing = merged.get(record.id)
                if existing is None or record.score > existing.score:
                    merged[record.id] = record

        results = sorted(merged.values(), key=lambda record: record.score, reverse=True)
        return results[:limit]

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Overlay backend does not support direct record lookup by ID."""
        del record_id
        return None

    async def list_memories(
        self,
        *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Overlay backend does not support list pagination."""
        del domain, limit, offset, readable_domains
        return []

    async def forget(self, record_id: str) -> bool:
        """Overlay backend currently has no deterministic per-record delete."""
        del record_id
        return False

    async def health_check(self) -> HealthStatus:
        """Report package availability + initialization readiness."""
        if not self.is_available:
            return HealthStatus(
                name="cognee-overlay",
                status="unhealthy",
                detail="cognee package not installed",
            )
        try:
            self._configure()
        except Exception as exc:
            return HealthStatus(name="cognee-overlay", status="unhealthy", detail=str(exc))
        return HealthStatus(name="cognee-overlay", status="healthy")


def _dataset_name(domain: str) -> str:
    normalized = (domain or "shared").strip()
    return normalized if normalized else "shared"


def _resolve_datasets(
    *,
    domain: str | None,
    readable_domains: list[str] | None,
) -> list[str]:
    if domain:
        if readable_domains is not None and domain not in readable_domains:
            return []
        return [_dataset_name(domain)]
    if readable_domains is None:
        return ["shared"]

    seen: set[str] = set()
    datasets: list[str] = []
    for candidate in readable_domains:
        normalized = _dataset_name(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        datasets.append(normalized)
    return datasets


def _to_memory_record(
    *,
    item: Any,
    dataset: str,
    weight: float,
) -> MemoryRecord:
    mapped = _to_mapping(item)
    raw_content = str(mapped.get("text") or mapped.get("content") or "")
    record_id, content = _extract_record_id(raw_content, dataset=dataset)

    raw_score = _as_float(mapped.get("score"), default=0.5)
    score = max(0.0, raw_score) * weight
    created_at = str(mapped.get("created_at") or datetime.now(UTC).isoformat())
    relationships = mapped.get("relationships")

    return MemoryRecord(
        id=record_id,
        content=content,
        domain=dataset,
        visibility="shared" if dataset == "shared" else "private",
        importance=min(1.0, max(0.0, score)),
        source="cognee-overlay",
        created_at=created_at,
        score=score,
        metadata={
            "backend": "cognee",
            "relationships": _as_str_list(relationships),
        },
    )


def _to_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        try:
            converted = item.to_dict()
            if isinstance(converted, dict):
                return converted
        except Exception:
            pass

    mapping: dict[str, Any] = {}
    for key in ("text", "content", "score", "created_at", "relationships"):
        if hasattr(item, key):
            mapping[key] = getattr(item, key)
    if mapping:
        return mapping
    return {"content": str(item)}


def _extract_record_id(raw_content: str, *, dataset: str) -> tuple[str, str]:
    first, sep, rest = raw_content.partition("\n")
    if first.startswith(_RECORD_ID_PREFIX):
        candidate = first[len(_RECORD_ID_PREFIX) :].strip()
        if candidate:
            content = rest if sep else ""
            return candidate, content

    fallback = str(uuid5(NAMESPACE_URL, f"cognee:{dataset}:{raw_content}"))
    return fallback, raw_content


def _as_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
