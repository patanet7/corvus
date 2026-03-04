"""Behavioral tests for CapabilitiesRegistry — security-enforced tool resolution.

NO mocks. Uses real CapabilitiesRegistry instances, real AgentSpec dataclasses,
real env-var manipulation via os.environ (direct, not monkeypatch).

Covers:
- Register and list modules
- Register duplicate raises ValueError
- resolve() with available env -> module in available_modules
- resolve() with missing env -> module in unavailable_modules
- resolve() with unregistered module -> unavailable
- resolve() with empty modules -> empty available
- resolve() with supports_per_agent naming
- confirm_gated from spec
- health for registered vs unknown module
- get_module for registered vs unknown module
- is_allowed checks
"""

import os

import pytest

from corvus.agents.spec import AgentSpec, AgentToolConfig
from corvus.capabilities.registry import (
    CapabilitiesRegistry,
    ModuleHealth,
    ResolvedTools,
    ToolModuleEntry,
)

# ---------------------------------------------------------------------------
# Helpers — real callables (no mocks)
# ---------------------------------------------------------------------------


def _noop_configure(cfg: dict) -> dict:
    """Real configure function that just returns the config."""
    return cfg


def _noop_create_tools(cfg: dict) -> list:
    """Real create_tools function that returns a list of tool descriptors."""
    return [{"name": f"tool_{k}", "value": v} for k, v in cfg.items()]


def _noop_create_mcp_server(tools: list, cfg: dict) -> dict:
    """Real create_mcp_server function that returns a server descriptor."""
    return {"tools": tools, "config": cfg}


def _healthy_check() -> ModuleHealth:
    """Real health check that returns healthy."""
    return ModuleHealth(name="test", status="healthy", detail="all good")


def _unhealthy_check() -> ModuleHealth:
    """Real health check that returns unhealthy."""
    return ModuleHealth(name="test", status="unhealthy", detail="connection refused")


def _make_entry(
    name: str = "paperless",
    requires_env: list[str] | None = None,
    supports_per_agent: bool = False,
    health_check=None,
    restart=None,
) -> ToolModuleEntry:
    """Create a real ToolModuleEntry with real callables."""
    return ToolModuleEntry(
        name=name,
        configure=_noop_configure,
        create_tools=_noop_create_tools,
        create_mcp_server=_noop_create_mcp_server,
        requires_env=requires_env or [],
        supports_per_agent=supports_per_agent,
        health_check=health_check,
        restart=restart,
    )


def _make_agent_spec(
    name: str = "docs",
    modules: dict | None = None,
    confirm_gated: list[str] | None = None,
) -> AgentSpec:
    """Create a real AgentSpec with the given tool modules."""
    return AgentSpec(
        name=name,
        description=f"Agent for {name} domain",
        tools=AgentToolConfig(
            modules=modules or {},
            confirm_gated=confirm_gated or [],
        ),
    )


@pytest.fixture(autouse=True)
def _clean_test_env_vars():
    """Save and restore env vars used by tests to avoid cross-test pollution."""
    test_vars = [
        "PAPERLESS_URL",
        "PAPERLESS_TOKEN",
        "FIREFLY_URL",
        "FIREFLY_TOKEN",
    ]
    saved = {k: os.environ.get(k) for k in test_vars}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# 1. ModuleHealth dataclass
# ---------------------------------------------------------------------------


class TestModuleHealth:
    """ModuleHealth should have sensible defaults and support custom values."""

    def test_defaults(self):
        h = ModuleHealth(name="test_mod")
        assert h.name == "test_mod"
        assert h.status == "healthy"
        assert h.detail == ""

    def test_custom_values(self):
        h = ModuleHealth(name="firefly", status="unhealthy", detail="timeout")
        assert h.name == "firefly"
        assert h.status == "unhealthy"
        assert h.detail == "timeout"


# ---------------------------------------------------------------------------
# 2. ToolModuleEntry dataclass
# ---------------------------------------------------------------------------


class TestToolModuleEntry:
    """ToolModuleEntry holds callables and metadata for a tool module."""

    def test_defaults(self):
        entry = _make_entry("paperless")
        assert entry.name == "paperless"
        assert entry.requires_env == []
        assert entry.supports_per_agent is False
        assert entry.health_check is None
        assert entry.restart is None

    def test_custom_env_requirements(self):
        entry = _make_entry("firefly", requires_env=["FIREFLY_URL", "FIREFLY_TOKEN"])
        assert entry.requires_env == ["FIREFLY_URL", "FIREFLY_TOKEN"]

    def test_supports_per_agent(self):
        entry = _make_entry("obsidian", supports_per_agent=True)
        assert entry.supports_per_agent is True

    def test_callables_are_real(self):
        entry = _make_entry("test")
        cfg = {"url": "http://localhost"}
        configured = entry.configure(cfg)
        assert configured == cfg
        tools = entry.create_tools(cfg)
        assert len(tools) == 1
        assert tools[0]["name"] == "tool_url"
        server = entry.create_mcp_server(tools, cfg)
        assert "tools" in server


# ---------------------------------------------------------------------------
# 3. ResolvedTools dataclass
# ---------------------------------------------------------------------------


class TestResolvedTools:
    """ResolvedTools should have sensible empty defaults."""

    def test_defaults(self):
        rt = ResolvedTools()
        assert rt.mcp_servers == {}
        assert rt.confirm_gated == set()
        assert rt.available_modules == []
        assert rt.unavailable_modules == {}

    def test_mutable_defaults_independent(self):
        a = ResolvedTools()
        b = ResolvedTools()
        a.available_modules.append("paperless")
        assert b.available_modules == []


# ---------------------------------------------------------------------------
# 4. Register and list modules
# ---------------------------------------------------------------------------


class TestRegisterAndList:
    """register() adds modules; list_available() enumerates them."""

    def test_register_single(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless"))
        assert "paperless" in reg.list_available()

    def test_register_multiple(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless"))
        reg.register("firefly", _make_entry("firefly"))
        reg.register("komodo", _make_entry("komodo"))
        available = reg.list_available()
        assert len(available) == 3
        assert set(available) == {"paperless", "firefly", "komodo"}

    def test_list_empty(self):
        reg = CapabilitiesRegistry()
        assert reg.list_available() == []

    def test_register_duplicate_raises(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless"))
        with pytest.raises(ValueError, match="paperless"):
            reg.register("paperless", _make_entry("paperless"))


# ---------------------------------------------------------------------------
# 5. get_module
# ---------------------------------------------------------------------------


class TestGetModule:
    """get_module() returns the entry or None."""

    def test_get_registered(self):
        reg = CapabilitiesRegistry()
        entry = _make_entry("paperless")
        reg.register("paperless", entry)
        assert reg.get_module("paperless") is entry

    def test_get_unknown_returns_none(self):
        reg = CapabilitiesRegistry()
        assert reg.get_module("nonexistent") is None


# ---------------------------------------------------------------------------
# 6. resolve() — available env
# ---------------------------------------------------------------------------


class TestResolveAvailableEnv:
    """resolve() with all required env vars set puts module in available_modules."""

    def test_module_with_env_satisfied(self):
        os.environ["PAPERLESS_URL"] = "http://localhost:8000"
        os.environ["PAPERLESS_TOKEN"] = "test-token-123"

        reg = CapabilitiesRegistry()
        reg.register(
            "paperless",
            _make_entry("paperless", requires_env=["PAPERLESS_URL", "PAPERLESS_TOKEN"]),
        )

        spec = _make_agent_spec(
            name="docs",
            modules={"paperless": {"url": "http://localhost:8000"}},
        )
        resolved = reg.resolve(spec)

        assert "paperless" in resolved.available_modules
        assert "paperless" not in resolved.unavailable_modules
        assert "paperless" in resolved.mcp_servers

    def test_module_with_no_env_requirements(self):
        reg = CapabilitiesRegistry()
        reg.register("basic", _make_entry("basic", requires_env=[]))

        spec = _make_agent_spec(name="test", modules={"basic": {}})
        resolved = reg.resolve(spec)

        assert "basic" in resolved.available_modules
        assert "basic" in resolved.mcp_servers


# ---------------------------------------------------------------------------
# 7. resolve() — missing env
# ---------------------------------------------------------------------------


class TestResolveMissingEnv:
    """resolve() with missing required env vars puts module in unavailable_modules."""

    def test_module_with_missing_env(self):
        os.environ.pop("FIREFLY_URL", None)
        os.environ.pop("FIREFLY_TOKEN", None)

        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", requires_env=["FIREFLY_URL", "FIREFLY_TOKEN"]),
        )

        spec = _make_agent_spec(name="finance", modules={"firefly": {}})
        resolved = reg.resolve(spec)

        assert "firefly" not in resolved.available_modules
        assert "firefly" in resolved.unavailable_modules
        assert "FIREFLY_URL" in resolved.unavailable_modules["firefly"]
        assert "firefly" not in resolved.mcp_servers

    def test_module_with_partial_env(self):
        os.environ["FIREFLY_URL"] = "http://localhost:8080"
        os.environ.pop("FIREFLY_TOKEN", None)

        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", requires_env=["FIREFLY_URL", "FIREFLY_TOKEN"]),
        )

        spec = _make_agent_spec(name="finance", modules={"firefly": {}})
        resolved = reg.resolve(spec)

        assert "firefly" not in resolved.available_modules
        assert "firefly" in resolved.unavailable_modules
        assert "FIREFLY_TOKEN" in resolved.unavailable_modules["firefly"]

    def test_module_with_empty_env_value(self):
        os.environ["FIREFLY_URL"] = "http://localhost:8080"
        os.environ["FIREFLY_TOKEN"] = "   "

        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", requires_env=["FIREFLY_URL", "FIREFLY_TOKEN"]),
        )

        spec = _make_agent_spec(name="finance", modules={"firefly": {}})
        resolved = reg.resolve(spec)

        assert "firefly" not in resolved.available_modules
        assert "firefly" in resolved.unavailable_modules
        assert "FIREFLY_TOKEN" in resolved.unavailable_modules["firefly"]


# ---------------------------------------------------------------------------
# 8. resolve() — unregistered module
# ---------------------------------------------------------------------------


class TestResolveUnregistered:
    """resolve() with an unregistered module puts it in unavailable_modules."""

    def test_unregistered_module(self):
        reg = CapabilitiesRegistry()

        spec = _make_agent_spec(name="test", modules={"ghost": {}})
        resolved = reg.resolve(spec)

        assert "ghost" not in resolved.available_modules
        assert "ghost" in resolved.unavailable_modules
        assert "not registered" in resolved.unavailable_modules["ghost"].lower()
        assert "ghost" not in resolved.mcp_servers


# ---------------------------------------------------------------------------
# 9. resolve() — empty modules
# ---------------------------------------------------------------------------


class TestResolveEmptyModules:
    """resolve() with empty modules produces empty resolved."""

    def test_empty_modules(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless"))

        spec = _make_agent_spec(name="test", modules={})
        resolved = reg.resolve(spec)

        assert resolved.available_modules == []
        assert resolved.unavailable_modules == {}
        assert resolved.mcp_servers == {}


# ---------------------------------------------------------------------------
# 10. resolve() — supports_per_agent naming
# ---------------------------------------------------------------------------


class TestResolvePerAgent:
    """When supports_per_agent=True, MCP server name includes agent name."""

    def test_per_agent_naming(self):
        reg = CapabilitiesRegistry()
        reg.register("obsidian", _make_entry("obsidian", supports_per_agent=True))

        spec = _make_agent_spec(name="personal", modules={"obsidian": {"vault": "~/vault"}})
        resolved = reg.resolve(spec)

        assert "obsidian" in resolved.available_modules
        assert "obsidian_personal" in resolved.mcp_servers
        assert "obsidian" not in resolved.mcp_servers

    def test_non_per_agent_naming(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless", supports_per_agent=False))

        spec = _make_agent_spec(name="docs", modules={"paperless": {}})
        resolved = reg.resolve(spec)

        assert "paperless" in resolved.mcp_servers
        assert "paperless_docs" not in resolved.mcp_servers


# ---------------------------------------------------------------------------
# 11. confirm_gated from spec
# ---------------------------------------------------------------------------


class TestConfirmGated:
    """confirm_gated() returns the set of confirm-gated tool names from AgentSpec."""

    def test_confirm_gated_from_spec(self):
        reg = CapabilitiesRegistry()
        spec = _make_agent_spec(
            name="finance",
            confirm_gated=[
                "mcp__firefly__create_transaction",
                "mcp__firefly__delete_transaction",
            ],
        )
        gated = reg.confirm_gated(spec)
        assert isinstance(gated, set)
        assert gated == {
            "mcp__firefly__create_transaction",
            "mcp__firefly__delete_transaction",
        }

    def test_confirm_gated_empty(self):
        reg = CapabilitiesRegistry()
        spec = _make_agent_spec(name="test", confirm_gated=[])
        gated = reg.confirm_gated(spec)
        assert gated == set()

    def test_confirm_gated_in_resolve(self):
        reg = CapabilitiesRegistry()
        reg.register("firefly", _make_entry("firefly"))

        spec = _make_agent_spec(
            name="finance",
            modules={"firefly": {}},
            confirm_gated=["mcp__firefly__create_transaction"],
        )
        resolved = reg.resolve(spec)
        assert "mcp__firefly__create_transaction" in resolved.confirm_gated


# ---------------------------------------------------------------------------
# 12. health() for registered vs unknown module
# ---------------------------------------------------------------------------


class TestHealth:
    """health() returns ModuleHealth for registered modules."""

    def test_health_with_health_check(self):
        reg = CapabilitiesRegistry()
        reg.register(
            "paperless",
            _make_entry("paperless", health_check=_healthy_check),
        )
        result = reg.health("paperless")
        assert result.name == "paperless"
        assert result.status == "healthy"
        assert result.detail == "all good"

    def test_health_unhealthy(self):
        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", health_check=_unhealthy_check),
        )
        result = reg.health("firefly")
        assert result.name == "firefly"
        assert result.status == "unhealthy"

    def test_health_no_health_check(self):
        reg = CapabilitiesRegistry()
        reg.register("basic", _make_entry("basic", health_check=None))
        result = reg.health("basic")
        assert result.name == "basic"
        assert result.status == "unknown"

    def test_health_unknown_module(self):
        reg = CapabilitiesRegistry()
        result = reg.health("nonexistent")
        assert result.name == "nonexistent"
        assert result.status == "unknown"
        assert "not registered" in result.detail.lower()


# ---------------------------------------------------------------------------
# 13. is_allowed checks
# ---------------------------------------------------------------------------


class TestIsAllowed:
    """is_allowed() verifies whether an agent can access a tool module."""

    def test_allowed_registered_module(self):
        os.environ["PAPERLESS_URL"] = "http://localhost:8000"

        reg = CapabilitiesRegistry()
        reg.register(
            "paperless",
            _make_entry("paperless", requires_env=["PAPERLESS_URL"]),
        )

        assert reg.is_allowed("docs", "paperless") is True

    def test_not_allowed_missing_env(self):
        os.environ.pop("FIREFLY_TOKEN", None)

        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", requires_env=["FIREFLY_TOKEN"]),
        )

        assert reg.is_allowed("finance", "firefly") is False

    def test_not_allowed_empty_env(self):
        os.environ["FIREFLY_TOKEN"] = ""

        reg = CapabilitiesRegistry()
        reg.register(
            "firefly",
            _make_entry("firefly", requires_env=["FIREFLY_TOKEN"]),
        )

        assert reg.is_allowed("finance", "firefly") is False

    def test_not_allowed_unregistered(self):
        reg = CapabilitiesRegistry()
        assert reg.is_allowed("test", "nonexistent") is False


# ---------------------------------------------------------------------------
# 14. resolve() creates valid MCP server structures
# ---------------------------------------------------------------------------


class TestResolveMCPServerStructure:
    """resolve() creates MCP server entries via create_tools + create_mcp_server."""

    def test_mcp_server_has_tools_and_config(self):
        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless"))

        spec = _make_agent_spec(
            name="docs",
            modules={"paperless": {"url": "http://localhost:8000"}},
        )
        resolved = reg.resolve(spec)

        server = resolved.mcp_servers["paperless"]
        assert "tools" in server
        assert "config" in server
        assert len(server["tools"]) == 1
        assert server["tools"][0]["name"] == "tool_url"

    def test_multiple_modules_resolved(self):
        os.environ["FIREFLY_TOKEN"] = "test-token"
        os.environ["PAPERLESS_TOKEN"] = "test-token"

        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless", requires_env=["PAPERLESS_TOKEN"]))
        reg.register("firefly", _make_entry("firefly", requires_env=["FIREFLY_TOKEN"]))

        spec = _make_agent_spec(
            name="multi",
            modules={
                "paperless": {"url": "http://localhost:8000"},
                "firefly": {"url": "http://localhost:8080"},
            },
        )
        resolved = reg.resolve(spec)

        assert set(resolved.available_modules) == {"paperless", "firefly"}
        assert "paperless" in resolved.mcp_servers
        assert "firefly" in resolved.mcp_servers

    def test_mixed_available_and_unavailable(self):
        os.environ["PAPERLESS_TOKEN"] = "test-token"
        os.environ.pop("FIREFLY_TOKEN", None)

        reg = CapabilitiesRegistry()
        reg.register("paperless", _make_entry("paperless", requires_env=["PAPERLESS_TOKEN"]))
        reg.register("firefly", _make_entry("firefly", requires_env=["FIREFLY_TOKEN"]))

        spec = _make_agent_spec(
            name="multi",
            modules={
                "paperless": {},
                "firefly": {},
            },
        )
        resolved = reg.resolve(spec)

        assert "paperless" in resolved.available_modules
        assert "firefly" in resolved.unavailable_modules
        assert "paperless" in resolved.mcp_servers
        assert "firefly" not in resolved.mcp_servers
