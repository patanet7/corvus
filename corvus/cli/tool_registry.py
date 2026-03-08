"""Corvus tool module registry.

Maps module names to (configure_fn, create_tools_fn) pairs. Each module
knows how to configure itself from env vars and produce a list of
(tool_name, callable) tuples.

Extracted from the former MCP bridge to be shared by the tool server.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

logger = logging.getLogger("corvus-tool-registry")

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
