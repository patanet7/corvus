"""Verify CORVUS_BREAK_GLASS env var no longer grants break-glass access.

Security hardening F-002: the env-var-based bypass was removed so that
break-glass mode can only be activated via Argon2id password verification
through BreakGlassSessionRegistry.
"""

import importlib
import os

import corvus.config


class TestBreakGlassEnvRemoval:
    """Behavioral tests confirming BREAK_GLASS_MODE is fully removed."""

    def test_config_does_not_export_break_glass_mode(self) -> None:
        """corvus.config must not have a BREAK_GLASS_MODE attribute."""
        assert not hasattr(corvus.config, "BREAK_GLASS_MODE"), (
            "BREAK_GLASS_MODE still exists in corvus.config — "
            "env-var bypass must be removed entirely"
        )

    def test_env_var_has_no_effect_on_config(self) -> None:
        """Setting CORVUS_BREAK_GLASS=1 must not create BREAK_GLASS_MODE."""
        original = os.environ.get("CORVUS_BREAK_GLASS")
        os.environ["CORVUS_BREAK_GLASS"] = "1"
        try:
            importlib.reload(corvus.config)
            assert not hasattr(corvus.config, "BREAK_GLASS_MODE"), (
                "BREAK_GLASS_MODE appeared after setting CORVUS_BREAK_GLASS=1 — "
                "env-var bypass must be removed entirely"
            )
        finally:
            if original is None:
                os.environ.pop("CORVUS_BREAK_GLASS", None)
            else:
                os.environ["CORVUS_BREAK_GLASS"] = original
            importlib.reload(corvus.config)

    def test_break_glass_not_importable_from_config(self) -> None:
        """Attempting to import BREAK_GLASS_MODE from corvus.config must fail."""
        exported = dir(corvus.config)
        assert "BREAK_GLASS_MODE" not in exported, (
            "BREAK_GLASS_MODE is still in dir(corvus.config)"
        )
