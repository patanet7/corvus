"""Behavioral tests for the welcome screen."""

import subprocess

from corvus.cli.screens.welcome import get_or_create_age_keypair


class TestGetOrCreateAgeKeypair:
    def test_creates_keypair_if_missing(self, tmp_path) -> None:
        key_file = tmp_path / "age-key.txt"
        public_key = get_or_create_age_keypair(key_file)
        assert public_key.startswith("age1")
        assert key_file.exists()
        assert oct(key_file.stat().st_mode)[-3:] == "600"

    def test_reads_existing_keypair(self, tmp_path) -> None:
        key_file = tmp_path / "age-key.txt"
        # Generate a real keypair first
        subprocess.run(
            ["age-keygen", "-o", str(key_file)],
            capture_output=True,
            check=True,
        )
        key_file.chmod(0o600)
        public_key = get_or_create_age_keypair(key_file)
        assert public_key.startswith("age1")
