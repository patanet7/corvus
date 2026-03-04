"""Behavioral tests for deployment-local Claude runtime home wiring."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from corvus.gateway.options import apply_claude_runtime_env, resolve_claude_runtime_home


def test_apply_claude_runtime_env_sets_home_and_xdg_paths(tmp_path: Path) -> None:
    home = tmp_path / "claude-home"
    opts = ClaudeAgentOptions(env={})

    apply_claude_runtime_env(opts, isolate=True, runtime_home=home)

    assert opts.env["HOME"] == str(home.resolve())
    assert opts.env["CLAUDE_CONFIG_DIR"] == str((home / ".claude").resolve())
    assert opts.env["XDG_CONFIG_HOME"] == str((home / ".config").resolve())
    assert opts.env["XDG_CACHE_HOME"] == str((home / ".cache").resolve())
    assert opts.env["XDG_STATE_HOME"] == str((home / ".local" / "state").resolve())
    assert opts.env["XDG_DATA_HOME"] == str((home / ".local" / "share").resolve())

    assert home.is_dir()
    assert (home / ".claude").is_dir()
    assert (home / ".claude" / ".claude.json").is_file()
    assert (home / ".config").is_dir()
    assert (home / ".cache").is_dir()
    assert (home / ".local" / "state").is_dir()
    assert (home / ".local" / "share").is_dir()


def test_apply_claude_runtime_env_uses_template_when_present(tmp_path: Path) -> None:
    home = tmp_path / "claude-home"
    template = tmp_path / "template.json"
    template.write_text('{"custom":"ok"}\n', encoding="utf-8")
    opts = ClaudeAgentOptions(env={})

    apply_claude_runtime_env(
        opts,
        isolate=True,
        runtime_home=home,
        config_template=template,
    )

    assert (home / ".claude" / ".claude.json").read_text(encoding="utf-8") == '{"custom":"ok"}\n'


def test_apply_claude_runtime_env_noop_when_disabled(tmp_path: Path) -> None:
    home = tmp_path / "claude-home"
    opts = ClaudeAgentOptions(env={"HOME": "/tmp/existing-home"})

    apply_claude_runtime_env(opts, isolate=False, runtime_home=home)

    assert opts.env["HOME"] == "/tmp/existing-home"
    assert not home.exists()


def test_resolve_claude_runtime_home_per_agent() -> None:
    base = Path("/tmp/claude-home").resolve()
    home = resolve_claude_runtime_home(
        base_home=base,
        scope="per_agent",
        user="thomas",
        agent_name="@huginn",
    )
    assert home == base / "users" / "thomas" / "agents" / "huginn"


def test_resolve_claude_runtime_home_per_session_agent() -> None:
    base = Path("/tmp/claude-home").resolve()
    home = resolve_claude_runtime_home(
        base_home=base,
        scope="per_session_agent",
        user="thomas",
        session_id="sess/123",
        agent_name="general",
    )
    assert home == base / "users" / "thomas" / "sessions" / "sess-123" / "general"


def test_resolve_claude_runtime_home_unknown_scope_falls_back_to_shared() -> None:
    base = Path("/tmp/claude-home").resolve()
    home = resolve_claude_runtime_home(
        base_home=base,
        scope="mystery",
        user="thomas",
    )
    assert home == base / "users" / "thomas" / "shared"
