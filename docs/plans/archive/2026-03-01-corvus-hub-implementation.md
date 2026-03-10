---
title: "Corvus Hub Architecture Implementation Plan"
type: plan
status: implemented
date: 2026-03-01
review_by: 2026-04-09
spec: null
supersedes: null
superseded_by: null
---

# Corvus Hub Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace hardcoded agent wiring with config-driven Agents Hub, security-enforced Capabilities Registry, and complete Memory Hub migration.

**Architecture:** Top-down — AgentSpec YAML is the single source of truth. AgentsHub coordinates spec → tools → memory → SDK options. CapabilitiesRegistry enforces deny-wins tool policy at resolution time. Old MemoryEngine retired in favor of MemoryHub + SessionManager.

**Tech Stack:** Python 3.11+, FastAPI, Claude Agent SDK, SQLite FTS5, PyYAML, pytest (no mocks)

**Design Doc:** `docs/plans/2026-03-01-corvus-hub-architecture-design.md`

---

## Phase 1: Foundation (no behavior change)

### Task 1: AgentSpec Dataclasses

**Files:**
- Create: `corvus/agents/__init__.py`
- Create: `corvus/agents/spec.py`
- Create: `tests/gateway/test_agent_spec.py`

**Step 1: Write the failing tests**

```python
# tests/gateway/test_agent_spec.py
"""Tests for AgentSpec dataclasses — YAML loading, validation, serialization."""

import pytest
from pathlib import Path

from corvus.agents.spec import (
    AgentModelConfig,
    AgentToolConfig,
    AgentMemoryConfig,
    AgentSpec,
)


class TestAgentModelConfig:
    def test_defaults(self):
        cfg = AgentModelConfig()
        assert cfg.preferred is None
        assert cfg.fallback is None
        assert cfg.auto is True
        assert cfg.complexity == "medium"

    def test_custom_values(self):
        cfg = AgentModelConfig(preferred="claude/opus", complexity="high")
        assert cfg.preferred == "claude/opus"
        assert cfg.complexity == "high"


class TestAgentToolConfig:
    def test_defaults(self):
        cfg = AgentToolConfig()
        assert cfg.builtin == []
        assert cfg.modules == {}
        assert cfg.confirm_gated == []

    def test_with_modules(self):
        cfg = AgentToolConfig(
            builtin=["Bash", "Read"],
            modules={
                "obsidian": {"allowed_prefixes": ["personal/"], "read": True, "write": True},
            },
            confirm_gated=["obsidian.write"],
        )
        assert "Bash" in cfg.builtin
        assert cfg.modules["obsidian"]["read"] is True
        assert "obsidian.write" in cfg.confirm_gated


class TestAgentMemoryConfig:
    def test_defaults(self):
        cfg = AgentMemoryConfig(own_domain="personal")
        assert cfg.own_domain == "personal"
        assert cfg.readable_domains is None
        assert cfg.can_read_shared is True
        assert cfg.can_write is True


class TestAgentSpec:
    def test_minimal_spec(self):
        spec = AgentSpec(name="test", description="Test agent")
        assert spec.name == "test"
        assert spec.enabled is True
        assert spec.models.complexity == "medium"
        assert spec.memory is None

    def test_full_spec(self):
        spec = AgentSpec(
            name="personal",
            description="Daily planning and journaling",
            enabled=True,
            models=AgentModelConfig(complexity="medium"),
            prompt_file="prompts/personal.md",
            tools=AgentToolConfig(
                builtin=["Bash", "Read"],
                modules={"obsidian": {"read": True, "write": True}},
                confirm_gated=["obsidian.write"],
            ),
            memory=AgentMemoryConfig(own_domain="personal"),
        )
        assert spec.name == "personal"
        assert spec.tools.builtin == ["Bash", "Read"]
        assert spec.memory.own_domain == "personal"

    def test_prompt_resolution_with_file(self, tmp_path):
        prompt_file = tmp_path / "prompts" / "test.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("# Test Agent\nYou are the test agent.")
        spec = AgentSpec(name="test", description="Test", prompt_file="prompts/test.md")
        result = spec.prompt(config_dir=tmp_path)
        assert "You are the test agent." in result

    def test_prompt_resolution_fallback(self, tmp_path):
        spec = AgentSpec(name="test", description="Test", prompt_file="prompts/missing.md")
        result = spec.prompt(config_dir=tmp_path)
        assert "test" in result.lower()

    def test_prompt_resolution_no_file(self, tmp_path):
        spec = AgentSpec(name="test", description="Test")
        result = spec.prompt(config_dir=tmp_path)
        assert "test" in result.lower()

    def test_to_dict_roundtrip(self):
        spec = AgentSpec(
            name="finance",
            description="Finance agent",
            models=AgentModelConfig(preferred="claude/opus", complexity="high"),
            tools=AgentToolConfig(builtin=["Bash"], modules={"firefly": {"enabled": True}}),
            memory=AgentMemoryConfig(own_domain="finance"),
        )
        data = spec.to_dict()
        restored = AgentSpec.from_dict(data)
        assert restored.name == spec.name
        assert restored.models.preferred == "claude/opus"
        assert restored.models.complexity == "high"
        assert restored.memory.own_domain == "finance"

    def test_from_yaml(self, tmp_path):
        yaml_content = """
name: homelab
description: Server management
enabled: true
models:
  preferred: null
  fallback: null
  auto: true
  complexity: high
prompt_file: prompts/homelab.md
tools:
  builtin:
    - Bash
    - Read
    - Grep
    - Glob
  modules:
    obsidian:
      allowed_prefixes:
        - homelab/
      read: true
      write: true
    memory:
      enabled: true
  confirm_gated:
    - obsidian.write
    - obsidian.append
memory:
  own_domain: homelab
  readable_domains: null
  can_read_shared: true
  can_write: true
"""
        yaml_file = tmp_path / "homelab.yaml"
        yaml_file.write_text(yaml_content)
        spec = AgentSpec.from_yaml(yaml_file)
        assert spec.name == "homelab"
        assert spec.models.complexity == "high"
        assert "Bash" in spec.tools.builtin
        assert spec.tools.modules["obsidian"]["read"] is True
        assert spec.memory.own_domain == "homelab"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_agent_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.agents.spec'`

**Step 3: Create package init**

```python
# corvus/agents/__init__.py
"""Agents Hub — config-driven agent definitions, registry, and lifecycle."""

from corvus.agents.spec import (
    AgentMemoryConfig,
    AgentModelConfig,
    AgentSpec,
    AgentToolConfig,
)

__all__ = [
    "AgentMemoryConfig",
    "AgentModelConfig",
    "AgentSpec",
    "AgentToolConfig",
]
```

**Step 4: Write the implementation**

```python
# corvus/agents/spec.py
"""AgentSpec — single source of truth for agent configuration.

Each agent is defined by one YAML file in config/agents/{name}.yaml.
The spec captures identity, model preferences, tool access, memory domain,
and prompt file location. All other components read from this spec.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentModelConfig:
    """Per-agent model preferences and routing hints."""

    preferred: str | None = None
    fallback: str | None = None
    auto: bool = True
    complexity: str = "medium"  # "high" | "medium" | "low"


@dataclass
class AgentToolConfig:
    """Per-agent tool access configuration."""

    builtin: list[str] = field(default_factory=list)
    modules: dict[str, dict] = field(default_factory=dict)
    confirm_gated: list[str] = field(default_factory=list)


@dataclass
class AgentMemoryConfig:
    """Per-agent memory domain isolation rules."""

    own_domain: str
    readable_domains: list[str] | None = None
    can_read_shared: bool = True
    can_write: bool = True


@dataclass
class AgentSpec:
    """Complete agent definition — the single source of truth.

    Loaded from config/agents/{name}.yaml by AgentRegistry.
    """

    name: str
    description: str
    enabled: bool = True
    models: AgentModelConfig = field(default_factory=AgentModelConfig)
    prompt_file: str | None = None
    tools: AgentToolConfig = field(default_factory=AgentToolConfig)
    memory: AgentMemoryConfig | None = None
    metadata: dict = field(default_factory=dict)

    def prompt(self, config_dir: Path) -> str:
        """Resolve prompt content, anchored to config_dir."""
        if self.prompt_file:
            path = config_dir / self.prompt_file
            if path.exists():
                return path.read_text()
        return f"You are the {self.name} agent. Help the user with {self.name}-related tasks."

    def to_dict(self) -> dict:
        """Serialize to dict for YAML/JSON output."""
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentSpec":
        """Deserialize from dict."""
        models_data = data.get("models", {})
        tools_data = data.get("tools", {})
        memory_data = data.get("memory")

        return cls(
            name=data["name"],
            description=data["description"],
            enabled=data.get("enabled", True),
            models=AgentModelConfig(**models_data) if models_data else AgentModelConfig(),
            prompt_file=data.get("prompt_file"),
            tools=AgentToolConfig(**tools_data) if tools_data else AgentToolConfig(),
            memory=AgentMemoryConfig(**memory_data) if memory_data else None,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentSpec":
        """Load spec from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_agent_spec.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/agents/__init__.py corvus/agents/spec.py tests/gateway/test_agent_spec.py
git commit -m "feat(agents): add AgentSpec dataclasses with YAML loading"
```

---

### Task 2: Write 9 Default Agent YAML Specs

**Files:**
- Create: `config/agents/personal.yaml`
- Create: `config/agents/work.yaml`
- Create: `config/agents/homelab.yaml`
- Create: `config/agents/finance.yaml`
- Create: `config/agents/email.yaml`
- Create: `config/agents/docs.yaml`
- Create: `config/agents/music.yaml`
- Create: `config/agents/home.yaml`
- Create: `config/agents/general.yaml`
- Create: `tests/gateway/test_agent_yaml_specs.py`

**Step 1: Write the failing test**

```python
# tests/gateway/test_agent_yaml_specs.py
"""Validate all 9 default agent YAML specs load correctly."""

import pytest
from pathlib import Path

from corvus.agents.spec import AgentSpec

CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"
EXPECTED_AGENTS = {"personal", "work", "homelab", "finance", "email", "docs", "music", "home", "general"}


class TestDefaultAgentSpecs:
    @pytest.fixture(scope="class")
    def specs(self) -> dict[str, AgentSpec]:
        result = {}
        for yaml_file in sorted(CONFIG_DIR.glob("*.yaml")):
            spec = AgentSpec.from_yaml(yaml_file)
            result[spec.name] = spec
        return result

    def test_all_nine_agents_exist(self, specs):
        assert set(specs.keys()) == EXPECTED_AGENTS

    def test_all_agents_enabled(self, specs):
        for name, spec in specs.items():
            assert spec.enabled, f"{name} should be enabled"

    def test_all_agents_have_description(self, specs):
        for name, spec in specs.items():
            assert spec.description, f"{name} missing description"

    def test_all_agents_have_memory_domain(self, specs):
        for name, spec in specs.items():
            assert spec.memory is not None, f"{name} missing memory config"
            assert spec.memory.own_domain, f"{name} missing own_domain"

    def test_all_agents_have_prompt_file(self, specs):
        for name, spec in specs.items():
            assert spec.prompt_file is not None, f"{name} missing prompt_file"

    def test_prompt_files_exist(self, specs):
        project_root = Path(__file__).parent.parent.parent
        for name, spec in specs.items():
            prompt_path = project_root / spec.prompt_file
            assert prompt_path.exists(), f"{name}: prompt file {spec.prompt_file} does not exist"

    def test_complexity_values_valid(self, specs):
        valid = {"high", "medium", "low"}
        for name, spec in specs.items():
            assert spec.models.complexity in valid, f"{name}: invalid complexity '{spec.models.complexity}'"

    def test_memory_domains_unique(self, specs):
        domains = [s.memory.own_domain for s in specs.values()]
        # general uses "shared" which is special
        non_shared = [d for d in domains if d != "shared"]
        assert len(non_shared) == len(set(non_shared)), "Duplicate memory domains found"

    def test_obsidian_agents_have_prefixes(self, specs):
        for name, spec in specs.items():
            obs = spec.tools.modules.get("obsidian")
            if obs and obs.get("write"):
                assert "obsidian.write" in spec.tools.confirm_gated or "obsidian.append" in spec.tools.confirm_gated, \
                    f"{name}: obsidian write without confirm-gating"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_agent_yaml_specs.py -v`
Expected: FAIL — no YAML files exist yet

**Step 3: Create all 9 YAML specs**

Create `config/agents/` directory, then write each YAML file. The content mirrors what's currently hardcoded in `corvus/agents.py` and `corvus/agent_config.py`. Here's one example — repeat the pattern for all 9, pulling descriptions from `corvus/agents.py` lines 32-149 and tool/memory access from `corvus/agent_config.py`:

```yaml
# config/agents/personal.yaml
name: personal
description: >
  Daily planning, task management, journaling, ADHD support,
  stray thought capture, health tracking, personal reminders,
  and self-care routines
enabled: true
models:
  preferred: null
  fallback: null
  auto: true
  complexity: medium
prompt_file: corvus/prompts/personal.md
tools:
  builtin:
    - Bash
    - Read
  modules:
    obsidian:
      allowed_prefixes:
        - "personal/"
        - "shared/"
      read: true
      write: true
    memory:
      enabled: true
  confirm_gated:
    - obsidian.write
    - obsidian.append
memory:
  own_domain: personal
  readable_domains: null
  can_read_shared: true
  can_write: true
```

Create the remaining 8 by referencing:
- `corvus/agents.py` for descriptions and tool lists
- `corvus/agent_config.py` lines 26-55 for obsidian access (personal, work, homelab, general)
- `corvus/agent_config.py` lines 105-118 for memory domains
- `config/models.yaml` lines 20-47 for complexity mapping: finance→high (opus), homelab→high (sonnet but infra-heavy), music→low (haiku), home→low (haiku), all others→medium

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_agent_yaml_specs.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add config/agents/ tests/gateway/test_agent_yaml_specs.py
git commit -m "feat(agents): add 9 default agent YAML specs"
```

---

### Task 3: AgentRegistry — Load, Validate, CRUD

**Files:**
- Create: `corvus/agents/registry.py`
- Create: `tests/gateway/test_agent_registry.py`
- Modify: `corvus/agents/__init__.py` — add AgentRegistry, ReloadResult exports

**Step 1: Write the failing tests**

```python
# tests/gateway/test_agent_registry.py
"""Tests for AgentRegistry — loading, validation, CRUD, reload."""

import pytest
from pathlib import Path

import yaml

from corvus.agents.registry import AgentRegistry, ReloadResult
from corvus.agents.spec import AgentSpec, AgentMemoryConfig, AgentToolConfig


def _write_spec(config_dir: Path, name: str, **overrides) -> Path:
    """Helper to write a valid agent YAML spec."""
    data = {
        "name": name,
        "description": f"{name} agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "prompt_file": None,
        "tools": {"builtin": ["Bash"], "modules": {}, "confirm_gated": []},
        "memory": {"own_domain": name, "can_read_shared": True, "can_write": True},
    }
    data.update(overrides)
    path = config_dir / f"{name}.yaml"
    path.write_text(yaml.dump(data))
    return path


class TestAgentRegistryLoad:
    def test_load_from_directory(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        _write_spec(tmp_path, "beta")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert len(reg.list_all()) == 2

    def test_load_empty_directory(self, tmp_path):
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert reg.list_all() == []

    def test_get_existing(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        spec = reg.get("alpha")
        assert spec is not None
        assert spec.name == "alpha"

    def test_get_missing(self, tmp_path):
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert reg.get("nonexistent") is None

    def test_list_enabled_excludes_disabled(self, tmp_path):
        _write_spec(tmp_path, "active")
        _write_spec(tmp_path, "inactive", enabled=False)
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        enabled = reg.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "active"


class TestAgentRegistryValidation:
    def test_rejects_empty_name(self, tmp_path):
        _write_spec(tmp_path, "", description="Bad agent")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert reg.get("") is None

    def test_rejects_empty_description(self, tmp_path):
        data = {"name": "bad", "description": "", "memory": {"own_domain": "bad"}}
        (tmp_path / "bad.yaml").write_text(yaml.dump(data))
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert reg.get("bad") is None

    def test_rejects_invalid_complexity(self, tmp_path):
        _write_spec(tmp_path, "bad", models={"complexity": "extreme"})
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert reg.get("bad") is None


class TestAgentRegistryCRUD:
    def test_create_agent(self, tmp_path):
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        spec = AgentSpec(
            name="new_agent",
            description="A new agent",
            memory=AgentMemoryConfig(own_domain="new"),
        )
        reg.create(spec)
        assert reg.get("new_agent") is not None
        assert (tmp_path / "new_agent.yaml").exists()

    def test_create_duplicate_raises(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        with pytest.raises(ValueError, match="already exists"):
            reg.create(AgentSpec(name="alpha", description="Dup"))

    def test_update_agent(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        updated = reg.update("alpha", {"description": "Updated description"})
        assert updated.description == "Updated description"
        # Verify persisted to disk
        reloaded = AgentSpec.from_yaml(tmp_path / "alpha.yaml")
        assert reloaded.description == "Updated description"

    def test_deactivate_agent(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        reg.deactivate("alpha")
        spec = reg.get("alpha")
        assert spec is not None
        assert spec.enabled is False


class TestAgentRegistryReload:
    def test_reload_detects_new_file(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        assert len(reg.list_all()) == 1
        _write_spec(tmp_path, "beta")
        result = reg.reload()
        assert "beta" in result.added
        assert len(reg.list_all()) == 2

    def test_reload_detects_removal(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        _write_spec(tmp_path, "beta")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        (tmp_path / "beta.yaml").unlink()
        result = reg.reload()
        assert "beta" in result.removed

    def test_reload_detects_change(self, tmp_path):
        _write_spec(tmp_path, "alpha")
        reg = AgentRegistry(config_dir=tmp_path)
        reg.load()
        _write_spec(tmp_path, "alpha", description="Changed!")
        result = reg.reload()
        assert "alpha" in result.changed
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_agent_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.agents.registry'`

**Step 3: Write the implementation**

```python
# corvus/agents/registry.py
"""AgentRegistry — loads, validates, and serves AgentSpecs from YAML files.

Each agent is defined by one YAML file in config/agents/{name}.yaml.
The registry provides CRUD operations that persist to disk, and a
reload() method that diffs against in-memory state.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from corvus.agents.spec import AgentSpec

logger = logging.getLogger("corvus-gateway")

VALID_COMPLEXITY = {"high", "medium", "low"}


@dataclass
class ReloadResult:
    """Result of a reload() operation."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class AgentRegistry:
    """Load, validate, and serve AgentSpecs from config/agents/*.yaml."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._specs: dict[str, AgentSpec] = {}
        self._file_hashes: dict[str, str] = {}  # name -> file content hash for change detection

    def load(self) -> None:
        """Load all YAML specs from config_dir. Invalid specs are logged and skipped."""
        self._specs.clear()
        self._file_hashes.clear()
        if not self._config_dir.exists():
            return
        for yaml_file in sorted(self._config_dir.glob("*.yaml")):
            self._load_one(yaml_file)

    def _load_one(self, path: Path) -> bool:
        """Load and validate a single YAML file. Returns True if loaded successfully."""
        try:
            spec = AgentSpec.from_yaml(path)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", path.name, exc)
            return False

        errors = self.validate(spec)
        if errors:
            logger.warning("Invalid spec %s: %s", path.name, "; ".join(errors))
            return False

        self._specs[spec.name] = spec
        self._file_hashes[spec.name] = path.read_text()
        return True

    def get(self, name: str) -> AgentSpec | None:
        """Get a spec by name, or None if not found."""
        return self._specs.get(name)

    def list_enabled(self) -> list[AgentSpec]:
        """Return all enabled specs."""
        return [s for s in self._specs.values() if s.enabled]

    def list_all(self) -> list[AgentSpec]:
        """Return all specs (enabled and disabled)."""
        return list(self._specs.values())

    def validate(self, spec: AgentSpec) -> list[str]:
        """Validate a spec. Returns list of error messages (empty = valid)."""
        errors: list[str] = []
        if not spec.name or not spec.name.strip():
            errors.append("name must be non-empty")
        if not spec.description or not spec.description.strip():
            errors.append("description must be non-empty")
        if spec.models.complexity not in VALID_COMPLEXITY:
            errors.append(f"complexity must be one of {VALID_COMPLEXITY}, got '{spec.models.complexity}'")
        if spec.memory and not spec.memory.own_domain:
            errors.append("memory.own_domain must be non-empty")
        return errors

    def create(self, spec: AgentSpec) -> None:
        """Create a new agent spec and persist to disk."""
        if spec.name in self._specs:
            raise ValueError(f"Agent '{spec.name}' already exists")
        errors = self.validate(spec)
        if errors:
            raise ValueError(f"Invalid spec: {'; '.join(errors)}")
        self._persist(spec)
        self._specs[spec.name] = spec

    def update(self, name: str, patch: dict) -> AgentSpec:
        """Partial update of an existing spec. Returns updated spec."""
        spec = self._specs.get(name)
        if spec is None:
            raise ValueError(f"Agent '{name}' not found")
        data = spec.to_dict()
        data.update(patch)
        updated = AgentSpec.from_dict(data)
        errors = self.validate(updated)
        if errors:
            raise ValueError(f"Invalid update: {'; '.join(errors)}")
        self._persist(updated)
        self._specs[name] = updated
        return updated

    def deactivate(self, name: str) -> None:
        """Set an agent to enabled=false and persist."""
        self.update(name, {"enabled": False})

    def reload(self) -> ReloadResult:
        """Re-read YAML files and diff against in-memory state."""
        result = ReloadResult()
        current_names = set(self._specs.keys())
        disk_names: set[str] = set()

        if not self._config_dir.exists():
            for name in current_names:
                result.removed.append(name)
            self._specs.clear()
            self._file_hashes.clear()
            return result

        for yaml_file in sorted(self._config_dir.glob("*.yaml")):
            try:
                spec = AgentSpec.from_yaml(yaml_file)
            except Exception as exc:
                result.errors[yaml_file.stem] = str(exc)
                continue

            errors = self.validate(spec)
            if errors:
                result.errors[spec.name] = "; ".join(errors)
                continue

            disk_names.add(spec.name)
            new_content = yaml_file.read_text()

            if spec.name not in current_names:
                result.added.append(spec.name)
                self._specs[spec.name] = spec
                self._file_hashes[spec.name] = new_content
            elif self._file_hashes.get(spec.name) != new_content:
                result.changed.append(spec.name)
                self._specs[spec.name] = spec
                self._file_hashes[spec.name] = new_content

        for name in current_names - disk_names:
            result.removed.append(name)
            self._specs.pop(name, None)
            self._file_hashes.pop(name, None)

        return result

    def _persist(self, spec: AgentSpec) -> None:
        """Write spec to disk as YAML."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        path = self._config_dir / f"{spec.name}.yaml"
        with open(path, "w") as f:
            yaml.dump(spec.to_dict(), f, default_flow_style=False, sort_keys=False)
        self._file_hashes[spec.name] = path.read_text()
```

**Step 4: Update `corvus/agents/__init__.py`**

Add `AgentRegistry` and `ReloadResult` to the exports.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_agent_registry.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/agents/registry.py corvus/agents/__init__.py tests/gateway/test_agent_registry.py
git commit -m "feat(agents): add AgentRegistry with YAML loading, validation, CRUD, reload"
```

---

### Task 4: CapabilitiesRegistry — Security-Enforced Tool Resolution

**Files:**
- Create: `corvus/capabilities/__init__.py`
- Create: `corvus/capabilities/registry.py`
- Create: `tests/gateway/test_capabilities_registry.py`

**Step 1: Write the failing tests**

```python
# tests/gateway/test_capabilities_registry.py
"""Tests for CapabilitiesRegistry — tool module registration and policy-enforced resolution."""

import pytest
from pathlib import Path

from corvus.agents.spec import AgentSpec, AgentToolConfig, AgentMemoryConfig
from corvus.capabilities.registry import (
    CapabilitiesRegistry,
    ToolModuleEntry,
    ResolvedTools,
    ModuleHealth,
)


def _make_spec(name: str, modules: dict | None = None) -> AgentSpec:
    """Helper to build a minimal AgentSpec."""
    return AgentSpec(
        name=name,
        description=f"{name} agent",
        tools=AgentToolConfig(
            builtin=["Bash"],
            modules=modules or {},
            confirm_gated=[],
        ),
        memory=AgentMemoryConfig(own_domain=name),
    )


def _make_module(name: str, requires_env: list[str] | None = None, per_agent: bool = False) -> ToolModuleEntry:
    """Helper to build a ToolModuleEntry."""
    return ToolModuleEntry(
        name=name,
        configure=lambda **kw: None,
        create_tools=lambda cfg: [lambda: "tool_result"],
        create_mcp_server=lambda tools, agent_cfg: {"name": name, "tools": tools},
        requires_env=requires_env or [],
        supports_per_agent=per_agent,
    )


class TestModuleRegistration:
    def test_register_and_list(self):
        reg = CapabilitiesRegistry()
        reg.register("ha", _make_module("ha"))
        reg.register("email", _make_module("email"))
        available = reg.list_available()
        assert "ha" in available
        assert "email" in available

    def test_register_duplicate_raises(self):
        reg = CapabilitiesRegistry()
        reg.register("ha", _make_module("ha"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register("ha", _make_module("ha"))


class TestToolResolution:
    def test_resolve_returns_available_modules(self, monkeypatch):
        monkeypatch.setenv("HA_URL", "http://ha.local")
        reg = CapabilitiesRegistry()
        reg.register("ha", _make_module("ha", requires_env=["HA_URL"]))
        spec = _make_spec("home", modules={"ha": {"enabled": True}})
        resolved = reg.resolve(spec)
        assert "ha" in resolved.available_modules

    def test_resolve_skips_unavailable_env(self):
        reg = CapabilitiesRegistry()
        reg.register("ha", _make_module("ha", requires_env=["HA_URL_MISSING"]))
        spec = _make_spec("home", modules={"ha": {"enabled": True}})
        resolved = reg.resolve(spec)
        assert "ha" not in resolved.available_modules
        assert "ha" in resolved.unavailable_modules

    def test_resolve_skips_unregistered_module(self):
        reg = CapabilitiesRegistry()
        spec = _make_spec("home", modules={"nonexistent": {"enabled": True}})
        resolved = reg.resolve(spec)
        assert "nonexistent" in resolved.unavailable_modules

    def test_resolve_empty_modules(self):
        reg = CapabilitiesRegistry()
        spec = _make_spec("music", modules={})
        resolved = reg.resolve(spec)
        assert resolved.available_modules == []


class TestConfirmGating:
    def test_confirm_gated_from_spec(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test")
        reg = CapabilitiesRegistry()
        reg.register("obsidian", _make_module("obsidian", requires_env=["OBSIDIAN_API_KEY"], per_agent=True))
        spec = AgentSpec(
            name="personal",
            description="Personal",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"obsidian": {"read": True, "write": True}},
                confirm_gated=["obsidian.write", "obsidian.append"],
            ),
            memory=AgentMemoryConfig(own_domain="personal"),
        )
        gated = reg.confirm_gated(spec)
        assert "obsidian.write" in gated
        assert "obsidian.append" in gated


class TestModuleHealth:
    def test_health_returns_status(self):
        reg = CapabilitiesRegistry()
        reg.register("ha", _make_module("ha"))
        health = reg.health("ha")
        assert health.name == "ha"

    def test_health_unknown_module(self):
        reg = CapabilitiesRegistry()
        health = reg.health("nonexistent")
        assert health.status == "unknown"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_capabilities_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.capabilities'`

**Step 3: Write the implementation**

```python
# corvus/capabilities/__init__.py
"""Capabilities — security-enforced tool resolution and module registry."""

from corvus.capabilities.registry import (
    CapabilitiesRegistry,
    ModuleHealth,
    ResolvedTools,
    ToolModuleEntry,
)

__all__ = [
    "CapabilitiesRegistry",
    "ModuleHealth",
    "ResolvedTools",
    "ToolModuleEntry",
]
```

```python
# corvus/capabilities/registry.py
"""CapabilitiesRegistry — security boundary for all tool access.

Every tool access flows through resolve(). The registry checks env gates,
applies per-agent scoping, enforces deny-wins policy, and derives
confirm-gated tool sets from agent specs.
"""

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("corvus-gateway")


@dataclass
class ModuleHealth:
    """Health status for a tool module."""

    name: str
    status: str = "healthy"  # "healthy" | "unhealthy" | "degraded" | "unknown"
    detail: str = ""


@dataclass
class ToolModuleEntry:
    """Registration entry for a tool module."""

    name: str
    configure: Callable
    create_tools: Callable
    create_mcp_server: Callable
    requires_env: list[str] = field(default_factory=list)
    supports_per_agent: bool = False
    health_check: Callable[[], Awaitable[ModuleHealth]] | None = None
    restart: Callable[[], Awaitable[None]] | None = None


@dataclass
class ResolvedTools:
    """Result of resolve() — the fully-scoped tool set for an agent."""

    mcp_servers: dict[str, Any] = field(default_factory=dict)
    confirm_gated: set[str] = field(default_factory=set)
    available_modules: list[str] = field(default_factory=list)
    unavailable_modules: dict[str, str] = field(default_factory=dict)


class CapabilitiesRegistry:
    """Security-enforced tool resolution. All tool access flows through here."""

    def __init__(self) -> None:
        self._modules: dict[str, ToolModuleEntry] = {}

    def register(self, name: str, module: ToolModuleEntry) -> None:
        """Register a tool module. Raises ValueError on duplicate."""
        if name in self._modules:
            raise ValueError(f"Module '{name}' already registered")
        self._modules[name] = module
        logger.info("Registered tool module: %s", name)

    def resolve(self, agent_spec: "AgentSpec") -> ResolvedTools:
        """Build the tool set for an agent, enforcing policy.

        1. Read agent's tools.modules from spec
        2. For each module, check env gates (is the service configured?)
        3. Apply per-agent scoping (obsidian prefixes, etc.)
        4. Deny wins — if env gate fails, module excluded
        5. Return only the tools this agent is allowed to use
        """
        from corvus.agents.spec import AgentSpec  # deferred to avoid circular import at module level

        resolved = ResolvedTools()

        for module_name, module_cfg in agent_spec.tools.modules.items():
            entry = self._modules.get(module_name)
            if entry is None:
                resolved.unavailable_modules[module_name] = "not registered"
                continue

            # Check env gates
            missing_env = [v for v in entry.requires_env if not os.environ.get(v)]
            if missing_env:
                resolved.unavailable_modules[module_name] = f"missing env: {', '.join(missing_env)}"
                continue

            # Build tools and MCP server for this module
            try:
                tools = entry.create_tools(module_cfg)
                mcp_server = entry.create_mcp_server(tools, module_cfg)

                server_name = f"{module_name}_{agent_spec.name}" if entry.supports_per_agent else module_name
                resolved.mcp_servers[server_name] = mcp_server
                resolved.available_modules.append(module_name)
            except Exception as exc:
                resolved.unavailable_modules[module_name] = f"error: {exc}"
                logger.warning("Failed to resolve module %s for agent %s: %s", module_name, agent_spec.name, exc)

        # Derive confirm-gated tools from spec
        resolved.confirm_gated = set(agent_spec.tools.confirm_gated)

        return resolved

    def is_allowed(self, agent_name: str, tool_name: str) -> bool:
        """Check if a tool is allowed for an agent. Used by hooks for audit."""
        # In V1, if it resolved, it's allowed. Future: per-turn re-evaluation.
        return True

    def confirm_gated(self, agent_spec: "AgentSpec") -> set[str]:
        """Return tools requiring user confirmation for this agent."""
        return set(agent_spec.tools.confirm_gated)

    def list_available(self) -> list[str]:
        """Return names of all registered modules."""
        return list(self._modules.keys())

    def health(self, name: str) -> ModuleHealth:
        """Get health status for a module."""
        entry = self._modules.get(name)
        if entry is None:
            return ModuleHealth(name=name, status="unknown", detail="not registered")
        # V1: simple — if registered, healthy. Future: call health_check callable.
        return ModuleHealth(name=name, status="healthy")

    def get_module(self, name: str) -> ToolModuleEntry | None:
        """Get a module entry by name."""
        return self._modules.get(name)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_capabilities_registry.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/capabilities/__init__.py corvus/capabilities/registry.py tests/gateway/test_capabilities_registry.py
git commit -m "feat(capabilities): add CapabilitiesRegistry with security-enforced tool resolution"
```

---

## Phase 2: AgentsHub (the switchover)

### Task 5: AgentsHub — The Coordinator

**Files:**
- Create: `corvus/agents/hub.py`
- Create: `tests/gateway/test_agents_hub.py`
- Modify: `corvus/agents/__init__.py` — add AgentsHub export

**Step 1: Write the failing tests**

```python
# tests/gateway/test_agents_hub.py
"""Tests for AgentsHub — the coordinator wiring spec → tools → memory → SDK options."""

import os
import pytest
from pathlib import Path

import yaml

from corvus.agents.hub import AgentsHub, AgentSummary
from corvus.agents.registry import AgentRegistry
from corvus.agents.spec import AgentSpec, AgentMemoryConfig, AgentToolConfig
from corvus.capabilities.registry import CapabilitiesRegistry, ToolModuleEntry
from corvus.memory import MemoryConfig, MemoryHub
from corvus.model_router import ModelRouter
from corvus.events import EventEmitter

from tests.conftest import make_hub, run


def _write_spec(config_dir: Path, name: str, **overrides) -> None:
    data = {
        "name": name,
        "description": f"{name} agent for testing",
        "enabled": True,
        "models": {"complexity": "medium"},
        "prompt_file": None,
        "tools": {"builtin": ["Bash"], "modules": {"memory": {"enabled": True}}, "confirm_gated": []},
        "memory": {"own_domain": name, "can_read_shared": True, "can_write": True},
    }
    data.update(overrides)
    (config_dir / f"{name}.yaml").write_text(yaml.dump(data))


def _make_hub(tmp_path: Path) -> AgentsHub:
    """Build a fully wired AgentsHub for testing."""
    agents_dir = tmp_path / "config" / "agents"
    agents_dir.mkdir(parents=True)
    _write_spec(agents_dir, "personal")
    _write_spec(agents_dir, "work")
    _write_spec(agents_dir, "finance", models={"complexity": "high"})

    agent_registry = AgentRegistry(config_dir=agents_dir)
    agent_registry.load()

    capabilities = CapabilitiesRegistry()
    memory_hub = make_hub(tmp_path)
    model_router = ModelRouter(config={"defaults": {"model": "sonnet"}})
    emitter = EventEmitter()

    return AgentsHub(
        registry=agent_registry,
        capabilities=capabilities,
        memory_hub=memory_hub,
        model_router=model_router,
        emitter=emitter,
        config_dir=tmp_path,
    )


class TestAgentsHubBuild:
    def test_build_all_returns_agent_definitions(self, tmp_path):
        hub = _make_hub(tmp_path)
        agents = hub.build_all()
        assert "personal" in agents
        assert "work" in agents
        assert "finance" in agents

    def test_build_agent_returns_definition(self, tmp_path):
        hub = _make_hub(tmp_path)
        defn = hub.build_agent("personal")
        assert defn.description is not None
        assert "personal" in defn.description.lower() or "planning" in defn.description.lower()


class TestPerAgentMemoryIdentity:
    """The critical fix — each agent gets its own memory toolkit with correct identity."""

    def test_memory_servers_are_per_agent(self, tmp_path):
        hub = _make_hub(tmp_path)
        personal_servers = hub.build_mcp_servers("personal")
        work_servers = hub.build_mcp_servers("work")
        # Each should have a uniquely named memory server
        assert "memory_personal" in personal_servers
        assert "memory_work" in work_servers

    def test_personal_memory_writes_to_personal_domain(self, tmp_path):
        hub = _make_hub(tmp_path)
        # Save via personal agent
        result = run(hub.memory_hub.save(
            _make_record("Test personal memory", domain="personal"),
            agent_name="personal",
        ))
        assert result  # record_id returned
        # Verify it's in personal domain
        records = run(hub.memory_hub.search("Test personal", agent_name="personal"))
        assert len(records) >= 1
        assert records[0].domain == "personal"

    def test_work_agent_cannot_write_to_personal_domain(self, tmp_path):
        hub = _make_hub(tmp_path)
        with pytest.raises(PermissionError):
            run(hub.memory_hub.save(
                _make_record("Sneaky write", domain="personal"),
                agent_name="work",
            ))


def _make_record(content: str, domain: str = "shared"):
    from corvus.memory.record import MemoryRecord
    import uuid
    return MemoryRecord(
        id=str(uuid.uuid4()),
        content=content,
        domain=domain,
        visibility="private",
    )


class TestAgentsHubManagement:
    def test_list_agents(self, tmp_path):
        hub = _make_hub(tmp_path)
        agents = hub.list_agents()
        assert len(agents) == 3
        names = {a.name for a in agents}
        assert names == {"personal", "work", "finance"}

    def test_create_agent(self, tmp_path):
        hub = _make_hub(tmp_path)
        spec = AgentSpec(
            name="music",
            description="Music practice",
            memory=AgentMemoryConfig(own_domain="music"),
        )
        created = hub.create_agent(spec)
        assert created.name == "music"
        assert hub.get_agent("music") is not None

    def test_update_agent(self, tmp_path):
        hub = _make_hub(tmp_path)
        updated = hub.update_agent("personal", {"description": "New description"})
        assert updated.description == "New description"

    def test_deactivate_agent(self, tmp_path):
        hub = _make_hub(tmp_path)
        hub.deactivate_agent("finance")
        spec = hub.get_agent("finance")
        assert spec.enabled is False

    def test_reload(self, tmp_path):
        hub = _make_hub(tmp_path)
        agents_dir = tmp_path / "config" / "agents"
        _write_spec(agents_dir, "music")
        result = hub.reload()
        assert "music" in result.added
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_agents_hub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.agents.hub'`

**Step 3: Write the implementation**

```python
# corvus/agents/hub.py
"""AgentsHub — the central coordinator for agent lifecycle.

Wires AgentSpec → tools → memory → SDK AgentDefinition.
Replaces the monolithic build_options() in server.py.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server

from corvus.agents.registry import AgentRegistry, ReloadResult
from corvus.agents.spec import AgentSpec
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.memory import MemoryHub, create_memory_toolkit
from corvus.model_router import ModelRouter

logger = logging.getLogger("corvus-gateway")


@dataclass
class AgentSummary:
    """Lightweight agent info for frontend listing."""

    name: str
    description: str
    enabled: bool
    complexity: str
    tool_modules: list[str]
    memory_domain: str
    has_prompt: bool


class AgentsHub:
    """Coordinates agent lifecycle: spec → tools → memory → SDK options."""

    def __init__(
        self,
        registry: AgentRegistry,
        capabilities: CapabilitiesRegistry,
        memory_hub: MemoryHub,
        model_router: ModelRouter,
        emitter: EventEmitter,
        config_dir: Path,
    ) -> None:
        self.registry = registry
        self.capabilities = capabilities
        self.memory_hub = memory_hub
        self.model_router = model_router
        self.emitter = emitter
        self.config_dir = config_dir

    def build_agent(self, name: str) -> AgentDefinition:
        """Build a single SDK AgentDefinition from spec."""
        spec = self.registry.get(name)
        if not spec or not spec.enabled:
            raise ValueError(f"Agent '{name}' not found or disabled")

        # Resolve tools with security enforcement
        resolved = self.capabilities.resolve(spec)

        # Create per-agent memory toolkit with correct identity
        memory_toolkit = create_memory_toolkit(self.memory_hub, agent_name=spec.name)
        resolved.mcp_servers[f"memory_{spec.name}"] = create_sdk_mcp_server(
            name=f"memory_{spec.name}",
            version="1.0.0",
            tools=[t.fn for t in memory_toolkit],
        )

        return AgentDefinition(
            description=spec.description,
            prompt=spec.prompt(config_dir=self.config_dir),
            tools=spec.tools.builtin,
        )

    def build_all(self) -> dict[str, AgentDefinition]:
        """Build all enabled agents. Replaces build_agents()."""
        agents = {}
        for spec in self.registry.list_enabled():
            try:
                agents[spec.name] = self.build_agent(spec.name)
            except Exception as exc:
                logger.warning("Failed to build agent %s: %s", spec.name, exc)
        return agents

    def build_mcp_servers(self, name: str) -> dict:
        """Build per-agent MCP servers (obsidian, memory, etc.)."""
        spec = self.registry.get(name)
        if not spec or not spec.enabled:
            return {}
        resolved = self.capabilities.resolve(spec)

        # Always add per-agent memory
        memory_toolkit = create_memory_toolkit(self.memory_hub, agent_name=spec.name)
        resolved.mcp_servers[f"memory_{spec.name}"] = create_sdk_mcp_server(
            name=f"memory_{spec.name}",
            version="1.0.0",
            tools=[t.fn for t in memory_toolkit],
        )
        return resolved.mcp_servers

    # --- Frontend management ---

    def list_agents(self) -> list[AgentSummary]:
        """List all agents with summary info."""
        result = []
        for spec in self.registry.list_all():
            modules = list(spec.tools.modules.keys())
            result.append(AgentSummary(
                name=spec.name,
                description=spec.description,
                enabled=spec.enabled,
                complexity=spec.models.complexity,
                tool_modules=modules,
                memory_domain=spec.memory.own_domain if spec.memory else "shared",
                has_prompt=spec.prompt_file is not None,
            ))
        return result

    def get_agent(self, name: str) -> AgentSpec | None:
        """Get full agent spec."""
        return self.registry.get(name)

    def create_agent(self, spec: AgentSpec) -> AgentSpec:
        """Create a new agent and persist to disk."""
        self.registry.create(spec)
        return spec

    def update_agent(self, name: str, patch: dict) -> AgentSpec:
        """Partial update of an agent."""
        return self.registry.update(name, patch)

    def deactivate_agent(self, name: str) -> None:
        """Deactivate an agent."""
        self.registry.deactivate(name)

    def reload(self) -> ReloadResult:
        """Reload agent specs from disk."""
        return self.registry.reload()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_agents_hub.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/agents/hub.py corvus/agents/__init__.py tests/gateway/test_agents_hub.py
git commit -m "feat(agents): add AgentsHub coordinator wiring spec → tools → memory → SDK"
```

---

### Task 6: Register Existing Tool Modules in CapabilitiesRegistry

**Files:**
- Create: `corvus/capabilities/modules.py`
- Create: `tests/gateway/test_capabilities_modules.py`

This task creates the registration functions that wire existing tool modules (`obsidian`, `email`, `drive`, `ha`, `paperless`, `firefly`) into the `CapabilitiesRegistry`. Each module gets a `register_{name}()` function that creates a `ToolModuleEntry`.

**Step 1: Write the failing tests**

```python
# tests/gateway/test_capabilities_modules.py
"""Tests for tool module registration functions."""

from corvus.capabilities.modules import TOOL_MODULE_DEFS


class TestToolModuleDefs:
    def test_all_modules_defined(self):
        names = {d.name for d in TOOL_MODULE_DEFS}
        assert names == {"obsidian", "email", "drive", "ha", "paperless", "firefly"}

    def test_obsidian_is_per_agent(self):
        obs = next(d for d in TOOL_MODULE_DEFS if d.name == "obsidian")
        assert obs.supports_per_agent is True

    def test_shared_modules_not_per_agent(self):
        for d in TOOL_MODULE_DEFS:
            if d.name != "obsidian":
                assert not d.supports_per_agent, f"{d.name} should not be per-agent"

    def test_all_modules_have_env_gates(self):
        for d in TOOL_MODULE_DEFS:
            assert len(d.requires_env) > 0, f"{d.name} should have env gate"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gateway/test_capabilities_modules.py -v`
Expected: FAIL

**Step 3: Write the implementation**

```python
# corvus/capabilities/modules.py
"""Tool module definitions for CapabilitiesRegistry.

Each existing tool module (obsidian, email, drive, ha, paperless, firefly)
is defined as a ToolModuleEntry with its env gates, configure function,
and tool creation logic. These definitions are registered at startup.
"""

from corvus.capabilities.registry import ToolModuleEntry


def _obsidian_entry() -> ToolModuleEntry:
    from corvus.tools.obsidian import ObsidianClient, configure as configure_obsidian
    import os

    def create_tools(module_cfg: dict) -> list:
        obs_url = os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124")
        obs_key = os.environ["OBSIDIAN_API_KEY"]
        prefixes = module_cfg.get("allowed_prefixes")
        client = ObsidianClient(obs_url, obs_key, prefixes)
        tools = []
        if module_cfg.get("read", True):
            tools.extend([client.obsidian_search, client.obsidian_read])
        if module_cfg.get("write", False):
            tools.extend([client.obsidian_write, client.obsidian_append])
        return tools

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="obsidian", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="obsidian",
        configure=configure_obsidian,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["OBSIDIAN_API_KEY"],
        supports_per_agent=True,
    )


def _email_entry() -> ToolModuleEntry:
    from corvus.tools.email import (
        configure as configure_email,
        email_archive, email_draft, email_label, email_labels,
        email_list, email_read, email_send,
    )

    def create_tools(module_cfg: dict) -> list:
        return [email_list, email_read, email_draft, email_send,
                email_archive, email_label, email_labels]

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="email", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="email",
        configure=configure_email,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["GOOGLE_CREDS_PATH"],
        supports_per_agent=False,
    )


def _drive_entry() -> ToolModuleEntry:
    from corvus.tools.drive import (
        configure as configure_drive,
        drive_cleanup, drive_create, drive_delete, drive_edit,
        drive_list, drive_move, drive_permanent_delete, drive_read, drive_share,
    )

    def create_tools(module_cfg: dict) -> list:
        return [drive_list, drive_read, drive_create, drive_edit,
                drive_move, drive_delete, drive_permanent_delete, drive_share, drive_cleanup]

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="drive", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="drive",
        configure=configure_drive,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["GOOGLE_CREDS_PATH"],
        supports_per_agent=False,
    )


def _ha_entry() -> ToolModuleEntry:
    from corvus.tools.ha import (
        configure as configure_ha,
        ha_call_service, ha_get_state, ha_list_entities,
    )

    def create_tools(module_cfg: dict) -> list:
        return [ha_list_entities, ha_get_state, ha_call_service]

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="ha", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="ha",
        configure=configure_ha,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["HA_URL"],
        supports_per_agent=False,
    )


def _paperless_entry() -> ToolModuleEntry:
    from corvus.tools.paperless import (
        configure as configure_paperless,
        paperless_bulk_edit, paperless_read, paperless_search,
        paperless_tag, paperless_tags,
    )

    def create_tools(module_cfg: dict) -> list:
        return [paperless_search, paperless_read, paperless_tags,
                paperless_tag, paperless_bulk_edit]

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="paperless", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="paperless",
        configure=configure_paperless,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["PAPERLESS_URL"],
        supports_per_agent=False,
    )


def _firefly_entry() -> ToolModuleEntry:
    from corvus.tools.firefly import (
        configure as configure_firefly,
        firefly_accounts, firefly_categories, firefly_create_transaction,
        firefly_summary, firefly_transactions,
    )

    def create_tools(module_cfg: dict) -> list:
        return [firefly_transactions, firefly_accounts, firefly_categories,
                firefly_summary, firefly_create_transaction]

    def create_mcp_server(tools: list, module_cfg: dict):
        from claude_agent_sdk import create_sdk_mcp_server
        return create_sdk_mcp_server(name="firefly", version="1.0.0", tools=tools)

    return ToolModuleEntry(
        name="firefly",
        configure=configure_firefly,
        create_tools=create_tools,
        create_mcp_server=create_mcp_server,
        requires_env=["FIREFLY_URL"],
        supports_per_agent=False,
    )


# All module definitions — registered by server.py at startup
TOOL_MODULE_DEFS: list[ToolModuleEntry] = [
    _obsidian_entry(),
    _email_entry(),
    _drive_entry(),
    _ha_entry(),
    _paperless_entry(),
    _firefly_entry(),
]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_capabilities_modules.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/capabilities/modules.py tests/gateway/test_capabilities_modules.py
git commit -m "feat(capabilities): register existing tool modules as ToolModuleEntry definitions"
```

---

### Task 7: Feature Flag and Server.py Switchover

**Files:**
- Modify: `corvus/server.py` — add `USE_AGENTS_HUB` flag, new `_build_options_hub()`, comparison path
- Modify: `corvus/router.py` — accept optional `AgentRegistry`, read from it when available
- Create: `tests/gateway/test_hub_switchover.py`

**Step 1: Write the failing tests**

```python
# tests/gateway/test_hub_switchover.py
"""Tests for the USE_AGENTS_HUB feature flag switchover."""

import os
import pytest
from pathlib import Path

import yaml


class TestRouterAgentFromRegistry:
    def test_valid_agents_from_registry(self, tmp_path):
        from corvus.agents.registry import AgentRegistry
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        for name in ["personal", "work", "homelab"]:
            data = {"name": name, "description": f"{name} agent", "memory": {"own_domain": name}}
            (agents_dir / f"{name}.yaml").write_text(yaml.dump(data))

        reg = AgentRegistry(config_dir=agents_dir)
        reg.load()

        from corvus.router import RouterAgent
        ra = RouterAgent(registry=reg)
        valid = ra.get_valid_agents()
        assert valid == {"personal", "work", "homelab"}

    def test_valid_agents_fallback_without_registry(self):
        from corvus.router import RouterAgent, VALID_AGENTS
        ra = RouterAgent()
        valid = ra.get_valid_agents()
        assert valid == VALID_AGENTS
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_hub_switchover.py -v`
Expected: FAIL — `RouterAgent` doesn't accept `registry` yet

**Step 3: Update RouterAgent**

Modify `corvus/router.py` to accept an optional `AgentRegistry` and add `get_valid_agents()`:

At `__init__` (around line 49), add `registry` parameter:
```python
def __init__(self, api_key=None, model=None, base_url=None, registry=None):
    # ... existing init ...
    self._registry = registry

def get_valid_agents(self) -> set[str]:
    if self._registry is not None:
        return {s.name for s in self._registry.list_enabled()}
    return VALID_AGENTS
```

In `parse_response()` (around line 59), replace `VALID_AGENTS` usage with `self.get_valid_agents()`.

In `classify()` (around line 79), use `self.get_valid_agents()` for the routing prompt if registry is available.

**Step 4: Update server.py**

Add near the top of `server.py` (after existing imports):
```python
USE_AGENTS_HUB = os.environ.get("USE_AGENTS_HUB", "").lower() in ("1", "true", "yes")
```

Add a new function `_build_options_hub()` that uses AgentsHub:
```python
def _build_options_hub(user: str, websocket=None) -> ClaudeAgentOptions:
    """Hub-driven build_options — used when USE_AGENTS_HUB=true."""
    return _agents_hub.build_options(user, websocket)
```

Initialize the hub at startup (inside lifespan or module-level, gated by flag).

Update the WebSocket handler to call the appropriate path:
```python
if USE_AGENTS_HUB:
    options = _build_options_hub(user, websocket=websocket)
else:
    options = build_options(user, websocket=websocket)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_hub_switchover.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/router.py corvus/server.py tests/gateway/test_hub_switchover.py
git commit -m "feat(server): add USE_AGENTS_HUB feature flag with safe switchover path"
```

---

## Phase 3: Memory Cleanup

### Task 8: SessionManager Extraction

**Files:**
- Create: `corvus/session_manager.py`
- Create: `tests/gateway/test_session_manager.py`

**Step 1: Write the failing tests**

```python
# tests/gateway/test_session_manager.py
"""Tests for SessionManager — session CRUD extracted from MemoryEngine."""

import pytest
from datetime import UTC, datetime
from pathlib import Path

from corvus.session_manager import SessionManager


class TestSessionManager:
    @pytest.fixture()
    def manager(self, tmp_path) -> SessionManager:
        return SessionManager(db_path=tmp_path / "sessions.sqlite")

    def test_start_and_get_session(self, manager):
        sid = "test-session-1"
        manager.start(sid, user="thomas", agent_name="personal")
        session = manager.get(sid)
        assert session is not None
        assert session["id"] == sid
        assert session["user"] == "thomas"

    def test_end_session(self, manager):
        sid = "test-session-2"
        manager.start(sid, user="thomas", agent_name="work")
        manager.end(sid, message_count=5, tool_count=3, agents_used=["work", "personal"])
        session = manager.get(sid)
        assert session["ended_at"] is not None
        assert session["message_count"] == 5
        assert "work" in session["agents_used"]

    def test_list_sessions(self, manager):
        for i in range(3):
            manager.start(f"s-{i}", user="thomas", agent_name="personal")
        sessions = manager.list(limit=10)
        assert len(sessions) == 3

    def test_delete_session(self, manager):
        manager.start("del-me", user="thomas", agent_name="personal")
        manager.delete("del-me")
        assert manager.get("del-me") is None

    def test_rename_session(self, manager):
        manager.start("rename-me", user="thomas", agent_name="personal")
        manager.rename("rename-me", "New Title")
        session = manager.get("rename-me")
        assert session["summary"] == "New Title"

    def test_list_with_user_filter(self, manager):
        manager.start("s-1", user="thomas", agent_name="personal")
        manager.start("s-2", user="other", agent_name="work")
        sessions = manager.list(user="thomas")
        assert len(sessions) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gateway/test_session_manager.py -v`
Expected: FAIL

**Step 3: Write the implementation**

Extract session-related code from `scripts/common/memory_engine.py` into `corvus/session_manager.py`. The `SessionManager` owns the `sessions` table and nothing else. It creates its own schema on init (just the `sessions` table). All methods are synchronous (matching current usage).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gateway/test_session_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus/session_manager.py tests/gateway/test_session_manager.py
git commit -m "feat(memory): extract SessionManager from MemoryEngine"
```

---

### Task 9: Schema Migration Script

**Files:**
- Create: `scripts/migrate_memory_schema.py`
- Create: `tests/mcp_servers/test_schema_migration.py`

Write the one-time migration script per the design doc section 7.5. The script:
1. Backs up the SQLite file
2. Migrates `chunks` rows → new `memories` schema (with UUID record_ids, domain="shared", visibility="shared")
3. Migrates old `memories` rows (if they exist with old schema)
4. Drops old tables: `chunks`, `chunks_fts`, `embedding_cache`, `files`, `meta`
5. Rebuilds `memories_fts` from migrated data

Test with a real SQLite database seeded with old-schema data, verify migration produces correct new-schema records.

**Step 1: Write the test, Step 2: Run to fail, Step 3: Implement, Step 4: Run to pass, Step 5: Commit**

```bash
git commit -m "feat(memory): add schema migration script for old MemoryEngine → MemoryHub"
```

---

### Task 10: Fix Session Extraction Identity

**Files:**
- Modify: `corvus/session.py` — add `primary_agent()` to `SessionTranscript`
- Modify: `corvus/server.py` — pass correct agent name to extraction
- Modify: `tests/gateway/test_session.py` — add test for primary_agent

**Step 1: Write failing test**

```python
def test_primary_agent_returns_most_used():
    transcript = SessionTranscript(
        user="thomas",
        session_id="test",
        messages=[],
        started_at=datetime.now(UTC),
        agents_used={"personal", "work", "personal"},  # personal used more
    )
    # Need to track counts, not just set — update agents_used to be a Counter or list
```

Note: `agents_used` is currently a `set[str]`. To determine the "primary" agent, it needs to be a list or Counter. The simplest fix: add an `agent_counts: dict[str, int]` field, or change the type. Design choice: add `agent_counts` field, keep `agents_used` as the set for backward compat.

**Step 2-5:** Implement, test, commit.

```bash
git commit -m "fix(session): pass correct agent identity to memory extraction"
```

---

### Task 11: Switch Session Endpoints to SessionManager

**Files:**
- Modify: `corvus/server.py` — replace `get_memory_engine()` with `SessionManager` in session endpoints and WebSocket handler
- Modify: existing session tests if needed

Switch the 5 REST endpoints (`/api/sessions`, `/api/sessions/{id}`, etc.) and the WebSocket connect/disconnect hooks to use `SessionManager` instead of `MemoryEngine`.

```bash
git commit -m "refactor(server): switch session endpoints from MemoryEngine to SessionManager"
```

---

## Phase 4: REST + Cleanup

### Task 12: Agent Management REST Endpoints

**Files:**
- Modify: `corvus/server.py` — add 6 REST endpoints for agent CRUD
- Create: `tests/gateway/test_agent_endpoints.py`

Add the endpoints from the design doc section 8.1:
```
GET    /api/agents              → hub.list_agents()
GET    /api/agents/{name}       → hub.get_agent(name)
POST   /api/agents              → hub.create_agent(spec)
PATCH  /api/agents/{name}       → hub.update_agent(name, patch)
DELETE /api/agents/{name}       → hub.deactivate_agent(name)
POST   /api/agents/reload       → hub.reload()
GET    /api/capabilities        → capabilities.list_available()
GET    /api/capabilities/{name} → capabilities.health(name)
```

Test with `httpx.AsyncClient` against the FastAPI app (real HTTP, no mocks).

```bash
git commit -m "feat(api): add agent management and capabilities REST endpoints"
```

---

### Task 13: Delete Old Code

**Files:**
- Delete: `corvus/agents.py`
- Delete: `corvus/agent_config.py`
- Delete: `corvus/providers/registry.py` (and `corvus/providers/` if empty)
- Delete: `scripts/common/memory_engine.py`
- Delete: `scripts/memory_search.py`
- Modify: `corvus/server.py` — remove old imports, old `build_options()`, old `build_system_prompt()`, `get_memory_engine()`, `get_memory_hub()` (replaced by hub)
- Modify: `corvus/hooks.py` — remove `CONFIRM_GATED_TOOLS` hardcoded set, derive from registry
- Modify: `corvus/supervisor.py` — update to use `CapabilitiesRegistry` instead of `ToolProviderRegistry`
- Remove: `USE_AGENTS_HUB` feature flag (old path deleted)
- Update: all test files that import from deleted modules

**Step 1:** Grep for all imports of deleted modules:
```bash
uv run pytest tests/ -v  # Run full suite BEFORE deleting anything
```

**Step 2:** Delete files one at a time, fix imports, run tests after each deletion.

**Step 3:** Remove feature flag — set hub path as the only path.

**Step 4:** Full test run

Run: `uv run pytest tests/ -v`
Expected: All PASS (871+ tests)

**Step 5: Commit**

```bash
git commit -m "refactor: delete old hardcoded agent/memory code, hub is now the only path"
```

---

## Summary

| Phase | Tasks | Commits | Risk |
|-------|-------|---------|------|
| 1: Foundation | 1-4 | 4 | None — no behavior change |
| 2: Switchover | 5-7 | 3 | Medium — feature flag protects |
| 3: Memory | 8-11 | 4 | Medium — schema migration needs backup |
| 4: Cleanup | 12-13 | 2 | Low — old code already unused behind flag |

Total: **13 tasks, ~13 commits**

Each task is independently testable and committable. Phase 1 can run with zero risk to the existing system. Phase 2's feature flag means the switchover is reversible. Phase 3's migration script backs up before modifying data. Phase 4 only deletes code that's already unreachable.
