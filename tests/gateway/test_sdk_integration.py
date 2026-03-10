"""Integration tests using real ClaudeSDKClient subprocesses.

These tests require ANTHROPIC_API_KEY to be set and will make real API calls.
Mark with pytest.mark.skipif so they can be skipped in CI.
"""

import os

import pytest

from corvus.gateway.sdk_client_manager import SDKClientManager
from tests.conftest import INSIDE_CLAUDE_CODE

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set — skipping SDK integration tests",
    ),
    pytest.mark.skipif(
        INSIDE_CLAUDE_CODE,
        reason="Cannot spawn nested Claude Code sessions — run outside Claude Code",
    ),
]


@pytest.mark.asyncio
async def test_persistent_context_across_queries():
    """Two queries to the same client — second should reference first."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    opts = ClaudeAgentOptions(
        allowed_tools=[],
        permission_mode="plan",  # read-only, no tool execution
        max_turns=1,
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Remember this number: 42")
        first_response = ""
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        first_response += block.text

        await client.query("What number did I ask you to remember?")
        second_response = ""
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        second_response += block.text

        assert "42" in second_response, f"Expected '42' in response, got: {second_response}"


@pytest.mark.asyncio
async def test_stream_events_with_partial_messages():
    """Verify StreamEvent objects arrive when include_partial_messages=True."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from claude_agent_sdk.types import StreamEvent

    opts = ClaudeAgentOptions(
        include_partial_messages=True,
        allowed_tools=[],
        permission_mode="plan",
        max_turns=1,
    )
    stream_events_seen = False
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Say hello")
        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                stream_events_seen = True

    assert stream_events_seen, "Expected StreamEvent objects with include_partial_messages=True"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="get_or_create stub not yet implemented — needs Task 5+")
async def test_sdk_client_manager_lifecycle():
    """Full lifecycle through SDKClientManager."""
    from claude_agent_sdk import ClaudeAgentOptions

    mgr = SDKClientManager(runtime=None)

    def builder():
        return ClaudeAgentOptions(
            allowed_tools=[],
            permission_mode="plan",
            max_turns=1,
        )

    mc = await mgr.get_or_create("test-sess", "test-agent", builder)
    assert mc.client is not None
    assert mc.agent_name == "test-agent"

    # Second call should return same client
    mc2 = await mgr.get_or_create("test-sess", "test-agent", builder)
    assert mc2 is mc

    # Teardown
    await mgr.teardown_session("test-sess")
    assert mgr.list_active_clients() == []
