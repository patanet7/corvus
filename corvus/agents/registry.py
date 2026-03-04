"""AgentRegistry — load, validate, CRUD, and hot-reload for agent specs.

Reads AgentSpec YAML files from a config directory, validates them against
a fixed rule set, and provides a dict-backed registry with full CRUD:

    registry = AgentRegistry(Path("config/agents"))
    registry.load()                      # bulk-load all *.yaml
    registry.get("homelab")              # lookup by name
    registry.list_enabled()              # only enabled agents
    registry.create(spec)                # validate + persist + register
    registry.update("homelab", patch)    # partial update
    registry.deactivate("homelab")       # set enabled=false
    result = registry.reload()           # diff disk vs in-memory

All file I/O uses real filesystem operations (no mocks, no fakes).
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from corvus.agents.spec import AgentSpec

logger = logging.getLogger("corvus-gateway")

VALID_COMPLEXITY = {"high", "medium", "low"}
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge *patch* into *base*, modifying *base* in-place.

    For nested dicts, values are merged recursively instead of replaced.
    Non-dict values in *patch* always overwrite the corresponding key in *base*.
    """
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@dataclass
class ReloadResult:
    """Result of a reload() call, reporting what changed on disk."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{self.added}")
        if self.removed:
            parts.append(f"-{self.removed}")
        if self.changed:
            parts.append(f"~{self.changed}")
        if self.errors:
            parts.append(f"errors={list(self.errors)}")
        return f"ReloadResult({', '.join(parts) or 'no changes'})"


class AgentRegistry:
    """Config-driven agent registry with YAML persistence.

    Loads AgentSpec definitions from ``config_dir/*.yaml``, validates them,
    and provides a full CRUD interface.  All mutations are persisted back
    to YAML so a fresh ``load()`` will pick them up.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._specs: dict[str, AgentSpec] = {}
        self._file_contents: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load all *.yaml specs from config_dir, skipping invalid ones."""
        self._specs.clear()
        self._file_contents.clear()
        if not self._config_dir.exists():
            logger.warning("Config dir %s does not exist — no agents loaded", self._config_dir)
            return
        for yaml_file in sorted(self._config_dir.glob("*.yaml")):
            self._load_one(yaml_file)

    def _load_one(self, path: Path) -> bool:
        """Load a single YAML file. Returns True on success, False on skip."""
        try:
            spec = AgentSpec.from_yaml(path)
        except (yaml.YAMLError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse %s: %s", path.name, exc)
            return False
        errors = self.validate(spec)
        if errors:
            logger.warning("Invalid spec %s: %s", path.name, "; ".join(errors))
            return False
        self._specs[spec.name] = spec
        self._file_contents[spec.name] = path.read_text()
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> AgentSpec | None:
        """Return the spec for *name*, or ``None`` if not registered."""
        return self._specs.get(name)

    def list_enabled(self) -> list[AgentSpec]:
        """Return all specs where ``enabled`` is True."""
        return [s for s in self._specs.values() if s.enabled]

    def list_all(self) -> list[AgentSpec]:
        """Return all registered specs (enabled and disabled)."""
        return list(self._specs.values())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, spec: AgentSpec) -> list[str]:
        """Validate *spec* against the fixed rule set.

        Returns a list of human-readable error messages.  An empty list
        means the spec is valid.
        """
        errors: list[str] = []

        if not spec.name or not spec.name.strip():
            errors.append("name must be non-empty and non-whitespace")
        elif not _SAFE_NAME_RE.match(spec.name):
            errors.append(f"name must be alphanumeric (plus hyphens/underscores), got {spec.name!r}")

        if not spec.description or not spec.description.strip():
            errors.append("description must be non-empty and non-whitespace")

        if spec.models.complexity not in VALID_COMPLEXITY:
            errors.append(f"complexity must be one of {sorted(VALID_COMPLEXITY)}, got {spec.models.complexity!r}")

        if spec.memory is not None:
            if not spec.memory.own_domain or not spec.memory.own_domain.strip():
                errors.append("memory.own_domain must be non-empty when memory config is present")

        return errors

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, spec: AgentSpec) -> None:
        """Validate, persist to YAML, and register a new agent spec.

        Raises ``ValueError`` if the spec fails validation or if an agent
        with the same name already exists.
        """
        errors = self.validate(spec)
        if errors:
            raise ValueError(f"Agent spec validation failed: {'; '.join(errors)}")
        if spec.name in self._specs:
            raise ValueError(f"Agent {spec.name!r} already exists")
        self._persist(spec)
        self._specs[spec.name] = spec
        self._file_contents[spec.name] = self._yaml_path(spec.name).read_text()

    def update(self, name: str, patch: dict) -> AgentSpec:
        """Apply a partial *patch* to the agent named *name*.

        Uses deep merge for nested dicts (tools, models, memory, metadata)
        so patching ``{"tools": {"builtin": ["Read"]}}`` doesn't wipe
        out ``confirm_gated`` or ``modules``.

        Raises ``KeyError`` if the agent is not found.
        Raises ``ValueError`` if the patched spec fails validation.
        """
        if name not in self._specs:
            raise KeyError(f"Agent {name!r} not found")

        patch_name = patch.get("name")
        if patch_name and patch_name != name:
            raise ValueError(f"Cannot rename agent via update() — got name={patch_name!r} but agent is {name!r}")

        existing = self._specs[name]
        merged = existing.to_dict()
        _deep_merge(merged, patch)
        updated = AgentSpec.from_dict(merged)

        errors = self.validate(updated)
        if errors:
            raise ValueError(f"Agent spec validation failed after patch: {'; '.join(errors)}")

        self._persist(updated)
        self._specs[name] = updated
        self._file_contents[name] = self._yaml_path(name).read_text()
        return updated

    def deactivate(self, name: str) -> None:
        """Set ``enabled=False`` for the agent named *name* and persist.

        Raises ``KeyError`` if the agent is not found.
        """
        if name not in self._specs:
            raise KeyError(f"Agent {name!r} not found")
        spec = self._specs[name]
        spec.enabled = False
        self._persist(spec)
        self._file_contents[name] = self._yaml_path(name).read_text()

    # ------------------------------------------------------------------
    # Reload (hot-reload with diff)
    # ------------------------------------------------------------------

    def reload(self) -> ReloadResult:
        """Re-read config_dir and diff against in-memory state.

        Returns a ``ReloadResult`` describing what was added, removed,
        changed, or errored since the last load/reload.
        """
        result = ReloadResult()

        if not self._config_dir.exists():
            # Everything currently loaded counts as removed
            result.removed = list(self._specs.keys())
            self._specs.clear()
            self._file_contents.clear()
            return result

        # Build a map of what is on disk now
        disk_specs: dict[str, AgentSpec] = {}
        disk_contents: dict[str, str] = {}
        for yaml_file in sorted(self._config_dir.glob("*.yaml")):
            try:
                spec = AgentSpec.from_yaml(yaml_file)
            except Exception as exc:
                stem = yaml_file.stem
                result.errors[stem] = str(exc)
                logger.warning("Reload: failed to parse %s: %s", yaml_file.name, exc)
                continue
            errors = self.validate(spec)
            if errors:
                stem = yaml_file.stem
                result.errors[stem] = "; ".join(errors)
                logger.warning("Reload: invalid spec %s: %s", yaml_file.name, "; ".join(errors))
                continue
            disk_specs[spec.name] = spec
            disk_contents[spec.name] = yaml_file.read_text()

        # Compute diff
        old_names = set(self._specs.keys())
        new_names = set(disk_specs.keys())

        result.added = sorted(new_names - old_names)
        result.removed = sorted(old_names - new_names)

        for name in old_names & new_names:
            if self._file_contents.get(name) != disk_contents.get(name):
                result.changed.append(name)
        result.changed.sort()

        # Apply
        self._specs = disk_specs
        self._file_contents = disk_contents

        return result

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist(self, spec: AgentSpec) -> None:
        """Write *spec* to ``config_dir/{name}.yaml``."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        path = self._yaml_path(spec.name)
        with open(path, "w") as f:
            yaml.dump(spec.to_dict(), f, default_flow_style=False, sort_keys=False)

    def _yaml_path(self, name: str) -> Path:
        """Return the YAML file path for an agent named *name*."""
        return self._config_dir / f"{name}.yaml"
