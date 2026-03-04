"""Break-glass mode — passphrase-protected privilege escalation.

Gateway-level only. Invisible to all agents. Per-session activation.
Uses Argon2id for passphrase hashing with escalating rate-limited lockout.
"""

import json
import os
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

DEFAULT_LOCKOUT_THRESHOLDS = [
    (3, 900),  # 3 failures -> 15 min
    (6, 3600),  # 6 failures -> 1 hour
    (9, 86400),  # 9 failures -> 24 hours
]


class BreakGlassManager:
    """Manages break-glass passphrase verification and session state.

    The passphrase hash is stored on disk at ``<config_dir>/passphrase.hash``
    with mode 0600.  Lockout state (failure count, locked_until) is persisted
    to ``<config_dir>/lockout.json`` so that restarts do not reset the counter.

    Activation is per-session (in-memory only) and is never persisted.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        lockout_thresholds: list[tuple[int, int]] | None = None,
    ):
        self._config_dir = config_dir or Path.home() / ".corvus"
        self._hash_file = self._config_dir / "passphrase.hash"
        self._lockout_file = self._config_dir / "lockout.json"
        self._lockout_thresholds = lockout_thresholds or DEFAULT_LOCKOUT_THRESHOLDS
        self._hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=2)
        self._active: bool = False
        self._lockout_state: dict = self._load_lockout_state()

    # ------------------------------------------------------------------
    # Passphrase management
    # ------------------------------------------------------------------

    def set_passphrase(self, passphrase: str) -> None:
        """Hash *passphrase* with Argon2id and write to ``passphrase.hash``.

        The file is created with mode 0600 (owner read/write only).
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        hashed = self._hasher.hash(passphrase)
        self._hash_file.write_text(hashed)
        os.chmod(self._hash_file, 0o600)

    def has_passphrase(self) -> bool:
        """Return True if a passphrase hash file exists on disk."""
        return self._hash_file.exists()

    def verify_passphrase(self, passphrase: str) -> bool:
        """Verify *passphrase* against the stored Argon2id hash.

        Returns ``False`` immediately if:
        - No passphrase has been set.
        - The account is currently locked out.

        On success the failure counter is reset.  On failure the counter is
        incremented and a lockout may be applied if a threshold is reached.
        """
        if not self.has_passphrase():
            return False

        if self.is_locked_out():
            return False

        stored_hash = self._hash_file.read_text().strip()
        try:
            self._hasher.verify(stored_hash, passphrase)
        except VerifyMismatchError:
            self._record_failure()
            return False

        # Success — reset failure counter
        self._lockout_state["failures"] = 0
        self._lockout_state["locked_until"] = 0.0
        self._save_lockout_state()
        return True

    # ------------------------------------------------------------------
    # Lockout management
    # ------------------------------------------------------------------

    def is_locked_out(self) -> bool:
        """Return True if the lockout period has not yet elapsed."""
        locked_until = self._lockout_state.get("locked_until", 0.0)
        if locked_until <= 0:
            return False
        if time.time() >= locked_until:
            # Lockout has expired — clear it
            self._lockout_state["locked_until"] = 0.0
            self._save_lockout_state()
            return False
        return True

    # ------------------------------------------------------------------
    # Session activation
    # ------------------------------------------------------------------

    def activate(self, passphrase: str) -> bool:
        """Attempt to activate break-glass mode for this session.

        Returns True on success.  Returns False if the passphrase is wrong
        or the account is locked out.
        """
        if self.verify_passphrase(passphrase):
            self._active = True
            return True
        return False

    def deactivate(self) -> None:
        """Deactivate break-glass mode for this session."""
        self._active = False

    def is_active(self) -> bool:
        """Return whether break-glass mode is active for this session."""
        return self._active

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_failure(self) -> None:
        """Increment the failure counter and apply a lockout if a threshold is met."""
        self._lockout_state["failures"] = self._lockout_state.get("failures", 0) + 1
        failures = self._lockout_state["failures"]

        # Walk thresholds in order; apply the highest matching one
        for threshold_count, lockout_seconds in self._lockout_thresholds:
            if failures >= threshold_count:
                self._lockout_state["locked_until"] = time.time() + lockout_seconds

        self._save_lockout_state()

    def _load_lockout_state(self) -> dict:
        """Load lockout state from disk, or return clean defaults."""
        if self._lockout_file.exists():
            try:
                data = json.loads(self._lockout_file.read_text())
                return {
                    "failures": data.get("failures", 0),
                    "locked_until": data.get("locked_until", 0.0),
                }
            except (json.JSONDecodeError, OSError):
                pass
        return {"failures": 0, "locked_until": 0.0}

    def _save_lockout_state(self) -> None:
        """Persist lockout state to ``lockout.json``."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._lockout_file.write_text(json.dumps(self._lockout_state))
