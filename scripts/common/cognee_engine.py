"""Cognee knowledge graph engine — graph-backed memory recall.

Uses Cognee with SQLite graph storage + LanceDB vector storage.
Per-domain dataset isolation for memory boundaries.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from corvus.ollama_probe import resolve_ollama_url

logger = logging.getLogger(__name__)


@dataclass
class GraphResult:
    """A single result from the Cognee knowledge graph."""

    content: str
    file_path: str
    score: float
    created_at: str
    relationships: list[str] = field(default_factory=list)


class CogneeEngine:
    """Knowledge graph search engine using Cognee.

    Provides graph-based memory recall that finds related memories through
    entity and relationship traversal — even when keywords and vectors
    don't match. Degrades gracefully when cognee is not installed.
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir or os.environ.get("COGNEE_DATA_DIR", "/data/cognee"))
        self._initialized = False

    def _ensure_init(self) -> None:
        """Lazy initialization of Cognee storage backends."""
        if self._initialized:
            return
        try:
            import cognee

            # Set env vars BEFORE calling cognee.config()
            os.environ.setdefault("COGNEE_DB_PROVIDER", "sqlite")
            os.environ.setdefault("COGNEE_VECTOR_DB_PROVIDER", "lancedb")
            os.environ.setdefault("COGNEE_DB_PATH", str(self.data_dir / "cognee.db"))
            os.environ.setdefault("COGNEE_VECTOR_DB_PATH", str(self.data_dir / "lancedb"))

            # Explicitly configure Cognee LLM + storage backends.
            # Reads provider/model/endpoint from env vars so deployment can
            # choose Anthropic, Ollama, or any OpenAI-compatible backend.
            try:
                llm_cfg: dict[str, str] = {}
                llm_provider = os.environ.get("COGNEE_LLM_PROVIDER")
                if llm_provider:
                    llm_cfg["llm_provider"] = llm_provider
                llm_model = os.environ.get("COGNEE_LLM_MODEL")
                if llm_model:
                    llm_cfg["llm_model"] = llm_model
                endpoint = os.environ.get("COGNEE_LLM_ENDPOINT")
                # For Ollama: resolve the best reachable URL with fallback
                if llm_provider == "ollama" and not endpoint:
                    _OLLAMA_URLS = [
                        "http://localhost:11434",
                        "http://localhost:11434",
                    ]
                    endpoint = resolve_ollama_url(_OLLAMA_URLS)
                if endpoint:
                    llm_cfg["llm_endpoint"] = endpoint
                # LiteLLM requires a non-empty API key even for Ollama
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
                # cognee.config API may vary by version -- fall back to env vars only
                logger.debug("cognee.config API not available, using env vars only")

            self._initialized = True
        except ImportError:
            pass

    @property
    def is_available(self) -> bool:
        """Check whether the cognee package is importable."""
        try:
            import cognee  # noqa: F401

            return True
        except ImportError:
            return False

    async def index(
        self,
        content: str,
        domain: str,
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Index content into the knowledge graph for a specific domain.

        Returns the number of items indexed (0 if cognee is unavailable).
        """
        if not self.is_available:
            return 0
        self._ensure_init()
        import cognee

        await cognee.add([content], dataset_name=domain)
        await cognee.cognify(dataset_name=domain)
        return 1

    async def search(
        self,
        query: str,
        domain: str | None = None,
        limit: int = 10,
    ) -> list[GraphResult]:
        """Search the knowledge graph.

        Returns related memories with relationship info, or an empty list
        if cognee is unavailable or an error occurs.
        """
        if not self.is_available:
            return []
        self._ensure_init()
        import cognee

        try:
            results = await cognee.search(query, dataset_name=domain)
            graph_results: list[GraphResult] = []
            for r in results[:limit]:
                graph_results.append(
                    GraphResult(
                        content=str(r.get("text", r.get("content", ""))),
                        file_path=str(r.get("source", "")),
                        score=float(r.get("score", 0.5)),
                        created_at=str(r.get("created_at", "")),
                        relationships=[str(rel) for rel in r.get("relationships", [])],
                    )
                )
            return graph_results
        except Exception:
            return []
