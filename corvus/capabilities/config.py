"""Capabilities config loader for module registry wiring."""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CapabilityModuleConfig:
    """Config for one capability module."""

    enabled: bool = True


@dataclass
class CapabilitiesConfig:
    """Capabilities module enable/disable config."""

    modules: dict[str, CapabilityModuleConfig] = field(default_factory=dict)

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        available_modules: list[str] | None = None,
        strict: bool = False,
    ) -> CapabilitiesConfig:
        """Load capabilities config from YAML.

        Fallback behavior (strict=False):
        - missing file -> default config (all available modules enabled)
        - parse/shape error -> default config
        """
        if not path.exists():
            logger.info("capabilities_config_not_found", path=str(path))
            return cls()

        try:
            raw = yaml.safe_load(path.read_text())
            if raw is None:
                raw = {}
            if not isinstance(raw, dict):
                raise ValueError(f"Expected YAML mapping in {path}, got {type(raw).__name__}")

            raw_modules = raw.get("modules", {})
            if raw_modules is None:
                raw_modules = {}
            if not isinstance(raw_modules, dict):
                raise ValueError("'modules' must be a mapping")

            modules: dict[str, CapabilityModuleConfig] = {}
            for name, module_cfg in raw_modules.items():
                if not isinstance(module_cfg, dict):
                    raise ValueError(f"modules.{name} must be a mapping")
                enabled = module_cfg.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise ValueError(f"modules.{name}.enabled must be a boolean")
                modules[name] = CapabilityModuleConfig(enabled=enabled)

            if available_modules:
                known = set(available_modules)
                unknown = sorted(set(modules) - known)
                for module_name in unknown:
                    logger.warning("unknown_capability_module", module=module_name)

            logger.info("capabilities_config_loaded", path=str(path))
            return cls(modules=modules)
        except Exception:
            if strict:
                raise
            logger.exception("capabilities_config_load_failed", path=str(path))
            return cls()

    def enabled_modules(self, available_modules: list[str]) -> list[str]:
        """Return enabled module names in the given canonical module order."""
        enabled: list[str] = []
        for module_name in available_modules:
            cfg = self.modules.get(module_name)
            if cfg is None or cfg.enabled:
                enabled.append(module_name)
        return enabled
