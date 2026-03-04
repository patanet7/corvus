"""Unified memory record dataclass.

Replaces both MemoryResult (memory_backends.py) and SearchResult (memory_engine.py)
with a single data model used across all layers of the memory system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EVERGREEN_THRESHOLD = 0.9

VALID_VISIBILITY = ("private", "shared")


@dataclass
class MemoryRecord:
    """A single memory record flowing through the Hub.

    Fields set by the system (not agent-controllable):
        id, domain, source, created_at, updated_at, deleted_at, score

    Fields set by the agent:
        content, visibility, importance, tags

    Fields set by search:
        score (populated on retrieval, 0.0 otherwise)
    """

    id: str
    content: str
    domain: str = "shared"
    visibility: Literal["private", "shared"] = "private"
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    source: str = "agent"
    created_at: str = ""
    updated_at: str | None = None
    deleted_at: str | None = None
    score: float = 0.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.visibility not in VALID_VISIBILITY:
            msg = f"visibility must be one of {VALID_VISIBILITY}, got {self.visibility!r}"
            raise ValueError(msg)

    @property
    def is_evergreen(self) -> bool:
        """Evergreen memories are exempt from temporal decay."""
        return self.importance >= EVERGREEN_THRESHOLD

    @property
    def is_deleted(self) -> bool:
        """Soft-deleted records have a non-None deleted_at."""
        return self.deleted_at is not None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": self.id,
            "content": self.content,
            "domain": self.domain,
            "visibility": self.visibility,
            "importance": self.importance,
            "tags": list(self.tags),
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "score": self.score,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryRecord:
        """Deserialize from a dict, ignoring unknown keys.

        Raises ValueError if required fields (id, content) are missing.
        """
        required = {"id", "content"}
        missing = required - data.keys()
        if missing:
            msg = f"Missing required fields: {', '.join(sorted(missing))}"
            raise ValueError(msg)
        known = {
            "id",
            "content",
            "domain",
            "visibility",
            "importance",
            "tags",
            "source",
            "created_at",
            "updated_at",
            "deleted_at",
            "score",
            "metadata",
        }
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
