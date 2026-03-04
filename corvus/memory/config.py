"""Memory Hub configuration loader + plugin registry for backends."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("corvus.memory.config")

_DEFAULT_PRIMARY_DB = Path(".data/memory/main.sqlite")


@dataclass
class BackendConfig:
    """Configuration for a single overlay backend."""

    name: str
    enabled: bool = False
    weight: float = 0.3
    settings: dict = field(default_factory=dict)


@dataclass
class MemoryConfig:
    """Configuration for the MemoryHub."""

    primary_db_path: Path
    overlays: list[BackendConfig] = field(default_factory=list)
    decay_half_life_days: float = 30.0
    evergreen_threshold: float = 0.9
    mmr_lambda: float = 0.7
    audit_enabled: bool = True

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        default_db_path: Path | None = None,
        strict: bool = False,
    ) -> MemoryConfig:
        """Load memory config from YAML with safe fallback behavior."""
        fallback_db = Path(default_db_path) if default_db_path else _DEFAULT_PRIMARY_DB
        if not path.exists():
            logger.info("Memory config not found at %s; using defaults", path)
            return cls(primary_db_path=fallback_db)

        try:
            raw = yaml.safe_load(path.read_text())
            if raw is None:
                raw = {}
            if not isinstance(raw, dict):
                raise ValueError(f"Expected YAML mapping in {path}, got {type(raw).__name__}")

            primary_db_path = _parse_primary_db_path(raw.get("primary_db_path"), config_path=path, fallback=fallback_db)
            overlays = _parse_overlays(raw.get("overlays", []))
            decay_half_life_days = _as_float(raw.get("decay_half_life_days", 30.0), "decay_half_life_days")
            evergreen_threshold = _as_float(raw.get("evergreen_threshold", 0.9), "evergreen_threshold")
            mmr_lambda = _as_float(raw.get("mmr_lambda", 0.7), "mmr_lambda")
            audit_enabled = _as_bool(raw.get("audit_enabled", True), "audit_enabled")

            logger.info("Loaded memory config from %s", path)
            return cls(
                primary_db_path=primary_db_path,
                overlays=overlays,
                decay_half_life_days=decay_half_life_days,
                evergreen_threshold=evergreen_threshold,
                mmr_lambda=mmr_lambda,
                audit_enabled=audit_enabled,
            )
        except Exception:
            if strict:
                raise
            logger.exception("Failed to load memory config from %s; using defaults", path)
            return cls(primary_db_path=fallback_db)

    def enabled_overlays(self) -> list[BackendConfig]:
        """Return overlays that are enabled."""
        return [overlay for overlay in self.overlays if overlay.enabled]


def _parse_primary_db_path(raw: object, *, config_path: Path, fallback: Path) -> Path:
    if raw is None:
        return fallback
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("primary_db_path must be a non-empty string")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = (config_path.parent / candidate).resolve()
    return candidate


def _parse_overlays(raw: object) -> list[BackendConfig]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("overlays must be a list")

    overlays: list[BackendConfig] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"overlays[{idx}] must be a mapping")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"overlays[{idx}].name must be a non-empty string")

        enabled = _as_bool(item.get("enabled", False), f"overlays[{idx}].enabled")
        weight = _as_float(item.get("weight", 0.3), f"overlays[{idx}].weight")

        settings = item.get("settings", {})
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise ValueError(f"overlays[{idx}].settings must be a mapping")

        overlays.append(
            BackendConfig(
                name=name.strip(),
                enabled=enabled,
                weight=weight,
                settings=dict(settings),
            )
        )
    return overlays


def _as_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean")


def _as_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"{field_name} must be numeric")
