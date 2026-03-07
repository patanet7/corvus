"""Behavioral tests for setup app routing."""

from pathlib import Path

from corvus.cli.setup import is_first_run


class TestIsFirstRun:
    def test_first_run_when_no_credentials(self, tmp_path: Path) -> None:
        assert is_first_run(config_dir=tmp_path) is True

    def test_not_first_run_when_credentials_exist(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("{}")
        assert is_first_run(config_dir=tmp_path) is False
