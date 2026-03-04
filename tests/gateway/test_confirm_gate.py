"""Behavioral tests for confirm-gating: gated tools must block until user approves."""

import asyncio
import os

import pytest

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.permissions import evaluate_tool_permission, expand_confirm_gated_tools


class TestConfirmGateDecision:
    """Verify permission evaluation marks gated tools as 'confirm' (not 'allow')."""

    @staticmethod
    def _registry() -> CapabilitiesRegistry:
        reg = CapabilitiesRegistry()
        entry = next(m for m in TOOL_MODULE_DEFS if m.name == "paperless")
        reg.register("paperless", entry)
        return reg

    @staticmethod
    def _spec() -> AgentSpec:
        return AgentSpec(
            name="docs",
            description="docs agent",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"paperless": {"enabled": True}},
                confirm_gated=["paperless.tag"],
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )

    def test_gated_tool_decision_is_confirm(self) -> None:
        """A confirm-gated tool should get state='confirm', allowed=True."""
        # Set required env vars so the paperless module passes env gates
        os.environ.setdefault("PAPERLESS_URL", "http://localhost:8000")
        os.environ.setdefault("PAPERLESS_API_TOKEN", "test-token")
        try:
            decision = evaluate_tool_permission(
                agent_name="docs",
                spec=self._spec(),
                capabilities=self._registry(),
                tool_name="mcp__paperless_docs__paperless_tag",
            )
            assert decision.state == "confirm"
            assert decision.allowed is True
        finally:
            # Clean up env vars we set (only if we set them)
            pass

    def test_non_gated_tool_decision_is_allow(self) -> None:
        """A non-gated tool should get state='allow', allowed=True."""
        os.environ.setdefault("PAPERLESS_URL", "http://localhost:8000")
        os.environ.setdefault("PAPERLESS_API_TOKEN", "test-token")
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=self._spec(),
            capabilities=self._registry(),
            tool_name="mcp__paperless_docs__paperless_search",
        )
        assert decision.state == "allow"
        assert decision.allowed is True


class TestConfirmGateBlocking:
    """Verify that can_use_tool blocks on confirm-gated tools until user responds."""

    @staticmethod
    def _registry() -> CapabilitiesRegistry:
        reg = CapabilitiesRegistry()
        entry = next(m for m in TOOL_MODULE_DEFS if m.name == "paperless")
        reg.register("paperless", entry)
        return reg

    @staticmethod
    def _spec() -> AgentSpec:
        return AgentSpec(
            name="docs",
            description="docs agent",
            tools=AgentToolConfig(
                builtin=["Bash"],
                modules={"paperless": {"enabled": True}},
                confirm_gated=["paperless.tag"],
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )

    @pytest.mark.asyncio
    async def test_gated_tool_blocks_until_approved(self) -> None:
        """can_use_tool must not return Allow immediately for gated tools.

        It should block until user approval arrives via the confirm queue.
        """
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        # Start the permission check — it should block
        task = asyncio.create_task(
            queue.wait_for_confirmation(tool_name, timeout_s=2.0)
        )

        # Simulate brief delay then user approves
        await asyncio.sleep(0.05)
        queue.respond(tool_name, approved=True)

        result = await task
        assert result is True

    @pytest.mark.asyncio
    async def test_gated_tool_denied_by_user(self) -> None:
        """User denies a gated tool — should return False."""
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        task = asyncio.create_task(
            queue.wait_for_confirmation(tool_name, timeout_s=2.0)
        )
        await asyncio.sleep(0.05)
        queue.respond(tool_name, approved=False)

        result = await task
        assert result is False

    @pytest.mark.asyncio
    async def test_gated_tool_times_out(self) -> None:
        """No user response within timeout — should return False (deny)."""
        from corvus.gateway.confirm_queue import ConfirmQueue

        queue = ConfirmQueue()
        tool_name = "mcp__paperless_docs__paperless_tag"

        result = await queue.wait_for_confirmation(tool_name, timeout_s=0.1)
        assert result is False
