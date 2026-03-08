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
    """Chat modules import without error."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from corvus.cli.chat import parse_args; "
                "from corvus.cli.chat_render import render_welcome; "
                "from corvus.cli.compose_claude_md import compose_claude_md; "
                "from corvus.cli.compose_system_prompt import compose_system_prompt; "
                "from corvus.cli.tool_token import create_token, validate_token; "
                "from corvus.cli.tool_registry import _MODULE_REGISTRY"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"


def test_chat_parse_args_defaults() -> None:
    """parse_args returns expected defaults."""
    from corvus.cli.chat import parse_args

    args = parse_args([])
    assert args.agent is None
    assert args.model is None
    assert args.resume is None
    assert args.budget is None
    assert args.print_mode is False
    assert args.verbose is False
