# CLI MCP Tools Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give `corvus chat` agents access to their full domain toolset via a stdio MCP bridge server that wraps existing Python tool functions, plus support for external MCP servers declared in agent.yaml.

**Architecture:** A new `corvus/cli/mcp_bridge.py` is a FastMCP stdio server that imports and registers the same tool functions from `corvus/tools/*` and `corvus/memory/toolkit.py`. A new `corvus/cli/mcp_config.py` generates per-agent MCP config JSON by running `CapabilitiesRegistry.resolve()` to determine allowed tools, cherry-picking env vars, and merging any external MCP servers from the agent spec. `corvus/cli/chat.py` calls this at launch and passes `--mcp-config` to the claude subprocess.

**Tech Stack:** Python 3.13, `mcp` SDK (FastMCP), existing `corvus/tools/*` functions, `corvus/capabilities/registry.py`

**Design Doc:** `docs/plans/2026-03-07-cli-mcp-tools-design.md`

---

### Task 1: Add `mcp_servers` field to `AgentToolConfig`

**Files:**
- Modify: `corvus/agents/spec.py:52-58`
- Test: `tests/unit/test_agent_spec_mcp_servers.py`

**Step 1: Write the failing test**

Create `tests/unit/test_agent_spec_mcp_servers.py`:

```python
"""Tests for mcp_servers field on AgentToolConfig and AgentSpec."""

from corvus.agents.spec import AgentSpec, AgentToolConfig


class TestMcpServersField:
    def test_tool_config_defaults_to_empty_list(self) -> None:
        cfg = AgentToolConfig()
        assert cfg.mcp_servers == []

    def test_tool_config_accepts_mcp_servers(self) -> None:
        servers = [
            {"name": "komodo", "command": "npx", "args": ["-y", "@komodo/mcp"]},
        ]
        cfg = AgentToolConfig(mcp_servers=servers)
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0]["name"] == "komodo"

    def test_spec_from_dict_with_mcp_servers(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {
                "builtin": ["Bash"],
                "modules": {},
                "confirm_gated": [],
                "mcp_servers": [
                    {
                        "name": "ext-server",
                        "command": "some-binary",
                        "args": ["--flag"],
                        "env": {"KEY": "val"},
                    }
                ],
            },
        }
        spec = AgentSpec.from_dict(data)
        assert len(spec.tools.mcp_servers) == 1
        assert spec.tools.mcp_servers[0]["name"] == "ext-server"

    def test_spec_from_dict_without_mcp_servers(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {"builtin": ["Bash"], "modules": {}, "confirm_gated": []},
        }
        spec = AgentSpec.from_dict(data)
        assert spec.tools.mcp_servers == []

    def test_spec_to_dict_roundtrip(self) -> None:
        data = {
            "name": "test",
            "description": "Test agent",
            "tools": {
                "builtin": [],
                "modules": {},
                "confirm_gated": [],
                "mcp_servers": [{"name": "x", "command": "y", "args": []}],
            },
        }
        spec = AgentSpec.from_dict(data)
        out = spec.to_dict()
        assert out["tools"]["mcp_servers"] == [{"name": "x", "command": "y", "args": []}]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agent_spec_mcp_servers.py -v`
Expected: FAIL — `AgentToolConfig.__init__() got an unexpected keyword argument 'mcp_servers'`

**Step 3: Add `mcp_servers` field to `AgentToolConfig`**

In `corvus/agents/spec.py`, add the field to `AgentToolConfig` (after `confirm_gated`):

```python
@dataclass
class AgentToolConfig:
    """Allowed tools and MCP module bindings for an agent."""

    builtin: list[str] = field(default_factory=list)
    modules: dict[str, dict] = field(default_factory=dict)
    confirm_gated: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_agent_spec_mcp_servers.py -v`
Expected: All 5 PASS

**Step 5: Run existing spec tests to verify no regressions**

Run: `uv run pytest tests/ -k "spec" -v --timeout=30`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/agents/spec.py tests/unit/test_agent_spec_mcp_servers.py
git commit -m "feat: add mcp_servers field to AgentToolConfig

Agents can now declare external MCP servers in their tools config.
These are merged into the generated MCP config at CLI launch time."
```

---

### Task 2: Create `corvus/cli/mcp_config.py` — MCP config generator

**Files:**
- Create: `corvus/cli/mcp_config.py`
- Test: `tests/unit/test_mcp_config.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_mcp_config.py`:

```python
"""Tests for MCP config generation for CLI agents."""

import json
import os
from pathlib import Path

import pytest

from corvus.cli.mcp_config import build_mcp_config, resolve_bridge_env


class TestResolveBridgeEnv:
    """Test env var cherry-picking for the bridge server."""

    def test_picks_only_required_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.setenv("HA_TOKEN", "secret-token")
        monkeypatch.setenv("UNRELATED", "should-not-appear")
        result = resolve_bridge_env(requires_env=["HA_URL", "HA_TOKEN"])
        assert result == {"HA_URL": "http://ha.local", "HA_TOKEN": "secret-token"}
        assert "UNRELATED" not in result

    def test_skips_missing_vars(self, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.delenv("HA_TOKEN", raising=False)
        result = resolve_bridge_env(requires_env=["HA_URL", "HA_TOKEN"])
        assert result == {"HA_URL": "http://ha.local"}

    def test_empty_requires(self) -> None:
        result = resolve_bridge_env(requires_env=[])
        assert result == {}


class TestBuildMcpConfig:
    """Test full MCP config JSON generation."""

    def test_generates_bridge_entry(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local")
        monkeypatch.setenv("HA_TOKEN", "tok")
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={"ha": {}},
            requires_env_by_module={"ha": ["HA_URL", "HA_TOKEN"]},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "corvus-tools" in data["mcpServers"]
        bridge = data["mcpServers"]["corvus-tools"]
        assert bridge["command"] == "uv"
        assert "--agent" in bridge["args"]
        assert "homelab" in bridge["args"]
        assert bridge["env"]["HA_URL"] == "http://ha.local"
        assert bridge["env"]["HA_TOKEN"] == "tok"

    def test_includes_external_servers(self, tmp_path: Path) -> None:
        externals = [
            {
                "name": "komodo-mcp",
                "command": "npx",
                "args": ["-y", "@komodo/mcp"],
                "env": {"KEY": "val"},
            }
        ]
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        data = json.loads(config_path.read_text())
        assert "komodo-mcp" in data["mcpServers"]
        ext = data["mcpServers"]["komodo-mcp"]
        assert ext["command"] == "npx"
        assert ext["env"]["KEY"] == "val"

    def test_resolves_env_vars_in_external(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "resolved-val")
        externals = [
            {"name": "ext", "command": "bin", "args": [], "env": {"TOK": "${MY_TOKEN}"}},
        ]
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="shared",
        )
        data = json.loads(config_path.read_text())
        assert data["mcpServers"]["ext"]["env"]["TOK"] == "resolved-val"

    def test_http_transport_external(self, tmp_path: Path) -> None:
        externals = [
            {"name": "loki", "transport": "http", "url": "http://localhost:3100/mcp"},
        ]
        config_path = build_mcp_config(
            agent_name="homelab",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=externals,
            output_dir=tmp_path,
            memory_domain="homelab",
        )
        data = json.loads(config_path.read_text())
        assert "loki" in data["mcpServers"]
        loki = data["mcpServers"]["loki"]
        assert loki["url"] == "http://localhost:3100/mcp"
        assert loki.get("type") == "http"

    def test_file_permissions(self, tmp_path: Path) -> None:
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="shared",
        )
        stat = config_path.stat()
        assert oct(stat.st_mode & 0o777) == "0o600"

    def test_no_bridge_when_no_modules(self, tmp_path: Path) -> None:
        config_path = build_mcp_config(
            agent_name="test",
            module_configs={},
            requires_env_by_module={},
            external_mcp_servers=[],
            output_dir=tmp_path,
            memory_domain="shared",
        )
        data = json.loads(config_path.read_text())
        # Bridge should still exist for memory tools even with no modules
        assert "corvus-tools" in data["mcpServers"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mcp_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.cli.mcp_config'`

**Step 3: Implement `corvus/cli/mcp_config.py`**

```python
"""Generate per-agent MCP config JSON for corvus chat CLI.

Builds a config file that tells the claude subprocess which MCP servers
to connect to. The primary entry is the corvus-tools bridge server
(wrapping our Python tool functions). External MCP servers from agent.yaml
are merged alongside it.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def resolve_bridge_env(requires_env: list[str]) -> dict[str, str]:
    """Cherry-pick only the required env vars for the bridge server.

    Returns a dict of var_name -> value for vars that exist and are non-empty.
    Missing vars are silently skipped (the bridge will fail gracefully).
    """
    env: dict[str, str] = {}
    for var in requires_env:
        value = os.environ.get(var, "").strip()
        if value:
            env[var] = value
    return env


def _resolve_env_references(env: dict[str, str]) -> dict[str, str]:
    """Resolve ${VAR} references in env values from os.environ."""
    resolved: dict[str, str] = {}
    pattern = re.compile(r"\$\{([^}]+)\}")
    for key, value in env.items():
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        resolved[key] = pattern.sub(_replace, value)
    return resolved


def _build_external_entry(server: dict) -> dict:
    """Build a single MCP config entry from an external server declaration."""
    transport = server.get("transport", "stdio")

    if transport == "http":
        entry: dict = {"type": "http", "url": server["url"]}
        if "env" in server:
            entry["env"] = _resolve_env_references(server["env"])
        return entry

    # stdio transport (default)
    entry = {
        "command": server["command"],
        "args": server.get("args", []),
    }
    if "env" in server:
        entry["env"] = _resolve_env_references(server["env"])
    return entry


def build_mcp_config(
    *,
    agent_name: str,
    module_configs: dict[str, dict],
    requires_env_by_module: dict[str, list[str]],
    external_mcp_servers: list[dict],
    output_dir: Path,
    memory_domain: str,
) -> Path:
    """Generate MCP config JSON and write it to output_dir.

    Args:
        agent_name: Agent name for the bridge server.
        module_configs: Dict of module_name -> module config from agent spec.
        requires_env_by_module: Dict of module_name -> list of required env vars.
        external_mcp_servers: List of external MCP server dicts from agent.yaml.
        output_dir: Directory to write the config file to.
        memory_domain: Agent's memory domain for the memory toolkit.

    Returns:
        Path to the written config file.
    """
    mcp_servers: dict[str, dict] = {}

    # 1. Bridge server — wraps our Python tools + memory
    all_required_env: list[str] = []
    for module_name in module_configs:
        all_required_env.extend(requires_env_by_module.get(module_name, []))
    bridge_env = resolve_bridge_env(list(set(all_required_env)))

    modules_json = json.dumps(module_configs)
    mcp_servers["corvus-tools"] = {
        "command": sys.executable.replace("/bin/python", "/bin/uv") if "uv" not in sys.executable else sys.executable,
        "args": [
            "run", "python", "-m", "corvus.cli.mcp_bridge",
            "--agent", agent_name,
            "--modules-json", modules_json,
            "--memory-domain", memory_domain,
        ],
        "env": bridge_env,
    }
    # Use uv reliably
    mcp_servers["corvus-tools"]["command"] = "uv"

    # 2. External MCP servers from agent.yaml
    for server in external_mcp_servers:
        name = server.get("name", "unnamed")
        mcp_servers[name] = _build_external_entry(server)

    config = {"mcpServers": mcp_servers}
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / ".corvus-mcp.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    config_path.chmod(0o600)
    return config_path
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_mcp_config.py -v`
Expected: All 7 PASS

**Step 5: Commit**

```bash
git add corvus/cli/mcp_config.py tests/unit/test_mcp_config.py
git commit -m "feat: MCP config generator for CLI agents

build_mcp_config() generates per-agent MCP config JSON with:
- corvus-tools bridge entry (wraps Python tool functions + memory)
- external MCP servers from agent.yaml mcp_servers field
- env var cherry-picking (only required vars, ${VAR} resolution)
- 0600 file permissions for credential protection"
```

---

### Task 3: Create `corvus/cli/mcp_bridge.py` — stdio MCP bridge server

**Files:**
- Create: `corvus/cli/mcp_bridge.py`
- Test: `tests/unit/test_mcp_bridge.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_mcp_bridge.py`:

```python
"""Tests for the MCP bridge server tool registration."""

import json

import pytest

from corvus.cli.mcp_bridge import register_module_tools, register_memory_tools


class TestRegisterModuleTools:
    """Test that module tools are registered on a FastMCP server."""

    def test_registers_ha_tools(self) -> None:
        from unittest.mock import MagicMock
        # We test the registration logic, not the MCP server itself.
        # Use a list to collect registered tool names.
        registered: list[str] = []

        def fake_tool(name: str):
            def decorator(fn):
                registered.append(name)
                return fn
            return decorator

        register_module_tools(
            tool_registrar=fake_tool,
            module_configs={"ha": {}},
        )
        assert "ha_list_entities" in registered
        assert "ha_get_state" in registered
        assert "ha_call_service" in registered

    def test_registers_obsidian_read_only(self) -> None:
        registered: list[str] = []

        def fake_tool(name: str):
            def decorator(fn):
                registered.append(name)
                return fn
            return decorator

        register_module_tools(
            tool_registrar=fake_tool,
            module_configs={"obsidian": {"read": True, "write": False}},
        )
        assert "obsidian_search" in registered
        assert "obsidian_read" in registered
        assert "obsidian_write" not in registered
        assert "obsidian_append" not in registered

    def test_skips_unknown_module(self) -> None:
        registered: list[str] = []

        def fake_tool(name: str):
            def decorator(fn):
                registered.append(name)
                return fn
            return decorator

        register_module_tools(
            tool_registrar=fake_tool,
            module_configs={"nonexistent_module": {}},
        )
        assert registered == []

    def test_skips_module_missing_env(self) -> None:
        """Module with missing env vars should be skipped, not crash."""
        registered: list[str] = []

        def fake_tool(name: str):
            def decorator(fn):
                registered.append(name)
                return fn
            return decorator

        # HA requires HA_URL and HA_TOKEN — if not set, configure() raises
        # The bridge should catch and skip gracefully
        register_module_tools(
            tool_registrar=fake_tool,
            module_configs={"ha": {}},
            skip_configure_errors=True,
        )
        # May or may not register depending on env — we just verify no crash
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_mcp_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'corvus.cli.mcp_bridge'`

**Step 3: Implement `corvus/cli/mcp_bridge.py`**

```python
"""Corvus MCP Bridge Server — exposes agent tools over stdio MCP protocol.

Launched as a subprocess by the claude CLI via the generated MCP config.
Wraps existing corvus.tools.* functions and memory toolkit as MCP tools.

Usage:
    uv run python -m corvus.cli.mcp_bridge \
        --agent homelab \
        --modules-json '{"ha": {}, "obsidian": {"read": true}}' \
        --memory-domain homelab
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("corvus-mcp-bridge")

# Module name -> (configure_fn, create_tools_fn) mapping.
# Lazily populated to avoid importing all tools at module level when
# only a subset is needed.
_MODULE_REGISTRY: dict[str, tuple[Callable, Callable]] = {}


def _populate_module_registry() -> None:
    """Populate the module registry with available tool modules.

    Each entry maps module_name -> (configure_fn, create_tools_fn).
    The create_tools_fn takes the module config dict and returns a list
    of (tool_name, callable) tuples.
    """
    if _MODULE_REGISTRY:
        return  # Already populated

    # -- Obsidian --
    def _obs_configure(cfg: dict) -> None:
        from corvus.tools.obsidian import ObsidianClient, configure
        configure(
            base_url=os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124"),
            api_key=os.environ.get("OBSIDIAN_API_KEY", ""),
            allowed_prefixes=cfg.get("allowed_prefixes"),
        )

    def _obs_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.obsidian import ObsidianClient
        client = ObsidianClient(
            base_url=os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124"),
            api_key=os.environ.get("OBSIDIAN_API_KEY", ""),
            allowed_prefixes=cfg.get("allowed_prefixes"),
        )
        tools: list[tuple[str, Callable]] = []
        if cfg.get("read", True):
            tools.append(("obsidian_search", client.obsidian_search))
            tools.append(("obsidian_read", client.obsidian_read))
        if cfg.get("write", False):
            tools.append(("obsidian_write", client.obsidian_write))
            tools.append(("obsidian_append", client.obsidian_append))
        return tools

    _MODULE_REGISTRY["obsidian"] = (_obs_configure, _obs_tools)

    # -- Home Assistant --
    def _ha_configure(cfg: dict) -> None:
        from corvus.tools.ha import configure
        configure(
            ha_url=os.environ.get("HA_URL", ""),
            ha_token=os.environ.get("HA_TOKEN", ""),
        )

    def _ha_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.ha import ha_call_service, ha_get_state, ha_list_entities
        return [
            ("ha_list_entities", ha_list_entities),
            ("ha_get_state", ha_get_state),
            ("ha_call_service", ha_call_service),
        ]

    _MODULE_REGISTRY["ha"] = (_ha_configure, _ha_tools)

    # -- Paperless --
    def _paperless_configure(cfg: dict) -> None:
        from corvus.tools.paperless import configure
        configure(
            paperless_url=os.environ.get("PAPERLESS_URL", ""),
            paperless_token=os.environ.get("PAPERLESS_API_TOKEN", ""),
        )

    def _paperless_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.paperless import (
            paperless_bulk_edit, paperless_read, paperless_search,
            paperless_tag, paperless_tags,
        )
        return [
            ("paperless_search", paperless_search),
            ("paperless_read", paperless_read),
            ("paperless_tags", paperless_tags),
            ("paperless_tag", paperless_tag),
            ("paperless_bulk_edit", paperless_bulk_edit),
        ]

    _MODULE_REGISTRY["paperless"] = (_paperless_configure, _paperless_tools)

    # -- Firefly --
    def _firefly_configure(cfg: dict) -> None:
        from corvus.tools.firefly import configure
        configure(
            firefly_url=os.environ.get("FIREFLY_URL", ""),
            firefly_token=os.environ.get("FIREFLY_API_TOKEN", ""),
        )

    def _firefly_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.firefly import (
            firefly_accounts, firefly_categories,
            firefly_create_transaction, firefly_summary, firefly_transactions,
        )
        return [
            ("firefly_transactions", firefly_transactions),
            ("firefly_accounts", firefly_accounts),
            ("firefly_categories", firefly_categories),
            ("firefly_summary", firefly_summary),
            ("firefly_create_transaction", firefly_create_transaction),
        ]

    _MODULE_REGISTRY["firefly"] = (_firefly_configure, _firefly_tools)

    # -- Email --
    def _email_configure(cfg: dict) -> None:
        from corvus.google_client import GoogleClient
        from corvus.tools.email import configure
        from corvus.yahoo_client import YahooClient
        google_client = None
        yahoo_client = None
        try:
            google_client = GoogleClient.from_env()
        except (OSError, ValueError):
            pass
        try:
            yahoo_client = YahooClient.from_env()
        except (OSError, ValueError):
            pass
        configure(google_client=google_client, yahoo_client=yahoo_client)

    def _email_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.email import (
            email_archive, email_draft, email_label,
            email_labels, email_list, email_read, email_send,
        )
        read_only = cfg.get("read_only", False)
        if read_only:
            return [("email_list", email_list), ("email_read", email_read)]
        return [
            ("email_list", email_list),
            ("email_read", email_read),
            ("email_draft", email_draft),
            ("email_send", email_send),
            ("email_archive", email_archive),
            ("email_label", email_label),
            ("email_labels", email_labels),
        ]

    _MODULE_REGISTRY["email"] = (_email_configure, _email_tools)

    # -- Drive --
    def _drive_configure(cfg: dict) -> None:
        from corvus.google_client import GoogleClient
        from corvus.tools.drive import configure
        try:
            client = GoogleClient.from_env()
            configure(client=client)
        except (OSError, ValueError):
            pass

    def _drive_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.drive import (
            drive_cleanup, drive_create, drive_delete, drive_edit,
            drive_list, drive_move, drive_permanent_delete, drive_read, drive_share,
        )
        read_only = cfg.get("read_only", False)
        if read_only:
            return [("drive_list", drive_list), ("drive_read", drive_read)]
        return [
            ("drive_list", drive_list),
            ("drive_read", drive_read),
            ("drive_create", drive_create),
            ("drive_edit", drive_edit),
            ("drive_move", drive_move),
            ("drive_delete", drive_delete),
            ("drive_permanent_delete", drive_permanent_delete),
            ("drive_share", drive_share),
            ("drive_cleanup", drive_cleanup),
        ]

    _MODULE_REGISTRY["drive"] = (_drive_configure, _drive_tools)


def register_module_tools(
    *,
    tool_registrar: Callable,
    module_configs: dict[str, dict],
    skip_configure_errors: bool = False,
) -> list[str]:
    """Configure and register tool module functions.

    Args:
        tool_registrar: Callable that takes (name) and returns a decorator.
            Typically mcp_server.tool or a test fake.
        module_configs: Dict of module_name -> module config from agent spec.
        skip_configure_errors: If True, skip modules that fail to configure.

    Returns:
        List of registered tool names.
    """
    _populate_module_registry()
    registered: list[str] = []

    for module_name, module_cfg in module_configs.items():
        entry = _MODULE_REGISTRY.get(module_name)
        if entry is None:
            logger.warning("Unknown module '%s' — skipping", module_name)
            continue

        configure_fn, create_tools_fn = entry
        try:
            configure_fn(module_cfg)
        except Exception as exc:
            if skip_configure_errors:
                logger.warning("Module '%s' configure failed: %s — skipping", module_name, exc)
                continue
            raise

        tools = create_tools_fn(module_cfg)
        for tool_name, tool_fn in tools:
            tool_registrar(name=tool_name)(tool_fn)
            registered.append(tool_name)

    return registered


def register_memory_tools(
    *,
    tool_registrar: Callable,
    agent_name: str,
    memory_domain: str,
) -> list[str]:
    """Register memory toolkit tools on the MCP server.

    Args:
        tool_registrar: Callable that takes (name) and returns a decorator.
        agent_name: Agent name for memory domain scoping.
        memory_domain: Agent's own_domain for memory operations.

    Returns:
        List of registered tool names.
    """
    from corvus.memory import MemoryConfig, MemoryHub
    from corvus.memory.toolkit import create_memory_toolkit

    config = MemoryConfig.from_file(
        path="config/memory.yaml",
        default_db_path=None,
    )
    hub = MemoryHub(config)

    memory_tools = create_memory_toolkit(hub, agent_name=agent_name, own_domain=memory_domain)
    registered: list[str] = []

    for mem_tool in memory_tools:
        # Wrap async memory tool functions for MCP
        tool_registrar(name=mem_tool.name, description=mem_tool.description)(mem_tool.fn)
        registered.append(mem_tool.name)

    return registered


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="corvus-mcp-bridge")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--modules-json", default="{}", help="JSON dict of module configs")
    parser.add_argument("--memory-domain", default="shared", help="Memory domain")
    return parser.parse_args(argv)


def main() -> None:
    """Entry point for the MCP bridge server."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()
    module_configs: dict[str, dict] = json.loads(args.modules_json)

    mcp = FastMCP(f"corvus-tools-{args.agent}")

    # Register domain tool modules
    registered = register_module_tools(
        tool_registrar=mcp.tool,
        module_configs=module_configs,
        skip_configure_errors=True,
    )
    logger.info("Registered %d module tools for %s", len(registered), args.agent)

    # Register memory tools
    try:
        mem_registered = register_memory_tools(
            tool_registrar=mcp.tool,
            agent_name=args.agent,
            memory_domain=args.memory_domain,
        )
        logger.info("Registered %d memory tools", len(mem_registered))
    except Exception as exc:
        logger.warning("Memory toolkit init failed: %s — memory tools unavailable", exc)

    mcp.run()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_mcp_bridge.py -v`
Expected: All 4 PASS

**Step 5: Commit**

```bash
git add corvus/cli/mcp_bridge.py tests/unit/test_mcp_bridge.py
git commit -m "feat: MCP bridge server for CLI agent tools

Stdio MCP server (FastMCP) that wraps existing corvus.tools.*
functions and memory toolkit. Launched as a subprocess by the
claude CLI via the generated MCP config. Each module is lazily
imported and configured from env vars."
```

---

### Task 4: Wire MCP config into `corvus/cli/chat.py`

**Files:**
- Modify: `corvus/cli/chat.py:185-210,330-340`
- Test: `tests/unit/test_chat_mcp_wiring.py`

**Step 1: Write the failing test**

Create `tests/unit/test_chat_mcp_wiring.py`:

```python
"""Tests for MCP config wiring in corvus chat CLI."""

import json
from pathlib import Path
from unittest.mock import patch

from corvus.cli.chat import _build_claude_cmd, parse_args


class _FakeSpec:
    def __init__(self, mcp_servers=None):
        self.metadata = {"shared_skills": ["memory"]}

        class _Tools:
            builtin = ["Bash", "Read"]
            modules = {"ha": {}}
            confirm_gated = []

        self.tools = _Tools()
        self.tools.mcp_servers = mcp_servers or []

        class _Memory:
            own_domain = "homelab"

        self.memory = _Memory()


class _FakeAgentsHub:
    def __init__(self, mcp_servers=None):
        self._spec = _FakeSpec(mcp_servers=mcp_servers)

    def build_system_prompt(self, name):
        return f"You are {name}."

    def get_agent(self, name):
        return self._spec


class _FakeModelRouter:
    def get_model(self, name):
        return "sonnet"

    def get_backend(self, name):
        return "claude"


class _FakeRuntime:
    def __init__(self, mcp_servers=None):
        self.agents_hub = _FakeAgentsHub(mcp_servers=mcp_servers)
        self.model_router = _FakeModelRouter()


def test_mcp_config_flag_in_cmd():
    """claude command should include --mcp-config when MCP config exists."""
    runtime = _FakeRuntime()
    args = parse_args(["--agent", "homelab"])
    cmd = _build_claude_cmd("/usr/bin/claude", runtime, "homelab", args)
    assert "--mcp-config" in cmd
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_chat_mcp_wiring.py -v`
Expected: FAIL — `--mcp-config` not in cmd (not yet wired)

**Step 3: Wire MCP config generation into chat.py**

Add to `corvus/cli/chat.py` — new function `_build_agent_mcp_config`:

```python
def _build_agent_mcp_config(
    agent_name: str,
    runtime: object,
    isolated_home: Path,
) -> Path | None:
    """Generate MCP config for the agent's allowed tools.

    Returns the config file path, or None if generation fails.
    """
    from corvus.capabilities.registry import CapabilitiesRegistry
    from corvus.cli.mcp_config import build_mcp_config
    from corvus.credential_store import SERVICE_ENV_MAP

    spec = runtime.agents_hub.get_agent(agent_name)
    if spec is None:
        return None

    # Determine which modules this agent requests
    module_configs: dict[str, dict] = {}
    requires_env_by_module: dict[str, list[str]] = {}
    if hasattr(spec.tools, "modules") and spec.tools.modules:
        module_configs = dict(spec.tools.modules)

    # Build requires_env mapping from the capabilities registry
    caps = runtime.capabilities_registry
    for module_name in module_configs:
        entry = caps.get_module(module_name)
        if entry is not None:
            requires_env_by_module[module_name] = list(entry.requires_env)

    # External MCP servers from agent spec
    external_servers = getattr(spec.tools, "mcp_servers", []) or []

    # Memory domain
    memory_domain = spec.memory.own_domain if spec.memory else "shared"

    try:
        return build_mcp_config(
            agent_name=agent_name,
            module_configs=module_configs,
            requires_env_by_module=requires_env_by_module,
            external_mcp_servers=external_servers,
            output_dir=isolated_home,
            memory_domain=memory_domain,
        )
    except Exception as exc:
        logger.warning("MCP config generation failed: %s — tools unavailable in CLI", exc)
        return None
```

Modify `_build_claude_cmd` to accept and use the MCP config path. Add a parameter `mcp_config_path: Path | None = None` and append the flag:

```python
    # MCP config (domain tools + external servers)
    if mcp_config_path is not None:
        cmd.extend(["--mcp-config", str(mcp_config_path)])
```

Modify `main()` to call `_build_agent_mcp_config` after `_prepare_isolated_env` and pass the result to `_build_claude_cmd`:

```python
    env = _prepare_isolated_env(agent_name, runtime)
    mcp_config_path = _build_agent_mcp_config(
        agent_name, runtime, Path(env["HOME"])
    )
    cmd = _build_claude_cmd(claude_bin, runtime, agent_name, args, mcp_config_path=mcp_config_path)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_chat_mcp_wiring.py -v`
Expected: All PASS

**Step 5: Run existing chat tests**

Run: `uv run pytest tests/unit/test_chat_integration_smoke.py tests/unit/test_chat_cli_isolation.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add corvus/cli/chat.py tests/unit/test_chat_mcp_wiring.py
git commit -m "feat: wire MCP config into corvus chat CLI

corvus chat now generates a per-agent MCP config at launch,
giving agents access to their domain tools (Obsidian, HA,
Paperless, email, finance) and memory via the MCP bridge server.
External MCP servers from agent.yaml are also included."
```

---

### Task 5: Integration smoke test

**Files:**
- Modify: `tests/unit/test_chat_integration_smoke.py`

**Step 1: Write the smoke test**

Add to `tests/unit/test_chat_integration_smoke.py`:

```python
import json
from pathlib import Path


def test_mcp_config_generated_for_agent(tmp_path: Path) -> None:
    """Verify MCP config is generated with correct shape for a real agent."""
    from corvus.cli.mcp_config import build_mcp_config

    config_path = build_mcp_config(
        agent_name="homelab",
        module_configs={"ha": {}, "obsidian": {"read": True, "write": False}},
        requires_env_by_module={
            "ha": ["HA_URL", "HA_TOKEN"],
            "obsidian": ["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
        },
        external_mcp_servers=[],
        output_dir=tmp_path,
        memory_domain="homelab",
    )
    data = json.loads(config_path.read_text())

    # Bridge server entry exists
    assert "corvus-tools" in data["mcpServers"]
    bridge = data["mcpServers"]["corvus-tools"]
    assert bridge["command"] == "uv"
    assert "--agent" in bridge["args"]
    assert "homelab" in bridge["args"]

    # Modules JSON is in the args
    modules_idx = bridge["args"].index("--modules-json") + 1
    modules = json.loads(bridge["args"][modules_idx])
    assert "ha" in modules
    assert "obsidian" in modules
    assert modules["obsidian"]["read"] is True

    # Memory domain is in the args
    domain_idx = bridge["args"].index("--memory-domain") + 1
    assert bridge["args"][domain_idx] == "homelab"


def test_bridge_parse_args() -> None:
    """Verify bridge server CLI arg parsing."""
    from corvus.cli.mcp_bridge import parse_args

    args = parse_args(["--agent", "finance", "--modules-json", '{"firefly": {}}', "--memory-domain", "finance"])
    assert args.agent == "finance"
    assert args.memory_domain == "finance"
    modules = json.loads(args.modules_json)
    assert "firefly" in modules
```

**Step 2: Run the smoke tests**

Run: `uv run pytest tests/unit/test_chat_integration_smoke.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_chat_integration_smoke.py
git commit -m "test: add MCP config + bridge smoke tests"
```

---

### Task 6: Full test suite verification

**Step 1: Run lint**

Run: `uv run ruff check corvus/cli/mcp_bridge.py corvus/cli/mcp_config.py corvus/agents/spec.py`
Expected: No errors

**Step 2: Run format check**

Run: `uv run ruff format --check corvus/cli/mcp_bridge.py corvus/cli/mcp_config.py`
Expected: No changes needed (or fix and re-commit)

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -m "not live" --timeout=120 -q --tb=short`
Expected: All pass (same 2 pre-existing Docker failures)

**Step 4: Manual smoke test**

Run: `uv run python -m corvus.cli.chat --agent general --verbose`
Expected: Output shows `--mcp-config` in the command, bridge server path visible

**Step 5: Final commit if any fixes needed**

```bash
git add -u
git commit -m "fix: lint/format cleanup for MCP bridge"
```

---

Plan complete and saved to `docs/plans/2026-03-07-cli-mcp-tools-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?