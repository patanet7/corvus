"""Behavioral tests for BreakGlassManager — Argon2id passphrase + rate limiting.

NO mocks — real Argon2id hashing, real file I/O, real time.sleep.
All file operations use pytest tmp_path fixture.
"""

import time
from pathlib import Path

from corvus.break_glass import BreakGlassManager

# ---------------------------------------------------------------------------
# TestPassphraseSetAndVerify
# ---------------------------------------------------------------------------


class TestPassphraseSetAndVerify:
    """Test passphrase hashing and verification with real Argon2id."""

    def test_set_and_verify_correct_passphrase(self, tmp_path: Path):
        """set_passphrase then verify_passphrase with the same string returns True."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("correct-horse-battery-staple")
        assert mgr.verify_passphrase("correct-horse-battery-staple") is True

    def test_verify_wrong_passphrase(self, tmp_path: Path):
        """verify_passphrase with the wrong string returns False."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("correct-horse-battery-staple")
        assert mgr.verify_passphrase("wrong-passphrase") is False

    def test_hash_file_created_on_disk(self, tmp_path: Path):
        """After set_passphrase, passphrase.hash exists and starts with $argon2id$."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("my-secret-phrase")

        hash_file = tmp_path / "passphrase.hash"
        assert hash_file.exists()
        content = hash_file.read_text()
        assert content.startswith("$argon2id$")

    def test_hash_file_permissions(self, tmp_path: Path):
        """passphrase.hash is created with mode 0600 (owner read/write only)."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("my-secret-phrase")

        hash_file = tmp_path / "passphrase.hash"
        mode = hash_file.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0600, got {oct(mode)}"

    def test_verify_loads_from_disk(self, tmp_path: Path):
        """A new BreakGlassManager instance can verify from the persisted hash file."""
        mgr1 = BreakGlassManager(config_dir=tmp_path)
        mgr1.set_passphrase("persistent-passphrase")

        # Create a completely new instance pointing at the same config_dir
        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.verify_passphrase("persistent-passphrase") is True
        assert mgr2.verify_passphrase("wrong-one") is False

    def test_no_passphrase_set_returns_false(self, tmp_path: Path):
        """verify_passphrase returns False when no passphrase has been set."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        assert mgr.verify_passphrase("anything") is False

    def test_has_passphrase(self, tmp_path: Path):
        """has_passphrase returns True only after set_passphrase is called."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        assert mgr.has_passphrase() is False

        mgr.set_passphrase("now-it-exists")
        assert mgr.has_passphrase() is True

        # New instance should also see it
        mgr2 = BreakGlassManager(config_dir=tmp_path)
        assert mgr2.has_passphrase() is True


# ---------------------------------------------------------------------------
# TestRateLimiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test escalating rate-limited lockout with real file persistence."""

    def test_three_failures_triggers_lockout(self, tmp_path: Path):
        """3 failed attempts trigger lockout; even correct passphrase is rejected."""
        # Use short threshold: 3 failures -> 1 second lockout
        mgr = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(3, 1)])
        mgr.set_passphrase("good-passphrase")

        # Three wrong attempts
        for _ in range(3):
            assert mgr.verify_passphrase("wrong") is False

        # Now locked out — correct passphrase should be rejected
        assert mgr.is_locked_out() is True
        assert mgr.verify_passphrase("good-passphrase") is False

    def test_lockout_expires(self, tmp_path: Path):
        """After lockout period elapses, verification works again."""
        # 2 failures -> 1 second lockout
        mgr = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(2, 1)])
        mgr.set_passphrase("good-passphrase")

        # Two wrong attempts -> locked
        for _ in range(2):
            mgr.verify_passphrase("wrong")

        assert mgr.is_locked_out() is True

        # Wait for lockout to expire
        time.sleep(1.5)

        # Should be unlocked now
        assert mgr.is_locked_out() is False
        assert mgr.verify_passphrase("good-passphrase") is True

    def test_lockout_persists_to_disk(self, tmp_path: Path):
        """Lockout state survives creating a new BreakGlassManager instance."""
        mgr1 = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(2, 60)])
        mgr1.set_passphrase("good-passphrase")

        # Two wrong attempts
        for _ in range(2):
            mgr1.verify_passphrase("wrong")

        assert mgr1.is_locked_out() is True

        # New instance with same config_dir should still be locked
        mgr2 = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(2, 60)])
        assert mgr2.is_locked_out() is True
        assert mgr2.verify_passphrase("good-passphrase") is False

    def test_successful_verify_resets_failure_count(self, tmp_path: Path):
        """A correct verification resets the failure counter."""
        # 3 failures -> lockout
        mgr = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(3, 60)])
        mgr.set_passphrase("good-passphrase")

        # 2 wrong attempts (not yet locked)
        mgr.verify_passphrase("wrong")
        mgr.verify_passphrase("wrong")
        assert mgr.is_locked_out() is False

        # Correct passphrase resets the counter
        assert mgr.verify_passphrase("good-passphrase") is True

        # 2 more wrong attempts — should NOT be locked because counter was reset
        mgr.verify_passphrase("wrong")
        mgr.verify_passphrase("wrong")
        assert mgr.is_locked_out() is False


# ---------------------------------------------------------------------------
# TestBreakGlassSession
# ---------------------------------------------------------------------------


class TestBreakGlassSession:
    """Test per-session break-glass activation/deactivation."""

    def test_activate_with_correct_passphrase(self, tmp_path: Path):
        """activate() with correct passphrase returns True and sets is_active."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("activate-me")

        assert mgr.activate("activate-me") is True
        assert mgr.is_active() is True

    def test_activate_fails_with_wrong_passphrase(self, tmp_path: Path):
        """activate() with wrong passphrase returns False, is_active stays False."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("activate-me")

        assert mgr.activate("wrong-phrase") is False
        assert mgr.is_active() is False

    def test_deactivate(self, tmp_path: Path):
        """After activate then deactivate, is_active returns False."""
        mgr = BreakGlassManager(config_dir=tmp_path)
        mgr.set_passphrase("activate-me")

        mgr.activate("activate-me")
        assert mgr.is_active() is True

        mgr.deactivate()
        assert mgr.is_active() is False

    def test_activate_rejected_during_lockout(self, tmp_path: Path):
        """activate() returns False when locked out, even with correct passphrase."""
        mgr = BreakGlassManager(config_dir=tmp_path, lockout_thresholds=[(2, 60)])
        mgr.set_passphrase("good-passphrase")

        # Trigger lockout
        mgr.verify_passphrase("wrong")
        mgr.verify_passphrase("wrong")
        assert mgr.is_locked_out() is True

        # activate with correct passphrase should be rejected
        assert mgr.activate("good-passphrase") is False
        assert mgr.is_active() is False
