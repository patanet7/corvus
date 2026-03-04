"""Behavioral tests for YAML spec -> resolved tool set.

Tests the full chain: YAML agent spec -> AgentRegistry -> CapabilitiesRegistry.resolve()
-> verify each agent gets exactly the tool modules declared in their spec.

NO mocks. Real YAML files from config/agents/. Real registry instances.
Real ToolModuleEntry callables (noop implementations that pass env gates).
"""

from pathlib import Path

import pytest

from corvus.agents.registry import AgentRegistry
from corvus.agents.spec import AgentSpec
from corvus.capabilities.registry import (
    CapabilitiesRegistry,
    ToolModuleEntry,
)
from corvus.capabilities.modules import HUB_MANAGED_MODULES
from corvus.permissions import expand_confirm_gated_tools

# ---------------------------------------------------------------------------
# Project root and config directory
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS_CONFIG_DIR = PROJECT_ROOT / "config" / "agents"

# All domain tool modules known to the system (from modules.py TOOL_MODULE_DEFS)
ALL_DOMAIN_MODULES = {"obsidian", "email", "drive", "ha", "paperless", "firefly"}


# ---------------------------------------------------------------------------
# Helpers — real callables, no mocks
# ---------------------------------------------------------------------------


def _noop_configure(cfg: dict) -> dict:
    """Real configure — returns config unchanged."""
    return cfg


def _noop_create_tools(cfg: dict) -> list:
    """Real create_tools — returns a placeholder tool list."""
    return [{"name": "placeholder_tool"}]


def _noop_create_mcp_server(tools: list, cfg: dict) -> dict:
    """Real create_mcp_server — returns a server descriptor dict."""
    return {"tools": tools, "config": cfg}


def _make_entry(name: str, supports_per_agent: bool = False) -> ToolModuleEntry:
    """Build a real ToolModuleEntry with noop callables and NO env gates.

    By passing requires_env=[], every module will pass env gate checks,
    letting the test focus on which modules are *requested* by each agent.
    """
    return ToolModuleEntry(
        name=name,
        configure=_noop_configure,
        create_tools=_noop_create_tools,
        create_mcp_server=_noop_create_mcp_server,
        requires_env=[],
        supports_per_agent=supports_per_agent,
    )


def _build_capabilities_registry() -> CapabilitiesRegistry:
    """Build a CapabilitiesRegistry with all domain modules registered (no env gates).

    obsidian gets supports_per_agent=True to match the real module definition.
    """
    reg = CapabilitiesRegistry()
    for mod_name in ALL_DOMAIN_MODULES:
        per_agent = mod_name == "obsidian"
        reg.register(mod_name, _make_entry(mod_name, supports_per_agent=per_agent))
    return reg


def _load_agent_registry() -> AgentRegistry:
    """Load the real agent registry from config/agents/ YAML files."""
    registry = AgentRegistry(AGENTS_CONFIG_DIR)
    registry.load()
    return registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def agent_registry() -> AgentRegistry:
    """Shared AgentRegistry loaded from real YAML config files."""
    return _load_agent_registry()


@pytest.fixture(scope="module")
def cap_registry() -> CapabilitiesRegistry:
    """Shared CapabilitiesRegistry with all domain modules registered."""
    return _build_capabilities_registry()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestYAMLSpecToResolvedTools:
    """Full-chain tests: YAML agent spec -> AgentRegistry -> resolve() -> verify modules."""

    # -- Finance agent: only firefly ----------------------------------------

    def test_finance_agent_gets_only_firefly(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Finance YAML declares modules: {firefly: {enabled: true}}.

        After resolve(), firefly must be available. paperless, drive, ha,
        email must NOT appear in available_modules.
        """
        spec = agent_registry.get("finance")
        assert spec is not None, "finance agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "firefly" in resolved.available_modules
        for excluded in ("paperless", "drive", "ha", "email"):
            assert excluded not in resolved.available_modules, (
                f"{excluded} should not be in finance's available_modules"
            )

    # -- Docs agent: paperless + drive --------------------------------------

    def test_docs_agent_gets_paperless_and_drive(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Docs YAML declares modules: {paperless: ..., drive: ...}.

        After resolve(), both must be available. firefly, ha, email must NOT.
        """
        spec = agent_registry.get("docs")
        assert spec is not None, "docs agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "paperless" in resolved.available_modules
        assert "drive" in resolved.available_modules
        for excluded in ("firefly", "ha", "email"):
            assert excluded not in resolved.available_modules, (
                f"{excluded} should not be in docs's available_modules"
            )

    # -- Home agent: ha -----------------------------------------------------

    def test_home_agent_gets_ha(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Home YAML declares modules: {ha: {enabled: true}}.

        After resolve(), ha must be available. firefly, paperless, drive must NOT.
        """
        spec = agent_registry.get("home")
        assert spec is not None, "home agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "ha" in resolved.available_modules
        for excluded in ("firefly", "paperless", "drive"):
            assert excluded not in resolved.available_modules, (
                f"{excluded} should not be in home's available_modules"
            )

    # -- Music agent: no domain modules -------------------------------------

    def test_music_agent_has_no_domain_modules(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Music YAML declares modules: {}. No domain modules should resolve."""
        spec = agent_registry.get("music")
        assert spec is not None, "music agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert resolved.available_modules == [], (
            f"music should have no available domain modules, got {resolved.available_modules}"
        )

    # -- General agent: obsidian (read-only) --------------------------------

    def test_general_agent_gets_obsidian_only(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """General YAML declares modules: {obsidian: {read: true, write: false}}.

        After resolve(), obsidian must be available. firefly, paperless, drive,
        ha, email must NOT.
        """
        spec = agent_registry.get("general")
        assert spec is not None, "general agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "obsidian" in resolved.available_modules
        for excluded in ("firefly", "paperless", "drive", "ha", "email"):
            assert excluded not in resolved.available_modules, (
                f"{excluded} should not be in general's available_modules"
            )

    # -- Email agent: email module ------------------------------------------

    def test_email_agent_gets_email_module(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Email YAML declares modules: {email: {enabled: true}}."""
        spec = agent_registry.get("email")
        assert spec is not None, "email agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "email" in resolved.available_modules
        for excluded in ("firefly", "paperless", "ha"):
            assert excluded not in resolved.available_modules

    # -- Work agent: obsidian + email + drive --------------------------------

    def test_work_agent_gets_obsidian_email_drive(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Work YAML declares modules: {obsidian, email, drive}."""
        spec = agent_registry.get("work")
        assert spec is not None, "work agent not found in config/agents/"

        resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)

        assert "obsidian" in resolved.available_modules
        assert "email" in resolved.available_modules
        assert "drive" in resolved.available_modules
        for excluded in ("firefly", "paperless", "ha"):
            assert excluded not in resolved.available_modules

    # -- All agents load without error --------------------------------------

    def test_all_agents_load_without_error(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Every YAML spec in config/agents/ must parse, load, and be resolvable."""
        all_specs = agent_registry.list_all()
        assert len(all_specs) > 0, "No agent specs loaded from config/agents/"

        for spec in all_specs:
            assert isinstance(spec, AgentSpec), f"Expected AgentSpec, got {type(spec)}"
            assert spec.name, f"Agent spec has empty name"
            assert spec.description, f"Agent {spec.name} has empty description"

            # resolve() must not raise
            resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)
            assert resolved is not None, f"resolve() returned None for {spec.name}"

    # -- Resolved modules match YAML declaration exactly --------------------

    def test_resolved_modules_match_yaml_declaration(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """For every agent, the set of available modules after resolve() must
        equal exactly the set of modules declared in the agent's YAML spec
        (minus hub-managed modules like 'memory').
        """
        expected_modules = {
            "finance": {"firefly"},
            "docs": {"paperless", "drive"},
            "home": {"ha"},
            "music": set(),
            "general": {"obsidian"},
            "email": {"email"},
            "personal": {"obsidian"},
            "work": {"obsidian", "email", "drive"},
            "homelab": {"obsidian"},
            "huginn": {"obsidian"},
        }

        for agent_name, expected in expected_modules.items():
            spec = agent_registry.get(agent_name)
            assert spec is not None, f"{agent_name} not found in registry"

            resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)
            actual = set(resolved.available_modules)

            assert actual == expected, (
                f"Agent '{agent_name}': expected modules {expected}, got {actual}"
            )

    # -- Unavailable modules dict is empty when all gates pass ---------------

    def test_no_unavailable_modules_when_all_registered(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """When all modules are registered and have no env gates,
        unavailable_modules should be empty for every agent.
        """
        for spec in agent_registry.list_all():
            resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)
            assert resolved.unavailable_modules == {}, (
                f"Agent '{spec.name}' has unexpected unavailable modules: "
                f"{resolved.unavailable_modules}"
            )

    # -- Per-agent naming for obsidian servers --------------------------------

    def test_obsidian_servers_named_per_agent(
        self, agent_registry: AgentRegistry, cap_registry: CapabilitiesRegistry
    ):
        """Obsidian has supports_per_agent=True, so its MCP server key should
        be 'obsidian_{agent_name}' for each agent that uses it.
        """
        agents_with_obsidian = ["general", "personal", "work", "homelab", "huginn"]

        for agent_name in agents_with_obsidian:
            spec = agent_registry.get(agent_name)
            assert spec is not None

            resolved = cap_registry.resolve(spec, skip_modules=HUB_MANAGED_MODULES)
            expected_key = f"obsidian_{agent_name}"

            assert expected_key in resolved.mcp_servers, (
                f"Agent '{agent_name}': expected MCP server key '{expected_key}', "
                f"got keys {list(resolved.mcp_servers.keys())}"
            )
            # Plain 'obsidian' should NOT be a key (per-agent naming replaces it)
            assert "obsidian" not in resolved.mcp_servers


# ---------------------------------------------------------------------------
# Confirm-gated expansion tests
# ---------------------------------------------------------------------------


class TestConfirmGatedExpansion:
    """Verify confirm_gated short names expand to full MCP tool names."""

    def test_finance_gated_tools(self, agent_registry: AgentRegistry) -> None:
        """Finance declares confirm_gated: [firefly.create_transaction].

        Expansion must include the short name plus both MCP forms
        (with and without agent suffix).
        """
        spec = agent_registry.get("finance")
        assert spec is not None, "finance agent not found in config/agents/"

        expanded = expand_confirm_gated_tools("finance", spec.tools.confirm_gated)

        # Short name preserved
        assert "firefly.create_transaction" in expanded
        # MCP form with agent suffix: mcp__{module}_{agent}__{module}_{action}
        assert "mcp__firefly_finance__firefly_create_transaction" in expanded
        # MCP form without agent suffix: mcp__{module}__{module}_{action}
        assert "mcp__firefly__firefly_create_transaction" in expanded

    def test_docs_gated_tools(self, agent_registry: AgentRegistry) -> None:
        """Docs declares confirm_gated for paperless and drive tools.

        All short names and their MCP expansions must be present.
        """
        spec = agent_registry.get("docs")
        assert spec is not None, "docs agent not found in config/agents/"

        expanded = expand_confirm_gated_tools("docs", spec.tools.confirm_gated)

        # Short names preserved
        assert "paperless.tag" in expanded
        assert "paperless.bulk_edit" in expanded
        assert "drive.delete" in expanded
        assert "drive.permanent_delete" in expanded
        assert "drive.share" in expanded
        assert "drive.cleanup" in expanded

        # MCP forms with agent suffix
        assert "mcp__paperless_docs__paperless_tag" in expanded
        assert "mcp__paperless_docs__paperless_bulk_edit" in expanded
        assert "mcp__drive_docs__drive_delete" in expanded
        assert "mcp__drive_docs__drive_permanent_delete" in expanded
        assert "mcp__drive_docs__drive_share" in expanded
        assert "mcp__drive_docs__drive_cleanup" in expanded

        # MCP forms without agent suffix
        assert "mcp__paperless__paperless_tag" in expanded
        assert "mcp__drive__drive_delete" in expanded

    def test_home_gated_tools(self, agent_registry: AgentRegistry) -> None:
        """Home declares confirm_gated: [ha.call_service].

        Expansion must include both MCP forms.
        """
        spec = agent_registry.get("home")
        assert spec is not None, "home agent not found in config/agents/"

        expanded = expand_confirm_gated_tools("home", spec.tools.confirm_gated)

        assert "ha.call_service" in expanded
        assert "mcp__ha_home__ha_call_service" in expanded
        assert "mcp__ha__ha_call_service" in expanded

    def test_general_has_no_gated_tools(self, agent_registry: AgentRegistry) -> None:
        """General declares confirm_gated: []. Expansion must be empty."""
        spec = agent_registry.get("general")
        assert spec is not None, "general agent not found in config/agents/"

        expanded = expand_confirm_gated_tools("general", spec.tools.confirm_gated)

        assert len(expanded) == 0, f"Expected empty set, got {expanded}"

    def test_expansion_returns_set(self, agent_registry: AgentRegistry) -> None:
        """expand_confirm_gated_tools must return a set."""
        spec = agent_registry.get("finance")
        assert spec is not None

        expanded = expand_confirm_gated_tools("finance", spec.tools.confirm_gated)
        assert isinstance(expanded, set), f"Expected set, got {type(expanded)}"

    def test_expansion_count_matches_expected(
        self, agent_registry: AgentRegistry
    ) -> None:
        """Each dotted short name produces 3 entries (short + 2 MCP forms).

        finance has 1 confirm_gated entry -> 3 expanded.
        home has 1 -> 3.
        docs has 6 -> 18.
        general has 0 -> 0.
        """
        expected_counts = {
            "finance": 3,   # 1 short name * 3
            "home": 3,      # 1 short name * 3
            "docs": 18,     # 6 short names * 3
            "general": 0,
        }

        for agent_name, expected in expected_counts.items():
            spec = agent_registry.get(agent_name)
            assert spec is not None
            expanded = expand_confirm_gated_tools(agent_name, spec.tools.confirm_gated)
            assert len(expanded) == expected, (
                f"Agent '{agent_name}': expected {expected} expanded entries, "
                f"got {len(expanded)}: {expanded}"
            )
