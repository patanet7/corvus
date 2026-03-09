"""Behavioral tests for the tightened Darwin sandbox profile (F-010).

Validates that the macOS sandbox-exec profile restricts file access to the
workspace directory and essential system paths, while denying network access.
"""

from pathlib import Path

from corvus.acp.sandbox import (
    _DARWIN_SYSTEM_READ_PATHS,
    _DARWIN_SYSTEM_WRITE_PATHS,
    _build_darwin_sandbox_profile,
    build_sandbox_command,
)


class TestDarwinSandboxProfile:
    """Tests for _build_darwin_sandbox_profile output."""

    def test_profile_is_version_1(self, tmp_path: Path) -> None:
        """Profile must start with (version 1) for sandbox-exec compliance."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert profile.startswith("(version 1)")

    def test_profile_denies_network(self, tmp_path: Path) -> None:
        """Network access must always be denied."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(deny network*)" in profile

    def test_profile_denies_network_without_workspace(self) -> None:
        """Network denied even when no workspace is given."""
        profile = _build_darwin_sandbox_profile(None)
        assert "(deny network*)" in profile

    def test_profile_uses_deny_default(self, tmp_path: Path) -> None:
        """Profile must use (deny default), not (allow default)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(deny default)" in profile
        assert "(allow default)" not in profile

    def test_profile_allows_workspace_reads(self, tmp_path: Path) -> None:
        """Workspace directory must be readable."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        ws_resolved = str(workspace.resolve())
        assert f'(allow file-read* (subpath "{ws_resolved}"))' in profile

    def test_profile_allows_workspace_writes(self, tmp_path: Path) -> None:
        """Workspace directory must be writable."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        ws_resolved = str(workspace.resolve())
        assert f'(allow file-write* (subpath "{ws_resolved}"))' in profile

    def test_profile_allows_system_dir_reads(self, tmp_path: Path) -> None:
        """Essential system directories must be readable."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        for sys_path in _DARWIN_SYSTEM_READ_PATHS:
            assert f'(allow file-read* (subpath "{sys_path}"))' in profile, (
                f"Missing read access for system path: {sys_path}"
            )

    def test_profile_allows_limited_system_writes(self, tmp_path: Path) -> None:
        """Only /dev/null, /dev/tty, /dev/dtracehelper should be writable outside workspace."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        for sys_path in _DARWIN_SYSTEM_WRITE_PATHS:
            assert f'(allow file-write* (literal "{sys_path}"))' in profile, (
                f"Missing write access for: {sys_path}"
            )

    def test_profile_denies_arbitrary_path_read(self, tmp_path: Path) -> None:
        """Paths outside workspace and system dirs must not have explicit read grants."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        # /etc and /home are NOT in allowed system paths
        assert '"/etc"' not in profile
        assert '"/home"' not in profile
        assert '"/Users"' not in profile

    def test_profile_denies_arbitrary_path_write(self, tmp_path: Path) -> None:
        """Paths outside workspace must not have write grants."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        # Count file-write* subpath entries -- should only be workspace
        write_subpath_count = profile.count("(allow file-write* (subpath")
        assert write_subpath_count == 1, (
            f"Expected exactly 1 file-write subpath (workspace), got {write_subpath_count}"
        )

    def test_no_workspace_omits_user_file_access(self) -> None:
        """Without a workspace, no user-directory file access should be granted."""
        profile = _build_darwin_sandbox_profile(None)
        # No workspace-specific subpath writes
        assert "(allow file-write* (subpath" not in profile
        # System reads are still present
        assert "(allow file-read* (subpath" in profile

    def test_profile_allows_process_execution(self, tmp_path: Path) -> None:
        """Process execution must be allowed for running commands."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(allow process*)" in profile

    def test_profile_allows_signal(self, tmp_path: Path) -> None:
        """Signal handling must be allowed."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(allow signal)" in profile

    def test_profile_allows_sysctl_read(self, tmp_path: Path) -> None:
        """sysctl-read must be allowed for system info access."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(allow sysctl-read)" in profile

    def test_profile_allows_mach_ipc(self, tmp_path: Path) -> None:
        """Mach IPC must be allowed for macOS subsystem communication."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        profile = _build_darwin_sandbox_profile(workspace)
        assert "(allow mach*)" in profile


class TestBuildSandboxCommandDarwinWorkspace:
    """Tests for build_sandbox_command with workspace parameter on Darwin."""

    def test_with_workspace_uses_tightened_profile(self, tmp_path: Path) -> None:
        """When workspace is provided, the profile should scope file access."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, workspace=workspace, platform="darwin")
        assert result[0] == "sandbox-exec"
        assert "-p" in result
        profile = result[result.index("-p") + 1]
        ws_resolved = str(workspace.resolve())
        assert "(deny default)" in profile
        assert f'(subpath "{ws_resolved}")' in profile
        assert "(deny network*)" in profile
        assert result[-2:] == ["npx", "codex"]

    def test_without_workspace_uses_restrictive_default(self) -> None:
        """Without workspace, profile should deny default with no user-dir writes."""
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, platform="darwin")
        assert result[0] == "sandbox-exec"
        profile = result[result.index("-p") + 1]
        assert "(deny default)" in profile
        assert "(allow default)" not in profile
        assert "(deny network*)" in profile
        # No workspace subpath writes
        assert "(allow file-write* (subpath" not in profile

    def test_linux_unaffected_by_workspace(self, tmp_path: Path) -> None:
        """Linux sandbox should be unchanged regardless of workspace parameter."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, workspace=workspace, platform="linux")
        assert result[0] == "unshare"
        assert "--net" in result
        assert result[-2:] == ["npx", "codex"]

    def test_unsupported_platform_unaffected(self, tmp_path: Path) -> None:
        """Unsupported platforms return command unchanged."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        cmd = ["npx", "codex"]
        result = build_sandbox_command(cmd, workspace=workspace, platform="win32")
        assert result == cmd
