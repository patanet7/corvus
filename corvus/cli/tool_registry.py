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
import json
import logging
import os
from collections.abc import Callable

logger = logging.getLogger("corvus-mcp-bridge")

# Module name -> (configure_fn, create_tools_fn) mapping.
# Populated lazily via _populate_module_registry().
_MODULE_REGISTRY: dict[str, tuple[Callable, Callable]] = {}


def _populate_module_registry() -> None:
    """Populate the module registry with available tool modules.

    Each entry maps module_name -> (configure_fn, create_tools_fn).
    The create_tools_fn takes the module config dict and returns a list
    of (tool_name, callable) tuples.
    """
    if _MODULE_REGISTRY:
        return

    # -- Obsidian --
    def _obs_configure(cfg: dict) -> None:
        from corvus.tools.obsidian import configure

        configure(
            base_url=os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124"),
            api_key=os.environ.get("OBSIDIAN_API_KEY", ""),
            allowed_prefixes=cfg.get("allowed_prefixes"),
        )

    def _obs_tools(cfg: dict) -> list[tuple[str, Callable]]:
        from corvus.tools.obsidian import (
            obsidian_append,
            obsidian_read,
            obsidian_search,
            obsidian_write,
        )

        tools: list[tuple[str, Callable]] = []
        if cfg.get("read", True):
            tools.append(("obsidian_search", obsidian_search))
            tools.append(("obsidian_read", obsidian_read))
        if cfg.get("write", False):
            tools.append(("obsidian_write", obsidian_write))
            tools.append(("obsidian_append", obsidian_append))
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
            paperless_bulk_edit,
            paperless_read,
            paperless_search,
            paperless_tag,
            paperless_tags,
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
            firefly_accounts,
            firefly_categories,
            firefly_create_transaction,
            firefly_summary,
            firefly_transactions,
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
            email_archive,
            email_draft,
            email_label,
            email_labels,
            email_list,
            email_read,
            email_send,
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
            drive_cleanup,
            drive_create,
            drive_delete,
            drive_edit,
            drive_list,
            drive_move,
            drive_permanent_delete,
            drive_read,
            drive_share,
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
        tool_registrar: Callable that takes (name, description) and returns a decorator.
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
        tool_registrar: Callable that takes (name, description) and returns a decorator.
        agent_name: Agent name for memory domain scoping.
        memory_domain: Agent's own_domain for memory operations.

    Returns:
        List of registered tool names.
    """
    from typing import Any

    from corvus.config import MEMORY_CONFIG, MEMORY_DB
    from corvus.memory import MemoryConfig, MemoryHub
    from corvus.memory.toolkit import create_memory_toolkit

    config = MemoryConfig.from_file(MEMORY_CONFIG, default_db_path=MEMORY_DB)
    hub = MemoryHub(config)

    # The bridge runs outside the full gateway runtime, so we provide a
    # simple resolver that grants the agent write access to its own domain.
    # The agent's permissions were already validated when the MCP config
    # was generated — only agents with the module enabled reach here.
    def _bridge_memory_access(name: str) -> dict[str, Any]:
        return {
            "own_domain": memory_domain,
            "can_read_shared": True,
            "can_write": True,
            "readable_domains": None,
        }

    def _bridge_readable_domains(name: str) -> list[str]:
        return [memory_domain, "shared"]

    hub.set_resolvers(_bridge_memory_access, _bridge_readable_domains)

    memory_tools = create_memory_toolkit(hub, agent_name=agent_name, own_domain=memory_domain)
    registered: list[str] = []

    for mem_tool in memory_tools:
        tool_registrar(name=mem_tool.name, description=mem_tool.description)(mem_tool.fn)
        registered.append(mem_tool.name)

    return registered


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the MCP bridge server."""
    parser = argparse.ArgumentParser(prog="corvus-mcp-bridge")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--modules-json", default="{}", help="JSON dict of module configs")
    parser.add_argument("--memory-domain", default="shared", help="Memory domain")
    return parser.parse_args(argv)


def main() -> None:
    """Entry point for the MCP bridge server."""
    from mcp.server.fastmcp import FastMCP

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
