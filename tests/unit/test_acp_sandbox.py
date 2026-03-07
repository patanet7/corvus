"""Behavioral tests for corvus.acp.sandbox — env stripping + network isolation."""

from pathlib import Path

from corvus.acp.sandbox import build_acp_env, build_sandbox_command


class TestBuildAcpEnv:
    """Tests for environment sanitization."""

    def test_env_strips_secrets(self, tmp_path: Path) -> None:
        """Secrets must be stripped; allowed vars and overrides must survive."""
        workspace = tmp_path / "agent_ws"
        workspace.mkdir()

        host_env = {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
            "DATABASE_URL": "postgres://user:pass@localhost/db",
            "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "CORVUS_SESSION_SECRET": "supersecret",
            "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        result = build_acp_env(workspace=workspace, host_env=host_env)

        # Secrets must be absent
        assert "ANTHROPIC_API_KEY" not in result
        assert "OPENAI_API_KEY" not in result
        assert "DATABASE_URL" not in result
        assert "AWS_SECRET_ACCESS_KEY" not in result
        assert "CORVUS_SESSION_SECRET" not in result

        # Allowed vars kept
        assert result["LANG"] == "en_US.UTF-8"
        assert result["TERM"] == "xterm-256color"

        # Overrides applied
        assert result["HOME"] == str(workspace)
        assert result["TMPDIR"] == str(workspace / "tmp")

    def test_env_restricts_path(self, tmp_path: Path) -> None:
        """PATH must be restricted to safe locations regardless of host PATH."""
        workspace = tmp_path / "agent_ws"
        workspace.mkdir()

        host_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        result = build_acp_env(workspace=workspace, host_env=host_env)

        assert result["PATH"] == "/usr/bin:/bin"


class TestBuildSandboxCommand:
    """Tests for platform-specific sandbox wrapping."""

    def test_sandbox_command_darwin(self) -> None:
        """On macOS, cmd must be wrapped with sandbox-exec."""
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="darwin")

        assert result[0] == "sandbox-exec"
        assert "-p" in result
        # Original command preserved at the end
        assert result[-2:] == ["npx", "codex"]

    def test_sandbox_command_linux(self) -> None:
        """On Linux, cmd must be wrapped with unshare --net."""
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="linux")

        assert result[0] == "unshare"
        assert "--net" in result
        # Original command preserved at the end
        assert result[-2:] == ["npx", "codex"]

    def test_sandbox_command_unsupported(self) -> None:
        """On unsupported platforms, cmd is returned unchanged."""
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="win32")

        assert result == cmd
