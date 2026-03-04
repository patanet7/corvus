"""Behavioral tests for runtime tool permission evaluation."""

from __future__ import annotations

import os

from corvus.agents.spec import AgentMemoryConfig, AgentSpec, AgentToolConfig
from corvus.capabilities.modules import TOOL_MODULE_DEFS
from corvus.capabilities.registry import CapabilitiesRegistry
from corvus.permissions import (
    build_policy_entries,
    evaluate_tool_permission,
    expand_confirm_gated_tools,
    normalize_permission_mode,
)


def _paperless_registry() -> CapabilitiesRegistry:
    reg = CapabilitiesRegistry()
    entry = next(module_def for module_def in TOOL_MODULE_DEFS if module_def.name == "paperless")
    reg.register("paperless", entry)
    return reg


def _agent_spec() -> AgentSpec:
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


def test_expand_confirm_gated_tools() -> None:
    expanded = expand_confirm_gated_tools("docs", ["paperless.tag"])
    assert "paperless.tag" in expanded
    assert "mcp__paperless_docs__paperless_tag" in expanded
    assert "mcp__paperless__paperless_tag" in expanded


def test_builtin_tool_allow_and_deny() -> None:
    reg = _paperless_registry()
    spec = _agent_spec()
    allowed = evaluate_tool_permission(
        agent_name="docs",
        spec=spec,
        capabilities=reg,
        tool_name="Bash",
    )
    denied = evaluate_tool_permission(
        agent_name="docs",
        spec=spec,
        capabilities=reg,
        tool_name="Read",
    )
    assert allowed.allowed is True
    assert allowed.state == "allow"
    assert denied.allowed is False
    assert denied.state == "deny"


def test_module_tool_denied_when_env_missing() -> None:
    reg = _paperless_registry()
    spec = _agent_spec()
    prior_url = os.environ.pop("PAPERLESS_URL", None)
    prior_token = os.environ.pop("PAPERLESS_API_TOKEN", None)
    try:
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=spec,
            capabilities=reg,
            tool_name="mcp__paperless__paperless_search",
        )
        assert decision.allowed is False
        assert decision.state == "deny"
        assert "missing env" in decision.reason.lower()
    finally:
        if prior_url is not None:
            os.environ["PAPERLESS_URL"] = prior_url
        if prior_token is not None:
            os.environ["PAPERLESS_API_TOKEN"] = prior_token


def test_module_tool_allowed_when_env_present() -> None:
    reg = _paperless_registry()
    spec = _agent_spec()
    prior_url = os.environ.get("PAPERLESS_URL")
    prior_token = os.environ.get("PAPERLESS_API_TOKEN")
    os.environ["PAPERLESS_URL"] = "http://paperless.local"
    os.environ["PAPERLESS_API_TOKEN"] = "test-token"
    try:
        decision = evaluate_tool_permission(
            agent_name="docs",
            spec=spec,
            capabilities=reg,
            tool_name="mcp__paperless__paperless_search",
        )
        assert decision.allowed is True
        assert decision.state == "allow"
    finally:
        if prior_url is None:
            os.environ.pop("PAPERLESS_URL", None)
        else:
            os.environ["PAPERLESS_URL"] = prior_url
        if prior_token is None:
            os.environ.pop("PAPERLESS_API_TOKEN", None)
        else:
            os.environ["PAPERLESS_API_TOKEN"] = prior_token


def test_cross_agent_memory_is_denied() -> None:
    reg = _paperless_registry()
    spec = _agent_spec()
    decision = evaluate_tool_permission(
        agent_name="docs",
        spec=spec,
        capabilities=reg,
        tool_name="mcp__memory_personal__memory_search",
    )
    assert decision.allowed is False
    assert decision.scope == "memory_access"


def test_build_policy_entries_reflect_runtime_state() -> None:
    reg = _paperless_registry()
    spec = _agent_spec()
    prior_url = os.environ.pop("PAPERLESS_URL", None)
    prior_token = os.environ.pop("PAPERLESS_API_TOKEN", None)
    try:
        entries = build_policy_entries(
            agent_name="docs",
            spec=spec,
            capabilities=reg,
        )
        module_entry = next(item for item in entries if item["key"] == "module:paperless")
        confirm_entry = next(item for item in entries if item["key"] == "confirm:paperless.tag")
        assert module_entry["state"] == "deny"
        assert confirm_entry["state"] == "confirm"
    finally:
        if prior_url is not None:
            os.environ["PAPERLESS_URL"] = prior_url
        if prior_token is not None:
            os.environ["PAPERLESS_API_TOKEN"] = prior_token


def test_normalize_permission_mode() -> None:
    assert normalize_permission_mode("acceptEdits") == "acceptEdits"
    assert normalize_permission_mode("invalid-mode") == "default"
