"""Behavioral tests for CorvusACPClient construction and capability building.

These tests verify the client's configuration, property access, and
capability advertisement logic without spawning real processes.
"""

from pathlib import Path

from corvus.acp.client import ACPClientConfig, CorvusACPClient
from corvus.acp.registry import AcpAgentEntry


def _make_entry() -> AcpAgentEntry:
    return AcpAgentEntry(
        name="codex",
        command="npx @zed-industries/codex-acp",
        default_permissions="approve-reads",
    )


def _make_config(tmp_path: Path, **overrides) -> ACPClientConfig:
    defaults = {
        "agent_entry": _make_entry(),
        "workspace": tmp_path,
        "corvus_session_id": "sess-001",
        "corvus_run_id": "run-001",
        "parent_agent": "work",
        "parent_allows_read": True,
        "parent_allows_write": True,
        "parent_allows_bash": True,
    }
    defaults.update(overrides)
    return ACPClientConfig(**defaults)


def test_client_config_construction(tmp_path: Path) -> None:
    """ACPClientConfig stores all fields correctly."""
    config = _make_config(tmp_path)

    assert config.agent_entry.name == "codex"
    assert config.workspace == tmp_path
    assert config.corvus_session_id == "sess-001"
    assert config.corvus_run_id == "run-001"
    assert config.parent_agent == "work"
    assert config.parent_allows_read is True
    assert config.parent_allows_write is True
    assert config.parent_allows_bash is True


def test_client_construction(tmp_path: Path) -> None:
    """CorvusACPClient exposes agent_name and workspace properties."""
    config = _make_config(tmp_path)
    client = CorvusACPClient(config)

    assert client.agent_name == "codex"
    assert client.workspace == tmp_path


def test_client_capabilities_no_bash(tmp_path: Path) -> None:
    """When parent_allows_bash=False, terminal must NOT appear in capabilities."""
    config = _make_config(tmp_path, parent_allows_bash=False)
    client = CorvusACPClient(config)
    caps = client.build_capabilities()

    assert "terminal" not in caps
    # fs should still be present since read and write are allowed
    assert "fs" in caps


def test_client_capabilities_no_write(tmp_path: Path) -> None:
    """When parent_allows_write=False, fs.writeTextFile must not be True."""
    config = _make_config(tmp_path, parent_allows_write=False)
    client = CorvusACPClient(config)
    caps = client.build_capabilities()

    fs = caps.get("fs", {})
    assert fs.get("writeTextFile") is not True
    # read should still be present
    assert fs.get("readTextFile") is True


def test_client_capabilities_full(tmp_path: Path) -> None:
    """When all permissions are True, fs and terminal capabilities are all present."""
    config = _make_config(tmp_path)
    client = CorvusACPClient(config)
    caps = client.build_capabilities()

    assert caps["fs"]["readTextFile"] is True
    assert caps["fs"]["writeTextFile"] is True
    assert "terminal" in caps


def test_client_capabilities_no_read_no_write(tmp_path: Path) -> None:
    """When both read and write are False, the fs key must not appear."""
    config = _make_config(
        tmp_path,
        parent_allows_read=False,
        parent_allows_write=False,
    )
    client = CorvusACPClient(config)
    caps = client.build_capabilities()

    assert "fs" not in caps
