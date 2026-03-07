"""Behavioral tests for custom provider modal."""

from corvus.cli.screens.custom_modal import CustomModal


class TestCustomModal:
    def test_modal_has_section(self) -> None:
        modal = CustomModal(section="provider")
        assert modal.section == "provider"

    def test_modal_accepts_service_section(self) -> None:
        modal = CustomModal(section="service")
        assert modal.section == "service"
