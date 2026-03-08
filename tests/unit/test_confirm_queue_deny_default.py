"""Behavioral tests: confirm-gated tools must deny when no confirm queue is available.

Covers F-007/SEC-003 — the confirm queue fallthrough must default to deny,
not silently allow. Break-glass sessions bypass via allow_secret_access.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
from corvus.gateway.confirm_queue import ConfirmQueue
from corvus.gateway.options import _build_can_use_tool


@dataclass
class _AgentsHub:
    spec: AgentSpec

    def get_agent(self, name: str) -> AgentSpec | None:
        return self.spec if name == self.spec.name else None


@dataclass
class _Runtime:
    agents_hub: _AgentsHub
    capabilities_registry: CapabilitiesRegistry
    emitter: EventEmitter


def _make_runtime(
    *,
    agent_name: str = "docs",
    confirm_gated: list[str] | None = None,
) -> _Runtime:
    spec = AgentSpec(
        name=agent_name,
        description=f"{agent_name} agent",
        tools=AgentToolConfig(
            builtin=["Bash"],
            modules={},
            confirm_gated=confirm_gated if confirm_gated is not None else ["Bash"],
        ),
        memory=AgentMemoryConfig(own_domain=agent_name),
    )
    return _Runtime(
        agents_hub=_AgentsHub(spec=spec),
        capabilities_registry=CapabilitiesRegistry(),
        emitter=EventEmitter(),
    )


class TestConfirmQueueDenyDefault:
    """Confirm-gated tools without a confirm queue must be denied."""

    def test_no_confirm_queue_returns_deny(self) -> None:
        """When confirm_queue is None, gated tools get PermissionResultDeny."""
        runtime = _make_runtime()
        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=None,
        )
        assert callback is not None

        result = asyncio.run(callback("Bash", {"command": "ls"}, ToolPermissionContext()))
        assert isinstance(result, PermissionResultDeny)
        assert "requires confirmation" in result.message
        assert "no confirm queue" in result.message

    def test_deny_message_includes_tool_name(self) -> None:
        """The deny message must identify the blocked tool."""
        runtime = _make_runtime()
        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=None,
        )
        assert callback is not None

        result = asyncio.run(callback("Bash", {}, ToolPermissionContext()))
        assert isinstance(result, PermissionResultDeny)
        assert "Bash" in result.message

    def test_non_gated_tool_still_allowed_without_queue(self) -> None:
        """Non-gated builtin tools are unaffected by missing confirm queue."""
        spec = AgentSpec(
            name="docs",
            description="docs agent",
            tools=AgentToolConfig(
                builtin=["Bash", "Read"],
                modules={},
                confirm_gated=["Bash"],  # Only Bash is gated
            ),
            memory=AgentMemoryConfig(own_domain="docs"),
        )
        runtime = _Runtime(
            agents_hub=_AgentsHub(spec=spec),
            capabilities_registry=CapabilitiesRegistry(),
            emitter=EventEmitter(),
        )
        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=None,
        )
        assert callback is not None

        result = asyncio.run(callback("Read", {"path": "README.md"}, ToolPermissionContext()))
        assert isinstance(result, PermissionResultAllow)

    def test_break_glass_bypasses_confirm_gate(self) -> None:
        """Break-glass sessions allow all tools regardless of gating or queue."""
        runtime = _make_runtime()
        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=True,
            confirm_queue=None,
        )
        assert callback is not None

        result = asyncio.run(callback("Bash", {"command": "rm -rf /"}, ToolPermissionContext()))
        assert isinstance(result, PermissionResultAllow)

    def test_with_confirm_queue_approved_allows(self) -> None:
        """When a confirm queue IS present and user approves, tool is allowed."""
        runtime = _make_runtime()
        queue = ConfirmQueue()

        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=queue,
        )
        assert callback is not None

        async def _run() -> PermissionResultAllow | PermissionResultDeny:
            task = asyncio.create_task(
                callback("Bash", {"command": "ls"}, ToolPermissionContext())
            )
            await asyncio.sleep(0.05)
            queue.respond("Bash", approved=True)
            return await task

        result = asyncio.run(_run())
        assert isinstance(result, PermissionResultAllow)

    def test_with_confirm_queue_denied_denies(self) -> None:
        """When a confirm queue IS present and user denies, tool is denied."""
        runtime = _make_runtime()
        queue = ConfirmQueue()

        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=queue,
        )
        assert callback is not None

        async def _run() -> PermissionResultAllow | PermissionResultDeny:
            task = asyncio.create_task(
                callback("Bash", {"command": "ls"}, ToolPermissionContext())
            )
            await asyncio.sleep(0.05)
            queue.respond("Bash", approved=False)
            return await task

        result = asyncio.run(_run())
        assert isinstance(result, PermissionResultDeny)
        assert "denied" in result.message.lower()

    def test_denied_tool_not_gated_still_denied(self) -> None:
        """Tools not in builtin list are denied regardless of confirm queue state."""
        runtime = _make_runtime()
        callback = _build_can_use_tool(
            runtime=runtime,  # type: ignore[arg-type]
            agent_name="docs",
            allow_secret_access=False,
            confirm_queue=None,
        )
        assert callback is not None

        result = asyncio.run(callback("Write", {"path": "/etc/passwd"}, ToolPermissionContext()))
        assert isinstance(result, PermissionResultDeny)
