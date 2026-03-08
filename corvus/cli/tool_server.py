"""Corvus Tool Server — Unix socket server for agent tool calls.

Listens on a Unix domain socket, validates agent-scoped JWTs, and
dispatches to existing corvus.tools.* functions. Credentials never
leave this process — the agent subprocess only sees the socket path
and a scoped bearer token.

Lifecycle:
    1. Created by chat.py before launching claude subprocess
    2. Listens on {agent_workspace}/.corvus.sock
    3. Stopped after claude subprocess exits
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from corvus.cli.tool_token import validate_token

logger = logging.getLogger("corvus-tool-server")

# Module name → tool_name → callable mapping.
# Populated lazily via _populate_tool_registry().
_TOOL_REGISTRY: dict[str, dict[str, Any]] = {}

# Known module prefixes for tool name → module extraction.
# Ordered longest-first so "paperless" matches before a hypothetical "paper".
_MODULE_PREFIXES = [
    "paperless",
    "obsidian",
    "firefly",
    "memory",
    "email",
    "drive",
    "ha",
]


def _populate_tool_registry(module_configs: dict[str, dict]) -> None:
    """Populate the tool registry from module configs.

    Reuses the same module registration pattern as mcp_bridge.py.
    Only configures and loads tools for modules in module_configs.
    """
    if _TOOL_REGISTRY:
        return

    from corvus.cli.mcp_bridge import _MODULE_REGISTRY, _populate_module_registry

    _populate_module_registry()

    for module_name, module_cfg in module_configs.items():
        entry = _MODULE_REGISTRY.get(module_name)
        if entry is None:
            logger.warning("Unknown module '%s' — skipping", module_name)
            continue

        configure_fn, create_tools_fn = entry
        try:
            configure_fn(module_cfg)
        except Exception as exc:
            logger.warning("Module '%s' configure failed: %s — skipping", module_name, exc)
            continue

        tools = create_tools_fn(module_cfg)
        _TOOL_REGISTRY[module_name] = {}
        for tool_name, tool_fn in tools:
            _TOOL_REGISTRY[module_name][tool_name] = tool_fn


def _register_memory_tools(agent_name: str, memory_domain: str) -> None:
    """Register memory tools into the tool registry."""
    from corvus.config import MEMORY_CONFIG, MEMORY_DB
    from corvus.memory import MemoryConfig, MemoryHub
    from corvus.memory.toolkit import create_memory_toolkit

    config = MemoryConfig.from_file(MEMORY_CONFIG, default_db_path=MEMORY_DB)
    hub = MemoryHub(config)

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
    _TOOL_REGISTRY["memory"] = {}
    for mem_tool in memory_tools:
        _TOOL_REGISTRY["memory"][mem_tool.name] = mem_tool.fn


class ToolServer:
    """Unix socket tool server with JWT authentication.

    Args:
        secret: HMAC secret for JWT validation.
        socket_path: Path for the Unix domain socket.
        module_configs: Dict of module_name -> config for tool registration.
        agent_name: Agent name for memory tool scoping.
        memory_domain: Memory domain for memory tools.
    """

    def __init__(
        self,
        *,
        secret: bytes,
        socket_path: str,
        module_configs: dict[str, dict],
        agent_name: str = "",
        memory_domain: str = "shared",
    ) -> None:
        self._secret = secret
        self._socket_path = socket_path
        self._module_configs = module_configs
        self._agent_name = agent_name
        self._memory_domain = memory_domain
        self._server: asyncio.AbstractServer | None = None

    def _extract_module(self, tool_name: str) -> str:
        """Extract module name from a tool name like 'obsidian_search' → 'obsidian'."""
        for prefix in _MODULE_PREFIXES:
            if tool_name.startswith(prefix + "_") or tool_name == prefix:
                return prefix
        # Fallback: first segment before underscore
        return tool_name.split("_")[0]

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=30)
            if not data:
                return

            try:
                request = json.loads(data.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                response = {"ok": False, "error": "malformed_request"}
                writer.write(json.dumps(response).encode())
                await writer.drain()
                return

            response = await self._dispatch(request)
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except asyncio.TimeoutError:
            response = {"ok": False, "error": "timeout"}
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as exc:
            logger.exception("Connection handler error: %s", exc)
            response = {"ok": False, "error": "internal_error"}
            try:
                writer.write(json.dumps(response).encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, request: dict) -> dict:
        """Validate auth and dispatch a tool call."""
        # 1. Validate token
        token = request.get("token")
        if not token:
            return {"ok": False, "error": "missing_token"}

        try:
            payload = validate_token(secret=self._secret, token=token)
        except ValueError as exc:
            return {"ok": False, "error": f"auth_failed: {exc}"}

        # 2. Extract tool info
        tool_name = request.get("tool", "")
        params = request.get("params", {})
        module = self._extract_module(tool_name)

        # 3. Check module authorization
        allowed_modules = payload.get("modules", [])
        if module not in allowed_modules:
            return {"ok": False, "error": "not_authorized"}

        # 4. Look up and call tool
        module_tools = _TOOL_REGISTRY.get(module)
        if module_tools is None:
            return {"ok": False, "error": f"unknown_module: {module}"}

        tool_fn = module_tools.get(tool_name)
        if tool_fn is None:
            return {"ok": False, "error": f"unknown_tool: {tool_name}"}

        try:
            # Some tools are async (memory), some are sync (obsidian, ha, etc.)
            if asyncio.iscoroutinefunction(tool_fn):
                result = await tool_fn(**params)
            else:
                result = tool_fn(**params)
            return {"ok": True, "result": result}
        except Exception as exc:
            logger.exception("Tool call failed: %s(%s)", tool_name, params)
            return {"ok": False, "error": f"tool_error: {exc}"}

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        # Clean up stale socket
        sock_path = Path(self._socket_path)
        if sock_path.exists():
            sock_path.unlink()

        # Register tools (only for modules in config)
        _populate_tool_registry(self._module_configs)
        if self._agent_name:
            _register_memory_tools(self._agent_name, self._memory_domain)

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
        )
        # Set restrictive permissions on the socket file
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError:
            pass  # macOS may not honor chmod on sockets

        logger.info("Tool server listening on %s", self._socket_path)

    async def stop(self) -> None:
        """Stop the server and clean up the socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        sock_path = Path(self._socket_path)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        logger.info("Tool server stopped, socket removed")
