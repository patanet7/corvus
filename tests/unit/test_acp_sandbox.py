"""Behavioral tests for corvus.acp.sandbox — env stripping + network isolation."""

from pathlib import Path

from corvus.acp.sandbox import (
    build_acp_child_env,
    build_acp_spawn_env,
    build_sandbox_command,
)


class TestBuildAcpSpawnEnv:
    """Tests for spawn environment (ACP agent binary)."""

    def test_strips_corvus_secrets(self, tmp_path: Path) -> None:
        """Corvus-internal secrets must be stripped."""
        workspace = tmp_path / "ws"
        workspace.mkdir()

        host_env = {
            "CORVUS_SESSION_SECRET": "supersecret",
            "DATABASE_URL": "postgres://user:pass@localhost/db",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "HA_TOKEN": "ha-token",
            "FIREFLY_API_KEY": "firefly-key",
            "SOPS_AGE_KEY": "age-key",
            "MY_PASSWORD": "secret123",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "OPENAI_API_KEY": "sk-openai-key",
            "LANG": "en_US.UTF-8",
        }

        result = build_acp_spawn_env(workspace=workspace, host_env=host_env)

        # Corvus secrets stripped
        assert "CORVUS_SESSION_SECRET" not in result
        assert "DATABASE_URL" not in result
        assert "ANTHROPIC_API_KEY" not in result
        assert "HA_TOKEN" not in result
        assert "FIREFLY_API_KEY" not in result
        assert "SOPS_AGE_KEY" not in result
        assert "MY_PASSWORD" not in result

        # Agent auth tokens preserved
        assert result["OPENAI_API_KEY"] == "sk-openai-key"

        # Functional env preserved
        assert result["LANG"] == "en_US.UTF-8"
        assert result["PATH"] == "/usr/local/bin:/usr/bin:/bin"

        # Overrides
        assert result["HOME"] == str(workspace)

    def test_preserves_node_paths(self, tmp_path: Path) -> None:
        """Node version managers need their env vars."""
        workspace = tmp_path / "ws"
        workspace.mkdir()

        host_env = {
            "PATH": "/usr/bin:/bin",
            "FNM_DIR": "/home/user/.fnm",
            "FNM_MULTISHELL_PATH": "/tmp/fnm_path",
        }

        result = build_acp_spawn_env(workspace=workspace, host_env=host_env)
        assert result.get("FNM_DIR") == "/home/user/.fnm"
        assert result.get("FNM_MULTISHELL_PATH") == "/tmp/fnm_path"


class TestBuildAcpChildEnv:
    """Tests for child command environment (terminal/create)."""

    def test_env_strips_secrets(self, tmp_path: Path) -> None:
        """Secrets must be stripped; allowed vars and overrides must survive."""
        workspace = tmp_path / "agent_ws"
        workspace.mkdir()

        host_env = {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
            "DATABASE_URL": "postgres://user:pass@localhost/db",
            "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        result = build_acp_child_env(workspace=workspace, host_env=host_env)

        assert "ANTHROPIC_API_KEY" not in result
        assert "OPENAI_API_KEY" not in result
        assert "DATABASE_URL" not in result
        assert result["LANG"] == "en_US.UTF-8"
        assert result["TERM"] == "xterm-256color"
        assert result["HOME"] == str(workspace)
        assert result["TMPDIR"] == str(workspace / "tmp")

    def test_env_restricts_path(self, tmp_path: Path) -> None:
        """PATH must be restricted to safe locations."""
        workspace = tmp_path / "agent_ws"
        workspace.mkdir()

        host_env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
        result = build_acp_child_env(workspace=workspace, host_env=host_env)
        assert result["PATH"] == "/usr/bin:/bin"



class TestBuildSandboxCommand:
    """Tests for platform-specific sandbox wrapping."""

    def test_sandbox_command_darwin(self) -> None:
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="darwin")
        assert result[0] == "sandbox-exec"
        assert "-p" in result
        assert result[-2:] == ["npx", "codex"]

    def test_sandbox_command_linux(self) -> None:
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="linux")
        assert result[0] == "unshare"
        assert "--net" in result
        assert result[-2:] == ["npx", "codex"]

    def test_sandbox_command_unsupported(self) -> None:
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="win32")
        assert result == cmd
