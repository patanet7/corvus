"""Behavioral tests for MemoryConfig loading and runtime overlay wiring."""

from __future__ import annotations

from pathlib import Path

from corvus.gateway.runtime import _build_memory_overlays
from corvus.memory.backends.cognee import CogneeBackend
from corvus.memory.config import BackendConfig, MemoryConfig


class TestMemoryConfig:
    def test_missing_file_uses_default_db_path(self, tmp_path: Path) -> None:
        config = MemoryConfig.from_file(
            tmp_path / "missing-memory.yaml",
            default_db_path=tmp_path / "main.sqlite",
        )
        assert config.primary_db_path == tmp_path / "main.sqlite"
        assert config.overlays == []

    def test_loads_overlays_and_relative_primary_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config" / "memory.yaml"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(
            "\n".join(
                [
                    "primary_db_path: ../state/memory.sqlite",
                    "decay_half_life_days: 20",
                    "evergreen_threshold: 0.8",
                    "mmr_lambda: 0.6",
                    "audit_enabled: true",
                    "overlays:",
                    "  - name: cognee",
                    "    enabled: true",
                    "    weight: 0.42",
                    "    settings:",
                    "      data_dir: /tmp/cognee-data",
                    "  - name: unknown-overlay",
                    "    enabled: false",
                    "    weight: 0.9",
                ]
            )
        )

        config = MemoryConfig.from_file(
            cfg_path,
            default_db_path=tmp_path / "fallback.sqlite",
        )

        assert config.primary_db_path == tmp_path / "state" / "memory.sqlite"
        assert config.decay_half_life_days == 20.0
        assert config.evergreen_threshold == 0.8
        assert config.mmr_lambda == 0.6
        assert config.audit_enabled is True
        assert len(config.overlays) == 2
        assert len(config.enabled_overlays()) == 1
        assert config.enabled_overlays()[0].name == "cognee"
        assert config.enabled_overlays()[0].settings["data_dir"] == "/tmp/cognee-data"

    def test_invalid_yaml_falls_back_in_non_strict_mode(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "memory.yaml"
        cfg_path.write_text("- bad-shape")
        config = MemoryConfig.from_file(
            cfg_path,
            default_db_path=tmp_path / "fallback.sqlite",
            strict=False,
        )
        assert config.primary_db_path == tmp_path / "fallback.sqlite"
        assert config.overlays == []

    def test_invalid_yaml_raises_in_strict_mode(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "memory.yaml"
        cfg_path.write_text("- bad-shape")
        raised = False
        try:
            MemoryConfig.from_file(
                cfg_path,
                default_db_path=tmp_path / "fallback.sqlite",
                strict=True,
            )
        except ValueError:
            raised = True
        assert raised is True


class TestRuntimeOverlayFactory:
    def test_builds_cognee_overlay_from_enabled_config(self, tmp_path: Path) -> None:
        config = MemoryConfig(
            primary_db_path=tmp_path / "main.sqlite",
            overlays=[
                BackendConfig(
                    name="cognee",
                    enabled=True,
                    weight=0.5,
                    settings={"data_dir": str(tmp_path / "cognee")},
                ),
                BackendConfig(
                    name="unknown",
                    enabled=True,
                    weight=0.1,
                ),
            ],
        )

        overlays = _build_memory_overlays(config)
        assert len(overlays) == 1
        assert isinstance(overlays[0], CogneeBackend)
        assert overlays[0].weight == 0.5
        assert overlays[0].data_dir == tmp_path / "cognee"
