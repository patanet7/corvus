"""Behavioral tests for capabilities registry config loading.

NO mocks. Uses real YAML files on disk and real registry/module entries.
"""

from pathlib import Path

from corvus.capabilities.config import CapabilitiesConfig
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry


def _module_order() -> list[str]:
    return [module.name for module in TOOL_MODULE_DEFS]


class TestCapabilitiesConfig:
    def test_missing_file_defaults_to_all_enabled(self, tmp_path: Path):
        cfg = CapabilitiesConfig.from_file(tmp_path / "missing.yaml")
        enabled = cfg.enabled_modules(_module_order())
        assert enabled == _module_order()

    def test_disable_drive_via_config(self, tmp_path: Path):
        path = tmp_path / "capabilities.yaml"
        path.write_text(
            "\n".join(
                [
                    "modules:",
                    "  drive:",
                    "    enabled: false",
                ]
            )
        )

        cfg = CapabilitiesConfig.from_file(path)
        enabled = cfg.enabled_modules(_module_order())

        assert "drive" not in enabled
        assert "email" in enabled
        assert "obsidian" in enabled

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path: Path):
        path = tmp_path / "capabilities.yaml"
        path.write_text("- not-a-mapping")

        cfg = CapabilitiesConfig.from_file(path)
        enabled = cfg.enabled_modules(_module_order())
        assert enabled == _module_order()

    def test_strict_invalid_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "capabilities.yaml"
        path.write_text("- not-a-mapping")

        try:
            CapabilitiesConfig.from_file(path, strict=True)
            raised = False
        except ValueError:
            raised = True
        assert raised is True


class TestCapabilitiesRegistryFromConfig:
    def test_registry_respects_disabled_drive(self, tmp_path: Path):
        path = tmp_path / "capabilities.yaml"
        path.write_text(
            "\n".join(
                [
                    "modules:",
                    "  drive:",
                    "    enabled: false",
                    "  email:",
                    "    enabled: true",
                ]
            )
        )

        cfg = CapabilitiesConfig.from_file(path)
        enabled_names = cfg.enabled_modules(_module_order())
        by_name = {module.name: module for module in TOOL_MODULE_DEFS}

        registry = CapabilitiesRegistry()
        for module_name in enabled_names:
            registry.register(module_name, by_name[module_name])

        registered = set(registry.list_available())
        assert "drive" not in registered
        assert "email" in registered
