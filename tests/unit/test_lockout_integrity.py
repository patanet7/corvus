"""Behavioral tests for HMAC integrity protection on lockout.json (F-012).

All tests use real temp directories on disk -- no mocks.
"""

import hashlib
import hmac as hmac_mod
import json
import os
from pathlib import Path

import pytest

from corvus.break_glass import BreakGlassManager


def _make_manager(tmp: Path) -> BreakGlassManager:
    """Create a BreakGlassManager rooted in *tmp* with a passphrase set."""
    mgr = BreakGlassManager(config_dir=tmp)
    mgr.set_passphrase("test-passphrase-42")
    return mgr


class TestLockoutHMACPresent:
    """Verify that the lockout file contains an HMAC envelope."""

    def test_hmac_written_on_save(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)

        # Trigger a failure so lockout.json is written
        mgr.verify_passphrase("wrong")

        lockout_file = tmp_path / "lockout.json"
        assert lockout_file.exists()

        envelope = json.loads(lockout_file.read_text())
        assert "hmac" in envelope, "lockout.json must contain an 'hmac' field"
        assert "data" in envelope, "lockout.json must contain a 'data' field"
        assert isinstance(envelope["hmac"], str)
        assert len(envelope["hmac"]) == 64  # SHA-256 hex digest length

    def test_hmac_matches_data(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.verify_passphrase("wrong")

        lockout_file = tmp_path / "lockout.json"
        envelope = json.loads(lockout_file.read_text())

        # Recompute HMAC with the same key (passphrase hash file)
        key = (tmp_path / "passphrase.hash").read_bytes()
        data_bytes = json.dumps(envelope["data"], sort_keys=True).encode()
        expected = hmac_mod.new(key, data_bytes, hashlib.sha256).hexdigest()

        assert envelope["hmac"] == expected


class TestTamperedLockoutDetection:
    """Verify that modifying lockout.json triggers fail-safe lockout."""

    def test_tampered_failure_count_detected(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.verify_passphrase("wrong")

        lockout_file = tmp_path / "lockout.json"
        envelope = json.loads(lockout_file.read_text())

        # Tamper: reset failures to 0 but keep old HMAC
        envelope["data"]["failures"] = 0
        lockout_file.write_text(json.dumps(envelope))

        # Reload -- should detect tampering and lock out
        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out(), (
            "Tampered lockout.json must cause fail-safe lockout"
        )

    def test_tampered_locked_until_detected(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        # Generate 3 failures to trigger a lockout
        for _ in range(3):
            mgr.verify_passphrase("wrong")

        lockout_file = tmp_path / "lockout.json"
        envelope = json.loads(lockout_file.read_text())

        # Tamper: set locked_until to 0 (unlock) but keep old HMAC
        envelope["data"]["locked_until"] = 0.0
        lockout_file.write_text(json.dumps(envelope))

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out(), (
            "Tampered locked_until must cause fail-safe lockout"
        )

    def test_replaced_hmac_detected(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.verify_passphrase("wrong")

        lockout_file = tmp_path / "lockout.json"
        envelope = json.loads(lockout_file.read_text())

        # Tamper: replace HMAC with a bogus value
        envelope["hmac"] = "a" * 64
        lockout_file.write_text(json.dumps(envelope))

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out(), (
            "Bogus HMAC must cause fail-safe lockout"
        )


class TestCorruptedHMACResetToLocked:
    """Verify that corrupt / missing HMAC resets to locked state."""

    def test_missing_hmac_field(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        lockout_file = tmp_path / "lockout.json"

        # Write data without HMAC (simulates legacy or hand-edited file)
        lockout_file.write_text(json.dumps({"data": {"failures": 0, "locked_until": 0.0}}))

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out()

    def test_missing_data_field(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        lockout_file = tmp_path / "lockout.json"

        # Write HMAC but no data key
        lockout_file.write_text(json.dumps({"hmac": "abc123"}))

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out()

    def test_legacy_plain_json_format(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        lockout_file = tmp_path / "lockout.json"

        # Simulate the old (pre-HMAC) lockout format
        lockout_file.write_text(json.dumps({"failures": 0, "locked_until": 0.0}))

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out(), (
            "Legacy lockout format without HMAC envelope must cause fail-safe lockout"
        )

    def test_garbage_content(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        lockout_file = tmp_path / "lockout.json"
        lockout_file.write_text("NOT-JSON-{{{{")

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.is_locked_out()


class TestValidLockoutLoads:
    """Verify that a properly signed lockout file loads correctly."""

    def test_valid_lockout_loads_failure_count(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)

        # Generate exactly 2 failures
        mgr.verify_passphrase("wrong")
        mgr.verify_passphrase("wrong")

        # Reload from disk
        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2._lockout_state["failures"] == 2

    def test_valid_lockout_not_locked_below_threshold(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)

        # 1 failure -- below the first threshold of 3
        mgr.verify_passphrase("wrong")

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert not mgr2.is_locked_out()
        assert mgr2._lockout_state["failures"] == 1

    def test_successful_verify_resets_and_persists(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.verify_passphrase("wrong")
        mgr.verify_passphrase("wrong")

        # Correct passphrase resets counter
        assert mgr.verify_passphrase("test-passphrase-42")

        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2._lockout_state["failures"] == 0
        assert not mgr2.is_locked_out()

    def test_no_lockout_file_means_clean_state(self, tmp_path: Path) -> None:
        mgr = BreakGlassManager(config_dir=tmp_path)
        assert not mgr.is_locked_out()
        assert mgr._lockout_state["failures"] == 0


class TestPassphrasePermissionCheck:
    """Verify that passphrase.hash permission checks work."""

    def test_correct_permissions_verify_succeeds(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        hash_file = tmp_path / "passphrase.hash"

        # Confirm file has 0o600
        import stat

        file_mode = stat.S_IMODE(os.stat(hash_file).st_mode)
        assert file_mode == 0o600

        # Verification should succeed
        assert mgr.verify_passphrase("test-passphrase-42")

    def test_wrong_permissions_still_verifies_but_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        mgr = _make_manager(tmp_path)
        hash_file = tmp_path / "passphrase.hash"

        # Widen permissions to simulate tampering
        os.chmod(hash_file, 0o644)

        with caplog.at_level(logging.WARNING, logger="corvus.break_glass"):
            result = mgr.verify_passphrase("test-passphrase-42")

        # Verification still succeeds (we warn, not block)
        assert result, "Verification should still succeed despite wrong perms"

        # Warning was emitted
        assert any("0644" in rec.message for rec in caplog.records), (
            "Expected a log warning mentioning permissions 0644"
        )

        # Restore
        os.chmod(hash_file, 0o600)
