"""Tool module registration — wires existing corvus.tools.* modules into ToolModuleEntry defs.

Each tool module gets a factory function that returns a ToolModuleEntry. The factory
is called at module level to populate TOOL_MODULE_DEFS.

configure() reads credentials from env vars (not from cfg) — the YAML cfg provides
per-agent preferences (allowed_prefixes, read_only), while env vars hold secrets.

create_mcp_server() returns real SDK MCP server objects via create_sdk_mcp_server(),
not plain dicts. These are directly usable by ClaudeAgentOptions.mcp_servers.

IMPORTANT: The ``memory`` module referenced in agent YAMLs is handled directly by
AgentsHub (not via CapabilitiesRegistry). It is intentionally absent from
TOOL_MODULE_DEFS.
"""

import logging
import os
from collections.abc import Callable
from typing import Any, TypedDict, cast

from claude_agent_sdk import create_sdk_mcp_server

from corvus.capabilities.registry import ToolModuleEntry
from corvus.google_client import GoogleClient
from corvus.tools.drive import (
    configure as drive_configure,
)
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
from corvus.tools.email import (
    configure as email_configure,
)
from corvus.tools.email import (
    email_archive,
    email_draft,
    email_label,
    email_labels,
    email_list,
    email_read,
    email_send,
)
from corvus.tools.firefly import (
    configure as firefly_configure,
)
from corvus.tools.firefly import (
    firefly_accounts,
    firefly_categories,
    firefly_create_transaction,
    firefly_summary,
    firefly_transactions,
)
from corvus.tools.ha import (
    configure as ha_configure,
)
from corvus.tools.ha import (
    ha_call_service,
    ha_get_state,
    ha_list_entities,
)
from corvus.tools.obsidian import (
    ObsidianClient,
)
from corvus.tools.obsidian import (
    configure as obs_configure,
)
from corvus.tools.paperless import (
    configure as paperless_configure,
)
from corvus.tools.paperless import (
    paperless_bulk_edit,
    paperless_read,
    paperless_search,
    paperless_tag,
    paperless_tags,
)
from corvus.yahoo_client import YahooClient

logger = logging.getLogger("corvus.capabilities.modules")


class ObsidianModuleConfig(TypedDict, total=False):
    """Config shape for the obsidian tool module."""

    allowed_prefixes: list[str] | None
    read: bool
    write: bool


class EmailModuleConfig(TypedDict, total=False):
    """Config shape for the email tool module."""

    read_only: bool


class DriveModuleConfig(TypedDict, total=False):
    """Config shape for the drive tool module."""

    read_only: bool


def _obsidian_entry() -> ToolModuleEntry:
    """Build the Obsidian vault tool module entry.

    Per-agent: creates an ObsidianClient with allowed_prefixes from agent YAML,
    and respects read/write flags to control which tools are exposed.
    """

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        obs_configure(
            base_url=os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124"),
            api_key=os.environ.get("OBSIDIAN_API_KEY", ""),
            allowed_prefixes=cfg.get("allowed_prefixes"),
        )
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        client = ObsidianClient(
            base_url=os.environ.get("OBSIDIAN_URL", "https://127.0.0.1:27124"),
            api_key=os.environ.get("OBSIDIAN_API_KEY", ""),
            allowed_prefixes=cfg.get("allowed_prefixes"),
        )
        tools: list[Callable] = []
        if cfg.get("read", True):
            tools.extend([client.obsidian_search, client.obsidian_read])
        if cfg.get("write", False):
            tools.extend([client.obsidian_write, client.obsidian_append])
        return tools

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="obsidian",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="obsidian",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["OBSIDIAN_URL", "OBSIDIAN_API_KEY"],
        supports_per_agent=True,
    )


def _email_entry() -> ToolModuleEntry:
    """Build the email (Gmail + Yahoo) tool module entry.

    Discovers Google and Yahoo clients from env vars at configure time.
    """

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        google_client = None
        yahoo_client = None
        try:
            google_client = GoogleClient.from_env()
            if not google_client.list_accounts():
                google_client = None
        except (OSError, ValueError) as exc:
            logger.warning("Google client init failed: %s", exc)
        try:
            yahoo_client = YahooClient.from_env()
            if not yahoo_client.list_accounts():
                yahoo_client = None
        except (OSError, ValueError) as exc:
            logger.warning("Yahoo client init failed: %s", exc)
        email_configure(google_client=google_client, yahoo_client=yahoo_client)
        cfg["_google_client"] = google_client
        cfg["_yahoo_client"] = yahoo_client
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        has_google = cfg.get("_google_client") is not None
        read_only = cfg.get("read_only", False)

        if read_only or not has_google:
            return [email_list, email_read]

        return [
            email_list,
            email_read,
            email_draft,
            email_send,
            email_archive,
            email_label,
            email_labels,
        ]

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="email",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="email",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["GOOGLE_CREDS_PATH"],
    )


def _drive_entry() -> ToolModuleEntry:
    """Build the Google Drive/Docs tool module entry."""

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        google_client = None
        try:
            google_client = GoogleClient.from_env()
        except (OSError, ValueError) as exc:
            logger.warning("Google client init failed for drive: %s", exc)
        if google_client is not None:
            drive_configure(client=google_client)
        cfg["_google_client"] = google_client
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        read_only = cfg.get("read_only", False)
        if read_only:
            return [drive_list, drive_read]

        return [
            drive_list,
            drive_read,
            drive_create,
            drive_edit,
            drive_move,
            drive_delete,
            drive_permanent_delete,
            drive_share,
            drive_cleanup,
        ]

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="drive",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="drive",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["GOOGLE_CREDS_PATH"],
    )


def _ha_entry() -> ToolModuleEntry:
    """Build the Home Assistant tool module entry."""

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        ha_url = os.environ.get("HA_URL", "")
        ha_token = os.environ.get("HA_TOKEN", "")
        if not ha_url or not ha_token:
            raise ValueError("HA_URL and HA_TOKEN must be non-empty")
        ha_configure(ha_url=ha_url, ha_token=ha_token)
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        return [ha_list_entities, ha_get_state, ha_call_service]

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="ha",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="ha",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["HA_URL", "HA_TOKEN"],
    )


def _paperless_entry() -> ToolModuleEntry:
    """Build the Paperless-ngx tool module entry."""

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        url = os.environ.get("PAPERLESS_URL", "")
        token = os.environ.get("PAPERLESS_API_TOKEN", "")
        if not url or not token:
            raise ValueError("PAPERLESS_URL and PAPERLESS_API_TOKEN must be non-empty")
        paperless_configure(paperless_url=url, paperless_token=token)
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        return [
            paperless_search,
            paperless_read,
            paperless_tags,
            paperless_tag,
            paperless_bulk_edit,
        ]

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="paperless",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="paperless",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["PAPERLESS_URL", "PAPERLESS_API_TOKEN"],
    )


def _firefly_entry() -> ToolModuleEntry:
    """Build the Firefly III tool module entry."""

    def configure(cfg: dict[str, Any]) -> dict[str, Any]:
        url = os.environ.get("FIREFLY_URL", "")
        token = os.environ.get("FIREFLY_API_TOKEN", "")
        if not url or not token:
            raise ValueError("FIREFLY_URL and FIREFLY_API_TOKEN must be non-empty")
        firefly_configure(firefly_url=url, firefly_token=token)
        return cfg

    def create_tools(cfg: dict[str, Any]) -> list[Callable]:
        return [
            firefly_transactions,
            firefly_accounts,
            firefly_categories,
            firefly_summary,
            firefly_create_transaction,
        ]

    def create_mcp(tools: list[Callable], cfg: dict[str, Any]) -> Any:
        return create_sdk_mcp_server(
            name="firefly",
            version="1.0.0",
            tools=cast(list[Any], tools),
        )

    return ToolModuleEntry(
        name="firefly",
        configure=configure,
        create_tools=create_tools,
        create_mcp_server=create_mcp,
        requires_env=["FIREFLY_URL", "FIREFLY_API_TOKEN"],
    )


# ---------------------------------------------------------------------------
# Module names that are handled directly by AgentsHub (not via capabilities).
# These are skipped during resolve() to avoid misleading "unregistered" warnings.
# ---------------------------------------------------------------------------
HUB_MANAGED_MODULES: frozenset[str] = frozenset({"memory"})

# ---------------------------------------------------------------------------
# Module-level list of all tool module definitions.
# ---------------------------------------------------------------------------

TOOL_MODULE_DEFS: list[ToolModuleEntry] = [
    _obsidian_entry(),
    _email_entry(),
    _drive_entry(),
    _ha_entry(),
    _paperless_entry(),
    _firefly_entry(),
]
