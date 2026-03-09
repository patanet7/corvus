"""Behavioral tests for _resolve_parent_allows — derives parent capability
flags from the agent spec's declared builtins list.

Each test constructs a real AgentSpec with a specific builtins list and
verifies the resolved read/write/bash flags match expectations.
"""

from corvus.agents.spec import AgentSpec
from corvus.gateway.acp_executor import _resolve_parent_allows


def _make_spec(builtins: list[str]) -> AgentSpec:
    """Build a minimal AgentSpec with the given builtins list."""
    return AgentSpec.from_dict({
        "name": "test-agent",
        "description": "Test agent for parent_allows wiring",
        "tools": {"builtin": builtins},
    })


def test_read_and_grep_only():
    """Agent with Read and Grep gets read=True, write=False, bash=False."""
    spec = _make_spec(["Read", "Grep"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": True, "write": False, "bash": False}


def test_bash_read_write():
    """Agent with Bash, Read, Write gets all True."""
    spec = _make_spec(["Bash", "Read", "Write"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": True, "write": True, "bash": True}


def test_edit_implies_write():
    """Agent with Read and Edit gets write=True (Edit implies write)."""
    spec = _make_spec(["Read", "Edit"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": True, "write": True, "bash": False}


def test_empty_builtins_all_false():
    """Agent with no builtins gets all False."""
    spec = _make_spec([])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": False, "write": False, "bash": False}


def test_full_builtins():
    """Agent with all common builtins gets all True."""
    spec = _make_spec(["Bash", "Read", "Write", "Edit", "Grep", "Glob"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": True, "write": True, "bash": True}


def test_bash_only():
    """Agent with only Bash gets bash=True, others False."""
    spec = _make_spec(["Bash"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": False, "write": False, "bash": True}


def test_write_without_read():
    """Agent with Write but not Read gets write=True, read=False."""
    spec = _make_spec(["Write"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": False, "write": True, "bash": False}


def test_case_sensitivity():
    """Builtins are case-sensitive -- lowercase 'read' should not match."""
    spec = _make_spec(["read", "bash", "write"])
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": False, "write": False, "bash": False}


def test_default_tools_config():
    """AgentSpec with no tools section defaults to empty builtins."""
    spec = AgentSpec.from_dict({
        "name": "bare-agent",
        "description": "Agent with default tools config",
    })
    allows = _resolve_parent_allows(spec)
    assert allows == {"read": False, "write": False, "bash": False}
