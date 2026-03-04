"""Behavioral tests for AgentRegistry — load, validate, CRUD, reload.

NO mocks. All tests use real YAML files written to tmp_path with real
filesystem operations and real YAML parsing/writing.

Covers:
- Loading from directory (multiple specs, empty dir, nonexistent dir)
- Get existing/missing agent
- List enabled (excludes disabled)
- List all (includes disabled)
- Validation rules (empty name, empty description, invalid complexity,
  missing memory own_domain)
- CRUD: create, create duplicate raises, update, deactivate
- Reload: detect new, removed, and changed files; report errors
- Persistence: create/update/deactivate write YAML to disk
"""

from pathlib import Path

import pytest
import yaml

from corvus.agents.registry import AgentRegistry, ReloadResult
from corvus.agents.spec import AgentMemoryConfig, AgentSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_spec(config_dir: Path, name: str, **overrides) -> Path:
    """Write a minimal valid agent spec YAML file and return its path."""
    data = {
        "name": name,
        "description": f"{name} agent",
        "enabled": True,
        "models": {"complexity": "medium"},
        "memory": {"own_domain": name},
    }
    data.update(overrides)
    path = config_dir / f"{name}.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# 1. ReloadResult dataclass
# ---------------------------------------------------------------------------


class TestReloadResult:
    """ReloadResult fields should default to empty collections."""

    def test_defaults(self):
        r = ReloadResult()
        assert r.added == []
        assert r.removed == []
        assert r.changed == []
        assert r.errors == {}

    def test_custom_values(self):
        r = ReloadResult(
            added=["a"],
            removed=["b"],
            changed=["c"],
            errors={"d": "bad"},
        )
        assert r.added == ["a"]
        assert r.removed == ["b"]
        assert r.changed == ["c"]
        assert r.errors == {"d": "bad"}


# ---------------------------------------------------------------------------
# 2. Load from directory
# ---------------------------------------------------------------------------


class TestLoad:
    """load() reads all *.yaml files from config_dir."""

    def test_load_multiple_specs(self, tmp_path):
        _write_spec(tmp_path, "homelab")
        _write_spec(tmp_path, "finance")
        _write_spec(tmp_path, "work")

        reg = AgentRegistry(tmp_path)
        reg.load()

        assert len(reg.list_all()) == 3
        names = {s.name for s in reg.list_all()}
        assert names == {"homelab", "finance", "work"}

    def test_load_empty_dir(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()
        assert reg.list_all() == []

    def test_load_nonexistent_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        reg = AgentRegistry(missing)
        reg.load()
        assert reg.list_all() == []

    def test_load_skips_invalid_yaml(self, tmp_path):
        _write_spec(tmp_path, "good")
        # Write invalid YAML (not a dict)
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("just a string, not a mapping")

        reg = AgentRegistry(tmp_path)
        reg.load()

        assert len(reg.list_all()) == 1
        assert reg.list_all()[0].name == "good"

    def test_load_skips_validation_failures(self, tmp_path):
        _write_spec(tmp_path, "good")
        # Write a spec with empty name (validation failure)
        bad_path = tmp_path / "empty_name.yaml"
        bad_data = {"name": "", "description": "Has empty name"}
        with open(bad_path, "w") as f:
            yaml.dump(bad_data, f)

        reg = AgentRegistry(tmp_path)
        reg.load()

        assert len(reg.list_all()) == 1
        assert reg.list_all()[0].name == "good"

    def test_load_ignores_non_yaml_files(self, tmp_path):
        _write_spec(tmp_path, "agent1")
        # Write a .txt file that should be ignored
        (tmp_path / "readme.txt").write_text("not a yaml")

        reg = AgentRegistry(tmp_path)
        reg.load()
        assert len(reg.list_all()) == 1

    def test_load_clears_previous_state(self, tmp_path):
        _write_spec(tmp_path, "first")
        reg = AgentRegistry(tmp_path)
        reg.load()
        assert len(reg.list_all()) == 1

        # Remove old file, add new one
        (tmp_path / "first.yaml").unlink()
        _write_spec(tmp_path, "second")
        reg.load()
        assert len(reg.list_all()) == 1
        assert reg.list_all()[0].name == "second"


# ---------------------------------------------------------------------------
# 3. Get
# ---------------------------------------------------------------------------


class TestGet:
    """get() returns an AgentSpec by name, or None if missing."""

    def test_get_existing(self, tmp_path):
        _write_spec(tmp_path, "homelab")
        reg = AgentRegistry(tmp_path)
        reg.load()

        spec = reg.get("homelab")
        assert spec is not None
        assert spec.name == "homelab"

    def test_get_missing(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()
        assert reg.get("nonexistent") is None

    def test_get_returns_correct_spec(self, tmp_path):
        _write_spec(tmp_path, "finance", description="Finance domain agent")
        _write_spec(tmp_path, "work", description="Work domain agent")
        reg = AgentRegistry(tmp_path)
        reg.load()

        finance = reg.get("finance")
        assert finance.description == "Finance domain agent"

        work = reg.get("work")
        assert work.description == "Work domain agent"


# ---------------------------------------------------------------------------
# 4. List enabled / list all
# ---------------------------------------------------------------------------


class TestListMethods:
    """list_enabled() excludes disabled agents; list_all() includes all."""

    def test_list_enabled_excludes_disabled(self, tmp_path):
        _write_spec(tmp_path, "active1")
        _write_spec(tmp_path, "active2")
        _write_spec(tmp_path, "inactive", enabled=False)

        reg = AgentRegistry(tmp_path)
        reg.load()

        enabled = reg.list_enabled()
        assert len(enabled) == 2
        enabled_names = {s.name for s in enabled}
        assert "inactive" not in enabled_names

    def test_list_all_includes_disabled(self, tmp_path):
        _write_spec(tmp_path, "active")
        _write_spec(tmp_path, "inactive", enabled=False)

        reg = AgentRegistry(tmp_path)
        reg.load()

        all_specs = reg.list_all()
        assert len(all_specs) == 2
        names = {s.name for s in all_specs}
        assert names == {"active", "inactive"}

    def test_list_enabled_all_disabled(self, tmp_path):
        _write_spec(tmp_path, "off1", enabled=False)
        _write_spec(tmp_path, "off2", enabled=False)

        reg = AgentRegistry(tmp_path)
        reg.load()
        assert reg.list_enabled() == []

    def test_list_all_empty(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()
        assert reg.list_all() == []


# ---------------------------------------------------------------------------
# 5. Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """validate() returns a list of error messages for invalid specs."""

    def test_valid_spec_no_errors(self, tmp_path):
        spec = AgentSpec(
            name="homelab",
            description="Homelab agent",
            models=AgentSpec(
                name="",  # won't matter, we construct AgentModelConfig below
                description="",
            ).models,  # default AgentModelConfig
            memory=AgentMemoryConfig(own_domain="homelab"),
        )
        # Fix: construct properly
        spec = AgentSpec(
            name="homelab",
            description="Homelab agent",
            memory=AgentMemoryConfig(own_domain="homelab"),
        )
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert errors == []

    def test_empty_name(self, tmp_path):
        spec = AgentSpec(name="", description="Valid description")
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert any("name" in e.lower() for e in errors)

    def test_whitespace_only_name(self, tmp_path):
        spec = AgentSpec(name="   ", description="Valid description")
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert any("name" in e.lower() for e in errors)

    def test_empty_description(self, tmp_path):
        spec = AgentSpec(name="test", description="")
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert any("description" in e.lower() for e in errors)

    def test_whitespace_only_description(self, tmp_path):
        spec = AgentSpec(name="test", description="   ")
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert any("description" in e.lower() for e in errors)

    def test_invalid_complexity(self, tmp_path):
        from corvus.agents.spec import AgentModelConfig

        # AgentModelConfig now validates complexity in __post_init__
        with pytest.raises(ValueError, match="complexity"):
            AgentModelConfig(complexity="extreme")

    def test_valid_complexity_values(self, tmp_path):
        from corvus.agents.spec import AgentModelConfig

        reg = AgentRegistry(tmp_path)
        for level in ("high", "medium", "low"):
            spec = AgentSpec(
                name="test",
                description="Valid",
                models=AgentModelConfig(complexity=level),
            )
            errors = reg.validate(spec)
            assert errors == [], f"complexity={level!r} should be valid"

    def test_empty_memory_own_domain(self, tmp_path):
        spec = AgentSpec(
            name="test",
            description="Valid",
            memory=AgentMemoryConfig(own_domain=""),
        )
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert any("own_domain" in e.lower() for e in errors)

    def test_memory_none_is_valid(self, tmp_path):
        spec = AgentSpec(name="test", description="Valid")
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert errors == []

    def test_multiple_errors_returned(self, tmp_path):
        # AgentModelConfig validates complexity in __post_init__, so we use a valid
        # complexity here and test that name + description produce multiple errors
        spec = AgentSpec(
            name="",
            description="",
        )
        reg = AgentRegistry(tmp_path)
        errors = reg.validate(spec)
        assert len(errors) >= 2  # name, description


# ---------------------------------------------------------------------------
# 6. Create
# ---------------------------------------------------------------------------


class TestCreate:
    """create() validates, persists to YAML, adds to in-memory dict."""

    def test_create_new_agent(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        spec = AgentSpec(
            name="docs",
            description="Document management agent",
            memory=AgentMemoryConfig(own_domain="docs"),
        )
        reg.create(spec)

        # In-memory
        assert reg.get("docs") is not None
        assert reg.get("docs").description == "Document management agent"

        # Persisted to disk
        yaml_path = tmp_path / "docs.yaml"
        assert yaml_path.exists()
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "docs"

    def test_create_duplicate_raises(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        spec = AgentSpec(
            name="homelab",
            description="Homelab agent",
            memory=AgentMemoryConfig(own_domain="homelab"),
        )
        reg.create(spec)

        with pytest.raises(ValueError, match="already exists"):
            reg.create(spec)

    def test_create_invalid_spec_raises(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        spec = AgentSpec(name="", description="No name agent")

        with pytest.raises(ValueError, match="validation"):
            reg.create(spec)

    def test_create_does_not_persist_on_validation_failure(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        spec = AgentSpec(name="", description="No name agent")
        with pytest.raises(ValueError):
            reg.create(spec)

        # Nothing written to disk
        yaml_files = list(tmp_path.glob("*.yaml"))
        assert yaml_files == []


# ---------------------------------------------------------------------------
# 7. Update
# ---------------------------------------------------------------------------


class TestUpdate:
    """update() applies a partial patch, re-validates, and persists."""

    def test_update_description(self, tmp_path):
        _write_spec(tmp_path, "homelab")
        reg = AgentRegistry(tmp_path)
        reg.load()

        updated = reg.update("homelab", {"description": "Updated description"})
        assert updated.description == "Updated description"

        # Persisted
        with open(tmp_path / "homelab.yaml") as f:
            data = yaml.safe_load(f)
        assert data["description"] == "Updated description"

    def test_update_nonexistent_raises(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        with pytest.raises(KeyError, match="not found"):
            reg.update("nonexistent", {"description": "New"})

    def test_update_preserves_unpatched_fields(self, tmp_path):
        _write_spec(tmp_path, "finance", description="Finance agent")
        reg = AgentRegistry(tmp_path)
        reg.load()

        reg.update("finance", {"enabled": False})
        spec = reg.get("finance")
        assert spec.enabled is False
        assert spec.description == "Finance agent"  # Unchanged
        assert spec.name == "finance"  # Unchanged

    def test_update_invalid_patch_raises(self, tmp_path):
        _write_spec(tmp_path, "work")
        reg = AgentRegistry(tmp_path)
        reg.load()

        with pytest.raises(ValueError, match="validation"):
            reg.update("work", {"name": ""})

    def test_update_does_not_persist_on_validation_failure(self, tmp_path):
        _write_spec(tmp_path, "work")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Read original content
        original_content = (tmp_path / "work.yaml").read_text()

        with pytest.raises(ValueError):
            reg.update("work", {"name": ""})

        # File unchanged
        assert (tmp_path / "work.yaml").read_text() == original_content

    def test_update_returns_updated_spec(self, tmp_path):
        _write_spec(tmp_path, "personal")
        reg = AgentRegistry(tmp_path)
        reg.load()

        result = reg.update("personal", {"description": "Better description"})
        assert isinstance(result, AgentSpec)
        assert result.description == "Better description"


# ---------------------------------------------------------------------------
# 8. Deactivate
# ---------------------------------------------------------------------------


class TestDeactivate:
    """deactivate() sets enabled=false and persists."""

    def test_deactivate_sets_enabled_false(self, tmp_path):
        _write_spec(tmp_path, "homelab")
        reg = AgentRegistry(tmp_path)
        reg.load()

        assert reg.get("homelab").enabled is True
        reg.deactivate("homelab")
        assert reg.get("homelab").enabled is False

    def test_deactivate_persists(self, tmp_path):
        _write_spec(tmp_path, "docs")
        reg = AgentRegistry(tmp_path)
        reg.load()

        reg.deactivate("docs")

        with open(tmp_path / "docs.yaml") as f:
            data = yaml.safe_load(f)
        assert data["enabled"] is False

    def test_deactivate_removes_from_enabled_list(self, tmp_path):
        _write_spec(tmp_path, "finance")
        _write_spec(tmp_path, "work")
        reg = AgentRegistry(tmp_path)
        reg.load()

        assert len(reg.list_enabled()) == 2
        reg.deactivate("finance")
        enabled_names = {s.name for s in reg.list_enabled()}
        assert "finance" not in enabled_names
        assert "work" in enabled_names

    def test_deactivate_nonexistent_raises(self, tmp_path):
        reg = AgentRegistry(tmp_path)
        reg.load()

        with pytest.raises(KeyError, match="not found"):
            reg.deactivate("ghost")

    def test_deactivate_already_disabled_is_idempotent(self, tmp_path):
        _write_spec(tmp_path, "music", enabled=False)
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Should not raise
        reg.deactivate("music")
        assert reg.get("music").enabled is False


# ---------------------------------------------------------------------------
# 9. Reload
# ---------------------------------------------------------------------------


class TestReload:
    """reload() diffs files on disk vs in-memory state."""

    def test_reload_detects_new_file(self, tmp_path):
        _write_spec(tmp_path, "existing")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Add a new file after initial load
        _write_spec(tmp_path, "newcomer")
        result = reg.reload()

        assert "newcomer" in result.added
        assert reg.get("newcomer") is not None

    def test_reload_detects_removed_file(self, tmp_path):
        _write_spec(tmp_path, "keeper")
        _write_spec(tmp_path, "goner")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Remove a file after initial load
        (tmp_path / "goner.yaml").unlink()
        result = reg.reload()

        assert "goner" in result.removed
        assert reg.get("goner") is None

    def test_reload_detects_changed_file(self, tmp_path):
        _write_spec(tmp_path, "mutable", description="Original")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Modify the file
        _write_spec(tmp_path, "mutable", description="Updated on disk")
        result = reg.reload()

        assert "mutable" in result.changed
        assert reg.get("mutable").description == "Updated on disk"

    def test_reload_reports_errors_for_invalid_files(self, tmp_path):
        _write_spec(tmp_path, "good")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Add a new invalid file
        bad = tmp_path / "bad.yaml"
        bad.write_text("not: a: valid: spec: at: all")
        result = reg.reload()

        assert "bad" in result.errors or len(result.errors) > 0

    def test_reload_no_changes(self, tmp_path):
        _write_spec(tmp_path, "stable")
        reg = AgentRegistry(tmp_path)
        reg.load()

        result = reg.reload()
        assert result.added == []
        assert result.removed == []
        assert result.changed == []
        assert result.errors == {}

    def test_reload_mixed_changes(self, tmp_path):
        _write_spec(tmp_path, "stays")
        _write_spec(tmp_path, "modified", description="Old")
        _write_spec(tmp_path, "deleted")
        reg = AgentRegistry(tmp_path)
        reg.load()

        # Modify one, delete one, add one
        _write_spec(tmp_path, "modified", description="New")
        (tmp_path / "deleted.yaml").unlink()
        _write_spec(tmp_path, "brand_new")

        result = reg.reload()
        assert "brand_new" in result.added
        assert "deleted" in result.removed
        assert "modified" in result.changed


# ---------------------------------------------------------------------------
# 10. Persist round-trip
# ---------------------------------------------------------------------------


class TestPersistRoundTrip:
    """Created/updated specs should be loadable by a fresh registry."""

    def test_create_then_reload_in_new_registry(self, tmp_path):
        reg1 = AgentRegistry(tmp_path)
        reg1.load()
        reg1.create(
            AgentSpec(
                name="alpha",
                description="Alpha agent",
                memory=AgentMemoryConfig(own_domain="alpha"),
            )
        )

        # New registry instance loads the same directory
        reg2 = AgentRegistry(tmp_path)
        reg2.load()
        assert reg2.get("alpha") is not None
        assert reg2.get("alpha").description == "Alpha agent"

    def test_update_then_reload_in_new_registry(self, tmp_path):
        _write_spec(tmp_path, "beta")
        reg1 = AgentRegistry(tmp_path)
        reg1.load()
        reg1.update("beta", {"description": "Beta v2"})

        reg2 = AgentRegistry(tmp_path)
        reg2.load()
        assert reg2.get("beta").description == "Beta v2"

    def test_deactivate_then_reload_in_new_registry(self, tmp_path):
        _write_spec(tmp_path, "gamma")
        reg1 = AgentRegistry(tmp_path)
        reg1.load()
        reg1.deactivate("gamma")

        reg2 = AgentRegistry(tmp_path)
        reg2.load()
        assert reg2.get("gamma").enabled is False
