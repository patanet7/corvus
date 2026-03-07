"""Smoke tests for corvus chat CLI integration."""

import subprocess
import sys


def test_chat_help_exits_zero() -> None:
    """corvus chat --help exits 0 and shows usage."""
    result = subprocess.run(
        [sys.executable, "-m", "corvus.cli.chat", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Launch Claude Code CLI" in result.stdout


def test_chat_module_imports() -> None:
    """All chat modules import without error."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from corvus.cli.chat import parse_args; "
                "from corvus.cli.chat_render import render_welcome; "
                "from corvus.cli.chat_confirm import parse_confirm_response"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
