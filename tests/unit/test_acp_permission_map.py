"""Behavioral tests for ACP permission mapper — pure function, no I/O."""

from corvus.acp.permission_map import map_acp_permission


def test_read_maps_to_read() -> None:
    """ACP 'read' kind maps to Corvus 'Read' capability."""
    assert map_acp_permission("read") == "Read"


def test_search_maps_to_grep() -> None:
    """ACP 'search' kind maps to Corvus 'Grep' capability."""
    assert map_acp_permission("search") == "Grep"


def test_edit_maps_to_write() -> None:
    """ACP 'edit' kind maps to Corvus 'Write' capability."""
    assert map_acp_permission("edit") == "Write"


def test_delete_maps_to_write() -> None:
    """ACP 'delete' kind maps to Corvus 'Write' capability."""
    assert map_acp_permission("delete") == "Write"


def test_move_maps_to_write() -> None:
    """ACP 'move' kind maps to Corvus 'Write' capability."""
    assert map_acp_permission("move") == "Write"


def test_execute_maps_to_bash() -> None:
    """ACP 'execute' kind maps to Corvus 'Bash' capability."""
    assert map_acp_permission("execute") == "Bash"


def test_fetch_maps_to_webfetch() -> None:
    """ACP 'fetch' kind maps to Corvus 'WebFetch' capability."""
    assert map_acp_permission("fetch") == "WebFetch"


def test_think_always_allowed() -> None:
    """ACP 'think' kind returns None — always allowed, no policy check needed."""
    assert map_acp_permission("think") is None


def test_unknown_denied() -> None:
    """Unknown ACP kinds return '__DENIED__' — deny-wins for unmapped kinds."""
    assert map_acp_permission("unknown_kind") == "__DENIED__"


def test_case_insensitive() -> None:
    """Lookup is case-insensitive — uppercase and mixed case both resolve."""
    assert map_acp_permission("READ") == "Read"
    assert map_acp_permission("Execute") == "Bash"
