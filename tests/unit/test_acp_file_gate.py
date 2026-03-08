"""Behavioral tests for corvus.acp.file_gate — workspace boundary + secret pattern enforcement."""

from pathlib import Path

from corvus.acp.file_gate import check_file_access


class TestFileGateRead:
    """Tests for read operations through the file gate."""

    def test_read_allowed_file(self, tmp_path: Path) -> None:
        """A normal source file inside the workspace must be allowed."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        src = workspace / "src"
        src.mkdir()
        main_py = src / "main.py"
        main_py.write_text("print('hello')")

        result = check_file_access(
            path="src/main.py",
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is True
        assert result.resolved_path is not None
        assert result.resolved_path == main_py.resolve()

    def test_read_blocked_traversal(self, tmp_path: Path) -> None:
        """Path traversal outside workspace must be blocked."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = check_file_access(
            path="../../etc/passwd",
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is False
        assert "boundary" in result.reason.lower()
        assert result.resolved_path is None

    def test_read_blocked_secret_pattern(self, tmp_path: Path) -> None:
        """Dotenv files must be blocked by secret pattern."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".env").write_text("SECRET=x")

        result = check_file_access(
            path=".env",
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is False
        assert result.resolved_path is None

    def test_read_blocked_pem_file(self, tmp_path: Path) -> None:
        """PEM certificate/key files must be blocked."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "server.pem").write_text("-----BEGIN CERTIFICATE-----")

        result = check_file_access(
            path="server.pem",
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is False
        assert result.resolved_path is None

    def test_read_blocked_by_parent_policy(self, tmp_path: Path) -> None:
        """Parent agent disabling read must block even normal files."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "readme.txt").write_text("hello")

        result = check_file_access(
            path="readme.txt",
            workspace_root=workspace,
            operation="read",
            parent_allows_read=False,
        )

        assert result.allowed is False
        assert "parent" in result.reason.lower()


class TestFileGateWrite:
    """Tests for write operations through the file gate."""

    def test_write_allowed(self, tmp_path: Path) -> None:
        """Write to a normal path inside workspace must be allowed."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = check_file_access(
            path="src/new_file.py",
            workspace_root=workspace,
            operation="write",
            parent_allows_write=True,
        )

        assert result.allowed is True
        assert result.resolved_path is not None

    def test_write_blocked_by_parent_policy(self, tmp_path: Path) -> None:
        """Parent agent disabling write must block write operations."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = check_file_access(
            path="src/new_file.py",
            workspace_root=workspace,
            operation="write",
            parent_allows_write=False,
        )

        assert result.allowed is False
        assert "parent" in result.reason.lower()


class TestFileGatePathResolution:
    """Tests for path resolution edge cases."""

    def test_absolute_path_resolved(self, tmp_path: Path) -> None:
        """An absolute path inside the workspace must be allowed."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "data.txt"
        target.write_text("data")

        result = check_file_access(
            path=str(target),
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is True
        assert result.resolved_path == target.resolve()

    def test_symlink_outside_workspace_blocked(self, tmp_path: Path) -> None:
        """A symlink that resolves outside the workspace must be blocked."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        outside = tmp_path / "outside_secret.txt"
        outside.write_text("secret data")

        link = workspace / "sneaky_link"
        link.symlink_to(outside)

        result = check_file_access(
            path="sneaky_link",
            workspace_root=workspace,
            operation="read",
        )

        assert result.allowed is False
        assert "boundary" in result.reason.lower()
        assert result.resolved_path is None


class TestFileGateBreakGlass:
    """Tests for break-glass secret access override."""

    def test_secret_allowed_with_break_glass(self, tmp_path: Path) -> None:
        """With allow_secret_access=True, secret files should be readable."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".env").write_text("SECRET=value")

        result = check_file_access(
            path=".env",
            workspace_root=workspace,
            operation="read",
            allow_secret_access=True,
        )

        assert result.allowed is True
        assert result.resolved_path is not None

    def test_secret_blocked_without_break_glass(self, tmp_path: Path) -> None:
        """Without break-glass, secret files are still blocked."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".env").write_text("SECRET=value")

        result = check_file_access(
            path=".env",
            workspace_root=workspace,
            operation="read",
            allow_secret_access=False,
        )

        assert result.allowed is False
