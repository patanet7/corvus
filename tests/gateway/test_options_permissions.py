"""Behavioral tests for dynamic tool-permission callback wiring."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.events import EventEmitter
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


def _build_runtime() -> _Runtime:
    spec = AgentSpec(
        name="docs",
        description="docs agent",
        tools=AgentToolConfig(
            builtin=["Bash"],
            modules={},
            confirm_gated=["Bash"],
        ),
        memory=AgentMemoryConfig(own_domain="docs"),
    )
    return _Runtime(
        agents_hub=_AgentsHub(spec=spec),
        capabilities_registry=CapabilitiesRegistry(),
        emitter=EventEmitter(),
    )


def test_can_use_tool_emits_ws_permission_decision_for_allow() -> None:
    runtime = _build_runtime()
    captured: list[dict] = []

    async def _collect(payload: dict) -> None:
        captured.append(payload)

    callback = _build_can_use_tool(
        runtime=runtime,  # type: ignore[arg-type]
        agent_name="docs",
        allow_secret_access=False,
        ws_callback=_collect,
    )
    assert callback is not None

    result = asyncio.run(callback("Bash", {"command": "pwd"}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultAllow)
    # Two WS messages: tool_permission_decision + confirm_request (confirm-gated tool)
    assert len(captured) == 2
    assert captured[0]["type"] == "tool_permission_decision"
    assert captured[0]["agent"] == "docs"
    assert captured[0]["tool"] == "Bash"
    assert captured[0]["allowed"] is True
    assert captured[0]["state"] == "confirm"
    assert captured[1]["type"] == "confirm_request"
    assert captured[1]["tool"] == "Bash"


def test_can_use_tool_emits_ws_permission_decision_for_deny() -> None:
    runtime = _build_runtime()
    captured: list[dict] = []

    async def _collect(payload: dict) -> None:
        captured.append(payload)

    callback = _build_can_use_tool(
        runtime=runtime,  # type: ignore[arg-type]
        agent_name="docs",
        allow_secret_access=False,
        ws_callback=_collect,
    )
    assert callback is not None

    result = asyncio.run(callback("Read", {"path": "README.md"}, ToolPermissionContext()))
    assert isinstance(result, PermissionResultDeny)
    assert len(captured) == 1
    assert captured[0]["type"] == "tool_permission_decision"
    assert captured[0]["agent"] == "docs"
    assert captured[0]["tool"] == "Read"
    assert captured[0]["allowed"] is False
    assert captured[0]["state"] == "deny"
