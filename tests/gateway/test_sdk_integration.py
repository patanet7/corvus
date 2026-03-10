"""Integration tests for SDK client management.

Pool management tests run in every suite (no subprocess, fast).
Real SDK subprocess tests are marked ``slow`` — run with ``pytest -m slow``.

End-to-end LLM query tests live in tests/integration/test_live_llm_qa.py
which exercises the full stack (LiteLLM proxy, credential injection, streaming).
"""

import os
import time

import pytest

from corvus.credential_store import get_credential_store
from corvus.gateway.sdk_client_manager import ManagedClient, SDKClientManager
from tests.conftest import INSIDE_CLAUDE_CODE

# ---------------------------------------------------------------------------
# Pool management tests — exercise real pool logic, no subprocess needed
# ---------------------------------------------------------------------------


@pytest.fixture
def mgr():
    return SDKClientManager(runtime=None)


def _add_client(mgr: SDKClientManager, session_id: str, agent_name: str) -> ManagedClient:
    """Register a real ManagedClient in the pool (uses create_stub — a production factory)."""
    mc = ManagedClient.create_stub(session_id=session_id, agent_name=agent_name)
    pool = mgr._get_pool(session_id)
    pool.add(mc)
    return mc


def test_pool_create_and_reuse(mgr):
    """Same session+agent returns the same ManagedClient."""
    mc = _add_client(mgr, "sess-1", "agent-a")
    found = mgr._get_existing("sess-1", "agent-a")
    assert found is mc


def test_pool_returns_none_for_unknown(mgr):
    """Lookup for non-existent session/agent returns None."""
    assert mgr._get_existing("no-such-session", "agent-a") is None
    _add_client(mgr, "sess-1", "agent-a")
    assert mgr._get_existing("sess-1", "agent-b") is None


def test_multi_agent_same_session(mgr):
    """Different agents in same session get separate entries."""
    mc_a = _add_client(mgr, "sess-1", "agent-a")
    mc_b = _add_client(mgr, "sess-1", "agent-b")

    assert mc_a is not mc_b
    assert mgr._get_existing("sess-1", "agent-a") is mc_a
    assert mgr._get_existing("sess-1", "agent-b") is mc_b
    assert len(mgr.list_active_clients()) == 2


def test_session_isolation(mgr):
    """Different sessions are fully isolated."""
    mc_1 = _add_client(mgr, "sess-1", "agent-a")
    mc_2 = _add_client(mgr, "sess-2", "agent-a")

    assert mc_1 is not mc_2
    assert mgr._get_existing("sess-1", "agent-a") is mc_1
    assert mgr._get_existing("sess-2", "agent-a") is mc_2


@pytest.mark.asyncio
async def test_teardown_session(mgr):
    """Teardown removes all clients in a session."""
    _add_client(mgr, "sess-1", "agent-a")
    _add_client(mgr, "sess-1", "agent-b")
    _add_client(mgr, "sess-2", "agent-a")

    count = await mgr.teardown_session("sess-1")
    assert count == 2

    active = mgr.list_active_clients()
    assert len(active) == 1
    assert active[0].session_id == "sess-2"


@pytest.mark.asyncio
async def test_teardown_all(mgr):
    """Teardown all clears everything."""
    _add_client(mgr, "sess-1", "agent-a")
    _add_client(mgr, "sess-2", "agent-b")

    total = await mgr.teardown_all()
    assert total == 2
    assert mgr.list_active_clients() == []


def test_list_active_clients_shape(mgr):
    """list_active_clients returns ClientInfo with expected fields."""
    _add_client(mgr, "sess-1", "agent-a")
    active = mgr.list_active_clients()
    assert len(active) == 1
    assert active[0].session_id == "sess-1"
    assert active[0].agent_name == "agent-a"
    assert hasattr(active[0], "idle_seconds")


def test_last_activity_updated_on_lookup(mgr):
    """_get_existing updates last_activity timestamp."""
    mc = _add_client(mgr, "sess-1", "agent-a")
    original_ts = mc.last_activity
    time.sleep(0.01)
    mgr._get_existing("sess-1", "agent-a")
    assert mc.last_activity > original_ts


# ---------------------------------------------------------------------------
# Real SDK subprocess tests — spawn actual Claude Code CLI
# Run with: pytest -m slow tests/gateway/test_sdk_integration.py
# ---------------------------------------------------------------------------

# Load credentials for real subprocess tests
_store = get_credential_store()
_store.inject()

_has_credential = bool(
    os.environ.get("ANTHROPIC_API_KEY")
    or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
)


def _build_opts(**overrides):
    """Build ClaudeAgentOptions for real subprocess tests."""
    from claude_agent_sdk import ClaudeAgentOptions

    defaults: dict = {
        "allowed_tools": [],
        "permission_mode": "plan",
        "max_turns": 1,
        "model": os.environ.get("CORVUS_TEST_MODEL", "sonnet"),
    }
    defaults.update(overrides)
    opts = ClaudeAgentOptions(**defaults)

    for var in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        val = os.environ.get(var)
        if val:
            opts.env[var] = val

    return opts


@pytest.mark.slow
@pytest.mark.skipif(not _has_credential, reason="No LLM credential set")
@pytest.mark.skipif(INSIDE_CLAUDE_CODE, reason="Cannot spawn nested Claude Code sessions")
@pytest.mark.asyncio
async def test_real_sdk_client_lifecycle():
    """Real subprocess: create client, verify connection, teardown."""
    mgr = SDKClientManager(runtime=None)

    mc = await mgr.get_or_create("test-sess", "test-agent", lambda: _build_opts())
    assert mc.client is not None
    assert mc.agent_name == "test-agent"

    # Second call returns same client
    mc2 = await mgr.get_or_create("test-sess", "test-agent", lambda: _build_opts())
    assert mc2 is mc

    await mgr.teardown_session("test-sess")
    assert mgr.list_active_clients() == []
