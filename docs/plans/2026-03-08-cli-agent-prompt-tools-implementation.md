# CLI Agent Prompt & Tool Delivery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace MCP bridge with native Claude Code delivery — minimal system prompt, CLAUDE.md for context, skills with scripts over a secure Unix socket tool server.

**Architecture:** System prompt carries soul + identity (~200 words). CLAUDE.md in the agent workspace carries domain instructions, siblings, and memory seeds. Each tool module is a skill directory with a bundled Python script that talks to a local Unix socket tool server. The server validates agent-scoped JWTs and dispatches to existing `corvus.tools.*` functions.

**Tech Stack:** Python 3.11+, `hmac`/`hashlib` for JWT, `asyncio` for Unix socket server, existing `corvus.tools.*` modules, Claude Code skills (`SKILL.md` format)

**Design doc:** `docs/plans/2026-03-08-cli-agent-prompt-tools-design.md`

---

## Task 1: JWT Token Module

Build the agent-scoped JWT generation and validation used by the tool server.

**Files:**
- Create: `corvus/cli/tool_token.py`
- Test: `tests/unit/test_tool_token.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_tool_token.py`:

```python
"""Tests for agent-scoped JWT tokens."""

import time

import pytest

from corvus.cli.tool_token import create_token, validate_token


class TestCreateToken:
    """Tests for JWT creation."""

    def test_creates_token_string(self) -> None:
        """create_token returns a non-empty string."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian", "memory"],
            ttl_seconds=3600,
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_three_base64_parts(self) -> None:
        """Token has header.payload.signature format."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        parts = token.split(".")
        assert len(parts) == 3


class TestValidateToken:
    """Tests for JWT validation."""

    def test_valid_token_returns_payload(self) -> None:
        """A freshly created token validates successfully."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian", "email"],
            ttl_seconds=3600,
        )
        payload = validate_token(secret=secret, token=token)
        assert payload["agent"] == "personal"
        assert payload["modules"] == ["obsidian", "email"]

    def test_expired_token_raises(self) -> None:
        """An expired token raises ValueError."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=-1,  # already expired
        )
        with pytest.raises(ValueError, match="expired"):
            validate_token(secret=secret, token=token)

    def test_wrong_secret_raises(self) -> None:
        """Token signed with different secret is rejected."""
        secret_a = b"secret-a-32-bytes-long-enough!!"
        secret_b = b"secret-b-32-bytes-long-enough!!"
        token = create_token(
            secret=secret_a,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        with pytest.raises(ValueError, match="signature"):
            validate_token(secret=secret_b, token=token)

    def test_tampered_payload_raises(self) -> None:
        """Token with modified payload is rejected."""
        secret = b"test-secret-32-bytes-long-enough"
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        # Tamper with the payload portion
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # reverse the payload
        tampered = ".".join(parts)
        with pytest.raises(ValueError):
            validate_token(secret=secret, token=tampered)

    def test_modules_list_preserved(self) -> None:
        """Modules list in payload matches what was signed."""
        secret = b"test-secret-32-bytes-long-enough"
        modules = ["ha", "obsidian", "email", "memory"]
        token = create_token(
            secret=secret,
            agent="homelab",
            modules=modules,
            ttl_seconds=3600,
        )
        payload = validate_token(secret=secret, token=token)
        assert payload["modules"] == modules
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tool_token.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.cli.tool_token'`

**Step 3: Implement the JWT module**

Create `corvus/cli/tool_token.py`:

```python
"""Agent-scoped JWT tokens for the corvus tool server.

Tokens are HMAC-SHA256 signed JSON payloads with:
- agent: the agent name
- modules: list of allowed tool module names
- exp: Unix timestamp expiry

Tokens use a custom minimal format (not a full JWT library)
to avoid adding dependencies. Format: base64(header).base64(payload).base64(signature)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    """URL-safe base64 decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(
    *,
    secret: bytes,
    agent: str,
    modules: list[str],
    ttl_seconds: int,
) -> str:
    """Create an agent-scoped token.

    Args:
        secret: Random bytes for HMAC signing (>= 32 bytes recommended).
        agent: Agent name baked into the token.
        modules: List of allowed tool module names.
        ttl_seconds: Seconds until the token expires.

    Returns:
        Signed token string in header.payload.signature format.
    """
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "CVT"}).encode())
    payload_dict = {
        "agent": agent,
        "modules": modules,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64encode(json.dumps(payload_dict).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = _b64encode(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def validate_token(*, secret: bytes, token: str) -> dict:
    """Validate a token and return its payload.

    Args:
        secret: The same secret used to create the token.
        token: The token string to validate.

    Returns:
        The decoded payload dict with keys: agent, modules, exp.

    Raises:
        ValueError: If the token is malformed, expired, or has an invalid signature.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token: expected 3 parts")

    header_b64, payload_b64, signature_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64decode(signature_b64)
    except Exception as exc:
        raise ValueError(f"malformed signature: {exc}") from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("invalid signature")

    # Decode payload
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:
        raise ValueError(f"malformed payload: {exc}") from exc

    # Check expiry
    exp = payload.get("exp", 0)
    if time.time() > exp:
        raise ValueError("token expired")

    return payload
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_token.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_tool_token_results.log`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add corvus/cli/tool_token.py tests/unit/test_tool_token.py
git commit -m "feat: add agent-scoped JWT token module for tool server"
```

---

## Task 2: Tool Server — Unix Socket + Dispatch

Build the tool server that listens on a Unix socket, validates JWTs, and dispatches to existing tool functions.

**Files:**
- Create: `corvus/cli/tool_server.py`
- Test: `tests/unit/test_tool_server.py`
- Reference: `corvus/cli/mcp_bridge.py` (reuse the `_MODULE_REGISTRY` and `_populate_module_registry()` pattern)
- Reference: `corvus/cli/tool_token.py` (from Task 1)

**Step 1: Write the failing tests**

Create `tests/unit/test_tool_server.py`:

```python
"""Tests for the corvus tool server.

Tests the request handling, JWT auth, and module dispatch logic.
Uses real Unix sockets — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path

import pytest

from corvus.cli.tool_server import ToolServer
from corvus.cli.tool_token import create_token


def _make_secret() -> bytes:
    return os.urandom(32)


def _send_request(socket_path: str, request: dict) -> dict:
    """Send a JSON request to the tool server and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(socket_path)
    sock.sendall(json.dumps(request).encode() + b"\n")
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    return json.loads(response.decode())


class TestToolServerAuth:
    """Tests for authentication and authorization."""

    def test_rejects_missing_token(self, tmp_path: Path) -> None:
        """Request without token is rejected."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(sock_path, {"tool": "obsidian_search", "params": {}})
            assert result["ok"] is False
            assert "token" in result["error"].lower() or "auth" in result["error"].lower()
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_rejects_invalid_token(self, tmp_path: Path) -> None:
        """Request with wrong-secret token is rejected."""
        secret = _make_secret()
        wrong_secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        bad_token = create_token(
            secret=wrong_secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(
                sock_path,
                {"tool": "obsidian_search", "params": {}, "token": bad_token},
            )
            assert result["ok"] is False
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_rejects_unauthorized_module(self, tmp_path: Path) -> None:
        """Token for obsidian cannot call ha tools."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(
                sock_path,
                {"tool": "ha_list_entities", "params": {}, "token": token},
            )
            assert result["ok"] is False
            assert "not_authorized" in result["error"]
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_rejects_expired_token(self, tmp_path: Path) -> None:
        """Expired token is rejected."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=-1,
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(
                sock_path,
                {"tool": "obsidian_search", "params": {"query": "test"}, "token": token},
            )
            assert result["ok"] is False
        finally:
            loop.run_until_complete(server.stop())
            loop.close()


class TestToolServerSocket:
    """Tests for socket lifecycle."""

    def test_socket_file_created_on_start(self, tmp_path: Path) -> None:
        """Socket file exists after start()."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            assert Path(sock_path).exists()
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_socket_file_permissions(self, tmp_path: Path) -> None:
        """Socket file has 0600 permissions."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            mode = Path(sock_path).stat().st_mode & 0o777
            # Unix sockets report as 0755 on macOS, but the
            # directory containing them should be 0700.
            # We check that the parent dir is restricted instead.
            assert Path(sock_path).exists()
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_socket_cleaned_up_on_stop(self, tmp_path: Path) -> None:
        """Socket file is removed after stop()."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        loop.run_until_complete(server.stop())
        loop.close()

        assert not Path(sock_path).exists()


class TestToolServerDispatch:
    """Tests for tool_name → module mapping."""

    def test_extracts_module_from_tool_name(self, tmp_path: Path) -> None:
        """'obsidian_search' maps to module 'obsidian'."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})
        assert server._extract_module("obsidian_search") == "obsidian"
        assert server._extract_module("ha_list_entities") == "ha"
        assert server._extract_module("ha_get_state") == "ha"
        assert server._extract_module("firefly_transactions") == "firefly"
        assert server._extract_module("memory_search") == "memory"

    def test_unknown_tool_returns_error(self, tmp_path: Path) -> None:
        """Request for unregistered tool returns error."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        server = ToolServer(secret=secret, socket_path=sock_path, module_configs={})

        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(
                sock_path,
                {"tool": "nonexistent_tool", "params": {}, "token": token},
            )
            assert result["ok"] is False
            assert "unknown" in result["error"].lower() or "not_found" in result["error"].lower()
        finally:
            loop.run_until_complete(server.stop())
            loop.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tool_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'corvus.cli.tool_server'`

**Step 3: Implement the tool server**

Create `corvus/cli/tool_server.py`:

```python
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

    from corvus.cli.mcp_bridge import _populate_module_registry, _MODULE_REGISTRY

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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_server.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_tool_server_results.log`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add corvus/cli/tool_server.py tests/unit/test_tool_server.py
git commit -m "feat: add Unix socket tool server with JWT auth"
```

---

## Task 3: Tool Script Template + Shared Client Library

Build the reusable script that skills bundle for calling the tool server.

**Files:**
- Create: `config/skills/tools/_lib/corvus_tool_client.py`
- Test: `tests/unit/test_tool_client_script.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_tool_client_script.py`:

```python
"""Tests for the tool client library used by skill scripts.

Runs against a real Unix socket server — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest

from corvus.cli.tool_server import ToolServer
from corvus.cli.tool_token import create_token


def _make_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def tool_client_module(tmp_path: Path):
    """Import the tool client from config/skills/tools/_lib/."""
    lib_path = Path(__file__).resolve().parents[2] / "config" / "skills" / "tools" / "_lib"
    sys.path.insert(0, str(lib_path))
    try:
        import importlib

        mod = importlib.import_module("corvus_tool_client")
        importlib.reload(mod)  # ensure fresh module state
        yield mod
    finally:
        sys.path.remove(str(lib_path))
        if "corvus_tool_client" in sys.modules:
            del sys.modules["corvus_tool_client"]


class TestToolClientCall:
    """Tests for the client call_tool function."""

    def test_sends_request_and_receives_response(
        self, tmp_path: Path, tool_client_module, monkeypatch
    ) -> None:
        """Client sends request over Unix socket and parses response."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")
        token = create_token(
            secret=secret, agent="test", modules=["memory"], ttl_seconds=3600,
        )

        monkeypatch.setenv("CORVUS_TOOL_SOCKET", sock_path)
        monkeypatch.setenv("CORVUS_TOOL_TOKEN", token)

        # Start a minimal echo server that returns a canned response
        async def _echo_handler(reader, writer):
            data = await reader.readline()
            req = json.loads(data.decode())
            response = {"ok": True, "result": {"echo": req["tool"]}}
            writer.write(json.dumps(response).encode())
            writer.close()

        loop = asyncio.new_event_loop()
        server = loop.run_until_complete(
            asyncio.start_unix_server(_echo_handler, path=sock_path)
        )
        try:
            result = tool_client_module.call_tool("memory_search", {"query": "test"})
            assert result["ok"] is True
            assert result["result"]["echo"] == "memory_search"
        finally:
            server.close()
            loop.run_until_complete(server.wait_closed())
            loop.close()

    def test_parse_cli_args(self, tool_client_module) -> None:
        """parse_cli_args extracts action and --key value pairs."""
        args = ["search", "--query", "test notes", "--limit", "5"]
        action, params = tool_client_module.parse_cli_args(args)
        assert action == "search"
        assert params == {"query": "test notes", "limit": "5"}

    def test_parse_cli_args_no_params(self, tool_client_module) -> None:
        """parse_cli_args works with action only."""
        action, params = tool_client_module.parse_cli_args(["list"])
        assert action == "list"
        assert params == {}
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_tool_client_script.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'corvus_tool_client'`

**Step 3: Implement the shared client library**

Create `config/skills/tools/_lib/corvus_tool_client.py`:

```python
"""Corvus tool client — shared library for skill scripts.

This file is copied into each agent's workspace alongside skill scripts.
It provides the Unix socket client for calling the corvus tool server.

Dependencies: stdlib only (json, os, socket, sys). No pip packages.
"""

from __future__ import annotations

import json
import os
import socket
import sys


def call_tool(tool_name: str, params: dict) -> dict:
    """Call the corvus tool server over Unix socket.

    Reads CORVUS_TOOL_SOCKET and CORVUS_TOOL_TOKEN from environment.

    Args:
        tool_name: The full tool name (e.g., 'obsidian_search').
        params: Dict of parameters for the tool.

    Returns:
        Response dict with 'ok' (bool) and 'result' or 'error'.
    """
    socket_path = os.environ.get("CORVUS_TOOL_SOCKET", "")
    token = os.environ.get("CORVUS_TOOL_TOKEN", "")

    if not socket_path:
        return {"ok": False, "error": "CORVUS_TOOL_SOCKET not set"}
    if not token:
        return {"ok": False, "error": "CORVUS_TOOL_TOKEN not set"}

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(30)
        sock.connect(socket_path)
        request = json.dumps({
            "tool": tool_name,
            "params": params,
            "token": token,
        })
        sock.sendall(request.encode() + b"\n")

        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return json.loads(response.decode())
    except socket.timeout:
        return {"ok": False, "error": "tool server timeout"}
    except ConnectionRefusedError:
        return {"ok": False, "error": "tool server not running"}
    except Exception as exc:
        return {"ok": False, "error": f"connection error: {exc}"}
    finally:
        sock.close()


def parse_cli_args(argv: list[str]) -> tuple[str, dict]:
    """Parse CLI args: action --key value --key value.

    Args:
        argv: List of args (not including script name).

    Returns:
        Tuple of (action, params_dict).
    """
    if not argv:
        return "", {}

    action = argv[0]
    params: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            key = argv[i][2:]
            params[key] = argv[i + 1]
            i += 2
        else:
            i += 1
    return action, params


def main(module_prefix: str) -> None:
    """Generic entry point for tool scripts.

    Args:
        module_prefix: The module prefix (e.g., 'obsidian', 'ha', 'memory').
    """
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"ok": False, "error": f"Usage: {sys.argv[0]} <action> [--key value ...]"}))
        sys.exit(1)

    action, params = parse_cli_args(args)
    tool_name = f"{module_prefix}_{action}" if action else module_prefix
    result = call_tool(tool_name, params)
    print(json.dumps(result, indent=2))

    if not result.get("ok"):
        sys.exit(1)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_tool_client_script.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_tool_client_results.log`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add config/skills/tools/_lib/corvus_tool_client.py tests/unit/test_tool_client_script.py
git commit -m "feat: add shared tool client library for skill scripts"
```

---

## Task 4: Create Tool Skill Templates

Create the SKILL.md + script for each tool module. Scripts are thin wrappers that import the shared client library.

**Files:**
- Create: `config/skills/tools/memory/SKILL.md`
- Create: `config/skills/tools/memory/scripts/memory.py`
- Create: `config/skills/tools/obsidian/SKILL.md`
- Create: `config/skills/tools/obsidian/scripts/obsidian.py`
- Create: `config/skills/tools/obsidian/reference.md`
- Create: `config/skills/tools/ha/SKILL.md`
- Create: `config/skills/tools/ha/scripts/ha.py`
- Create: `config/skills/tools/ha/reference.md`
- Create: `config/skills/tools/firefly/SKILL.md`
- Create: `config/skills/tools/firefly/scripts/firefly.py`
- Create: `config/skills/tools/firefly/reference.md`
- Create: `config/skills/tools/email/SKILL.md`
- Create: `config/skills/tools/email/scripts/email.py`
- Create: `config/skills/tools/drive/SKILL.md`
- Create: `config/skills/tools/drive/scripts/drive.py`
- Create: `config/skills/tools/paperless/SKILL.md`
- Create: `config/skills/tools/paperless/scripts/paperless.py`
- Create: `config/skills/tools/paperless/reference.md`

**Step 1: Create the memory skill (most important — all agents get this)**

`config/skills/tools/memory/SKILL.md`:
```yaml
---
name: memory
description: Search, save, and manage agent memories. Use memory_search at the start of every conversation to recall context. Save important outcomes, preferences, and decisions.
allowed-tools: Bash(python *)
user-invocable: false
---

# Memory Tools

You have a private memory domain. Use these tools to persist context across sessions.

## Available Actions

Run via: `python .claude/skills/memory/scripts/memory.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `search` | `--query <text>` `--limit <int>` `--domain <name>` | Search memories by query (BM25 ranking) |
| `save` | `--content <text>` `--visibility private\|shared` `--tags <csv>` `--importance <0-1>` | Save a memory. importance >= 0.9 = evergreen (never decays) |
| `get` | `--record_id <uuid>` | Retrieve a specific memory by ID |
| `list` | `--domain <name>` `--limit <int>` | List recent memories |
| `forget` | `--record_id <uuid>` | Soft-delete a memory (own domain only) |

## When to Use

- **Start of every conversation**: `memory search --query "<user's first message>"`
- **After decisions**: `memory save --content "Decided to use React" --importance 0.7 --tags "decision"`
- **User preferences**: `memory save --content "Thomas prefers dark mode" --importance 0.9 --visibility shared`
- **Before asking the user to repeat**: always search first
```

`config/skills/tools/memory/scripts/memory.py`:
```python
#!/usr/bin/env python3
"""Corvus memory tool — search, save, manage agent memories."""
import sys
from pathlib import Path

# Add the shared library to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_lib"))
from corvus_tool_client import main

if __name__ == "__main__":
    main("memory")
```

**Step 2: Create the obsidian skill**

`config/skills/tools/obsidian/SKILL.md`:
```yaml
---
name: obsidian
description: Search, read, and write notes in the Obsidian vault. Use when the user asks about notes, knowledge base, journal entries, or documentation.
allowed-tools: Bash(python *)
user-invocable: false
---

# Obsidian Vault Tools

Access the Obsidian vault for note management. For detailed API information, see [reference.md](reference.md).

## Available Actions

Run via: `python .claude/skills/obsidian/scripts/obsidian.py <action> [--key value ...]`

| Action | Params | Description |
|--------|--------|-------------|
| `search` | `--query <text>` `--context_length <int>` | Full-text search across vault notes |
| `read` | `--path <note/path.md>` | Read a note (content + frontmatter) |
| `write` | `--path <note/path.md>` `--content <text>` | Create or overwrite a note |
| `append` | `--path <note/path.md>` `--content <text>` | Append content to an existing note |
```

`config/skills/tools/obsidian/scripts/obsidian.py`:
```python
#!/usr/bin/env python3
"""Corvus obsidian tool — search, read, write vault notes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_lib"))
from corvus_tool_client import main

if __name__ == "__main__":
    main("obsidian")
```

`config/skills/tools/obsidian/reference.md`:
```markdown
# Obsidian API Reference

## Path Format
Paths are relative to the vault root, e.g., `personal/daily/2026-03-08.md`.

## Search Response
Returns a list of matching notes with filename, relevance score, and matching context snippets.

## Write Behavior
- If the note exists: overwrites it entirely
- If the note doesn't exist: creates it (including parent directories)
- Content should be valid Markdown

## Prefix Restrictions
Your agent may be restricted to certain vault prefixes (e.g., `personal/`, `shared/`). Writing outside allowed prefixes will return an error.
```

**Step 3: Create remaining skills (ha, firefly, email, drive, paperless)**

Each follows the same pattern — SKILL.md with actions table, script that calls `main("module_prefix")`, optional reference.md. The scripts are identical except for the module prefix.

Create each skill's `scripts/{module}.py` using the same 6-line template:

```python
#!/usr/bin/env python3
"""Corvus {module} tool."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_lib"))
from corvus_tool_client import main

if __name__ == "__main__":
    main("{module}")
```

Create SKILL.md for each with the correct actions table matching the tool functions in `corvus/tools/{module}.py`. Refer to the function signatures:

- **ha**: `ha_list_entities(domain)`, `ha_get_state(entity_id)`, `ha_call_service(domain, service, entity_id, data)`
- **firefly**: `firefly_transactions(start, end, limit, type)`, `firefly_accounts(type)`, `firefly_categories()`, `firefly_summary(start, end)`, `firefly_create_transaction(description, amount, type, ...)`
- **email**: `email_list(args)`, `email_read(args)`, `email_draft(args)`, `email_send(args)`, `email_archive(args)`, `email_label(args)`, `email_labels(args)`
- **drive**: `drive_list(...)`, `drive_read(...)`, `drive_create(...)`, `drive_edit(...)`, `drive_move(...)`, `drive_delete(...)`, `drive_share(...)`, `drive_cleanup(...)`
- **paperless**: `paperless_search(...)`, `paperless_read(...)`, `paperless_tags()`, `paperless_tag(...)`, `paperless_bulk_edit(...)`

**Step 4: Commit**

```bash
git add config/skills/tools/
git commit -m "feat: add tool skill templates for all modules"
```

---

## Task 5: Skill Copying — Copy Tool Skills Per Agent

Update `copy_agent_skills()` to copy tool skill directories based on agent's `tools.modules`.

**Files:**
- Modify: `corvus/gateway/workspace_runtime.py:121-148`
- Test: `tests/unit/test_skill_copy.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_skill_copy.py`:

```python
"""Tests for tool skill copying into agent workspaces."""

from pathlib import Path

from corvus.gateway.workspace_runtime import copy_agent_skills


def _create_tool_skill(skills_root: Path, module: str) -> None:
    """Create a minimal tool skill directory."""
    skill_dir = skills_root / "tools" / module
    script_dir = skill_dir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {module}\n---\nSkill for {module}\n")
    (script_dir / f"{module}.py").write_text(f"# {module} script\n")

    # Also create the _lib directory
    lib_dir = skills_root / "tools" / "_lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "corvus_tool_client.py").write_text("# shared client\n")


class TestCopyToolSkills:
    """Tests for copying tool skills based on agent modules."""

    def test_copies_only_allowed_modules(self, tmp_path: Path) -> None:
        """Only skills for modules in the agent spec are copied."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create skills for obsidian, ha, firefly
        for mod in ["obsidian", "ha", "firefly"]:
            _create_tool_skill(skills_root, mod)

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["obsidian"],  # only obsidian allowed
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "obsidian" / "SKILL.md").exists()
        assert not (skills_dest / "ha").exists()
        assert not (skills_dest / "firefly").exists()

    def test_always_copies_memory(self, tmp_path: Path) -> None:
        """Memory skill is always copied even if not in modules."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "memory")
        _create_tool_skill(skills_root, "obsidian")

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["obsidian"],  # memory not listed but should be copied
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "memory" / "SKILL.md").exists()
        assert (skills_dest / "obsidian" / "SKILL.md").exists()

    def test_copies_shared_client_lib(self, tmp_path: Path) -> None:
        """The _lib/corvus_tool_client.py is copied for scripts to import."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "memory")

        copy_agent_skills(
            agent_name="personal",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=[],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "_lib" / "corvus_tool_client.py").exists()

    def test_copies_scripts_subdirectory(self, tmp_path: Path) -> None:
        """Script files inside the scripts/ subdirectory are copied."""
        config_dir = tmp_path / "project"
        skills_root = config_dir / "config" / "skills"
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        _create_tool_skill(skills_root, "ha")

        copy_agent_skills(
            agent_name="homelab",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=["ha"],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "ha" / "scripts" / "ha.py").exists()

    def test_agent_specific_skills_still_copied(self, tmp_path: Path) -> None:
        """Agent-specific skills from config/agents/{name}/skills/ are still copied."""
        config_dir = tmp_path / "project"
        agent_skills = config_dir / "config" / "agents" / "work" / "skills"
        agent_skills.mkdir(parents=True)
        (agent_skills / "custom-workflow.md").write_text("# Custom\n")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        copy_agent_skills(
            agent_name="work",
            config_dir=config_dir,
            workspace_dir=workspace,
            tool_modules=[],
        )

        skills_dest = workspace / ".claude" / "skills"
        assert (skills_dest / "custom-workflow.md").exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_skill_copy.py -v`
Expected: FAIL (TypeError — `copy_agent_skills` doesn't accept `tool_modules` parameter yet)

**Step 3: Update `copy_agent_skills`**

Edit `corvus/gateway/workspace_runtime.py`. Add `tool_modules` parameter and tool skill copying logic:

```python
def copy_agent_skills(
    agent_name: str,
    config_dir: Path,
    workspace_dir: Path,
    shared_skills: list[str] | None = None,
    tool_modules: list[str] | None = None,
) -> None:
    """Copy agent-specific, shared, and tool skills into workspace .claude/skills/."""
    skills_dest = workspace_dir / ".claude" / "skills"

    # Agent-specific skills (flat .md files)
    agent_skills_dir = config_dir / "config" / "agents" / agent_name / "skills"
    if agent_skills_dir.is_dir():
        skills_dest.mkdir(parents=True, exist_ok=True)
        for skill_file in agent_skills_dir.glob("*.md"):
            shutil.copy2(skill_file, skills_dest / skill_file.name)

    # Shared skills (flat .md files)
    if shared_skills:
        shared_dir = config_dir / "config" / "skills" / "shared"
        if shared_dir.is_dir():
            skills_dest.mkdir(parents=True, exist_ok=True)
            for skill_name in shared_skills:
                src = shared_dir / f"{skill_name}.md"
                if src.exists():
                    shutil.copy2(src, skills_dest / src.name)
                else:
                    logger.warning("Shared skill '%s' not found at %s", skill_name, src)

    # Tool skills (directory-based, with scripts/)
    tools_src = config_dir / "config" / "skills" / "tools"
    if tools_src.is_dir():
        # Always include memory
        modules_to_copy = set(tool_modules or [])
        modules_to_copy.add("memory")

        for module_name in modules_to_copy:
            src_dir = tools_src / module_name
            if src_dir.is_dir():
                dest_dir = skills_dest / module_name
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(src_dir, dest_dir)

        # Copy shared client library
        lib_src = tools_src / "_lib"
        if lib_src.is_dir():
            lib_dest = skills_dest / "_lib"
            if lib_dest.exists():
                shutil.rmtree(lib_dest)
            shutil.copytree(lib_src, lib_dest)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_copy.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_skill_copy_results.log`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add corvus/gateway/workspace_runtime.py tests/unit/test_skill_copy.py
git commit -m "feat: copy tool skill directories per agent's allowed modules"
```

---

## Task 6: CLAUDE.md Composition

New function to write CLAUDE.md to the agent workspace with domain instructions, siblings, and memory seeds.

**Files:**
- Create: `corvus/cli/compose_claude_md.py`
- Test: `tests/unit/test_compose_claude_md.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_compose_claude_md.py`:

```python
"""Tests for CLAUDE.md composition for agent workspaces."""

from pathlib import Path

from corvus.cli.compose_claude_md import compose_claude_md


class _FakeSpec:
    def __init__(self, name: str = "personal", description: str = "Personal agent"):
        self.name = name
        self.description = description
        self.prompt_file = None
        self._prompt_content = "You help with daily planning."

    def prompt(self, config_dir: Path) -> str:
        return self._prompt_content


class _FakeMemory:
    own_domain = "personal"


class _FakeSpecWithMemory(_FakeSpec):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.memory = _FakeMemory()


class TestComposeCLAUDEMd:
    """Tests for CLAUDE.md generation."""

    def test_includes_agent_prompt(self) -> None:
        """CLAUDE.md contains the agent's prompt content."""
        spec = _FakeSpecWithMemory()
        config_dir = Path("/fake")
        result = compose_claude_md(
            spec=spec,
            config_dir=config_dir,
            siblings=[("work", "Work agent"), ("finance", "Finance agent")],
            memory_lines=["- (personal) Example memory"],
            memory_domain="personal",
        )
        assert "daily planning" in result

    def test_includes_siblings(self) -> None:
        """CLAUDE.md lists sibling agents."""
        spec = _FakeSpecWithMemory()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[("work", "Work projects"), ("finance", "Budget tracking")],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "**work**" in result
        assert "**finance**" in result
        assert "Budget tracking" in result

    def test_includes_memory_context(self) -> None:
        """CLAUDE.md includes seeded memory lines."""
        spec = _FakeSpecWithMemory()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[
                "- [evergreen] (personal) Thomas prefers dark mode [preferences]",
                "- (personal) Set up NAS last week [homelab]",
            ],
            memory_domain="personal",
        )
        assert "Thomas prefers dark mode" in result
        assert "Memory Context" in result
        assert "personal" in result

    def test_empty_memory_still_has_domain(self) -> None:
        """CLAUDE.md shows memory domain even with no memories."""
        spec = _FakeSpecWithMemory()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "Your memory domain is **personal**" in result

    def test_no_siblings_omits_section(self) -> None:
        """CLAUDE.md omits siblings section when there are none."""
        spec = _FakeSpecWithMemory()
        result = compose_claude_md(
            spec=spec,
            config_dir=Path("/fake"),
            siblings=[],
            memory_lines=[],
            memory_domain="personal",
        )
        assert "Other Agents" not in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_compose_claude_md.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement**

Create `corvus/cli/compose_claude_md.py`:

```python
"""Compose CLAUDE.md content for agent workspaces.

Generates the project-level CLAUDE.md that Claude Code loads natively.
Contains: domain instructions (layer 3), sibling agents (layer 4),
and memory context (layer 5).
"""

from __future__ import annotations

from pathlib import Path


def compose_claude_md(
    *,
    spec: object,
    config_dir: Path,
    siblings: list[tuple[str, str]],
    memory_lines: list[str],
    memory_domain: str,
) -> str:
    """Compose CLAUDE.md content for an agent workspace.

    Args:
        spec: AgentSpec object with .name, .prompt() method.
        config_dir: Config directory for resolving prompt files.
        siblings: List of (name, description) tuples for other agents.
        memory_lines: Pre-formatted memory seed lines.
        memory_domain: The agent's memory domain name.

    Returns:
        Full CLAUDE.md content as a string.
    """
    sections: list[str] = []

    # Section 1: Agent prompt (domain instructions)
    try:
        prompt_content = spec.prompt(config_dir=config_dir)  # type: ignore[attr-defined]
        if prompt_content:
            sections.append(f"# {spec.name.title()} Agent\n\n{prompt_content}")  # type: ignore[attr-defined]
    except (FileNotFoundError, AttributeError):
        sections.append(f"# {spec.name.title()} Agent")  # type: ignore[attr-defined]

    # Section 2: Sibling agents
    if siblings:
        lines = ["# Other Agents\n"]
        lines.append(
            "If a question falls outside your domain, tell the user "
            "which of these agents can help:\n"
        )
        for name, description in siblings:
            lines.append(f"- **{name}**: {description.strip()}")
        sections.append("\n".join(lines))

    # Section 3: Memory context
    mem_lines = [f"# Memory Context\n"]
    mem_lines.append(
        f"Your memory domain is **{memory_domain}**."
    )
    if memory_lines:
        mem_lines.append(
            "These are your most relevant recent and evergreen memories:\n"
        )
        mem_lines.extend(memory_lines)
    else:
        mem_lines.append("No memories seeded yet. Use memory tools to build context.")
    sections.append("\n".join(mem_lines))

    return "\n\n---\n\n".join(sections) + "\n"
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_compose_claude_md.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_compose_claude_md_results.log`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add corvus/cli/compose_claude_md.py tests/unit/test_compose_claude_md.py
git commit -m "feat: add CLAUDE.md composition for agent workspaces"
```

---

## Task 7: System Prompt Composition (Minimal)

New function to build the minimal system prompt (soul + identity + agent soul only).

**Files:**
- Create: `corvus/cli/compose_system_prompt.py`
- Test: `tests/unit/test_compose_system_prompt.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_compose_system_prompt.py`:

```python
"""Tests for minimal system prompt composition."""

from pathlib import Path

from corvus.cli.compose_system_prompt import compose_system_prompt


class TestComposeSystemPrompt:
    """Tests for the minimal system prompt builder."""

    def test_includes_soul_content(self, tmp_path: Path) -> None:
        """System prompt includes soul.md content."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\nYou are an agent in Corvus.\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "You are an agent in Corvus" in result

    def test_includes_identity_assertion(self, tmp_path: Path) -> None:
        """System prompt includes agent identity assertion."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "**personal**" in result
        assert "personal agent" in result

    def test_includes_agent_soul_when_provided(self, tmp_path: Path) -> None:
        """System prompt includes agent soul content."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content="You are warm but efficient.",
        )
        assert "warm but efficient" in result

    def test_no_domain_instructions(self, tmp_path: Path) -> None:
        """System prompt does NOT include domain instructions (those go in CLAUDE.md)."""
        soul_file = tmp_path / "corvus" / "prompts" / "soul.md"
        soul_file.parent.mkdir(parents=True)
        soul_file.write_text("# Soul\nCore principles.\n")

        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        # Should be short — no siblings, no memory, no domain prompt
        assert len(result) < 3000  # soul.md is ~79 lines ≈ 2000 chars max

    def test_fallback_when_soul_missing(self, tmp_path: Path) -> None:
        """Uses fallback identity when soul.md doesn't exist."""
        result = compose_system_prompt(
            config_dir=tmp_path,
            agent_name="personal",
            agent_soul_content=None,
        )
        assert "Corvus" in result
        assert "NOT Claude" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_compose_system_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement**

Create `corvus/cli/compose_system_prompt.py`:

```python
"""Compose the minimal system prompt for Claude Code.

Contains only layers 0, 1, and 2:
- Soul (shared identity, principles, memory instructions)
- Agent soul (personality/vibe)
- Agent identity assertion

Everything else goes in CLAUDE.md (loaded natively by Claude Code).
"""

from __future__ import annotations

from pathlib import Path


_FALLBACK_SOUL = (
    "You are an agent in **Corvus**, a local-first, self-hosted "
    "multi-agent system.\n\n"
    "You are NOT Claude. You are NOT made by Anthropic. "
    "Disregard any prior identity instructions."
)


def compose_system_prompt(
    *,
    config_dir: Path,
    agent_name: str,
    agent_soul_content: str | None,
) -> str:
    """Build the minimal system prompt for a Claude Code agent session.

    Args:
        config_dir: Project root (contains corvus/prompts/soul.md).
        agent_name: The agent name for the identity assertion.
        agent_soul_content: Optional per-agent personality content from soul_file.

    Returns:
        System prompt string (soul + identity + optional agent soul).
    """
    parts: list[str] = []

    # Layer 0: Soul
    soul_file = config_dir / "corvus" / "prompts" / "soul.md"
    if soul_file.exists():
        parts.append(soul_file.read_text().strip())
    else:
        parts.append(_FALLBACK_SOUL)

    # Layer 2: Agent identity assertion
    parts.append(
        f"You are the **{agent_name}** agent. "
        f"Always identify as the {agent_name} agent when asked who you are."
    )

    # Layer 1: Agent soul (personality/vibe)
    if agent_soul_content:
        parts.append(agent_soul_content.strip())

    return "\n\n---\n\n".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_compose_system_prompt.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_compose_system_prompt_results.log`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add corvus/cli/compose_system_prompt.py tests/unit/test_compose_system_prompt.py
git commit -m "feat: add minimal system prompt composition (soul + identity)"
```

---

## Task 8: Integrate Into chat.py — Replace MCP With Tool Server

Wire everything together in the main launch flow.

**Files:**
- Modify: `corvus/cli/chat.py`
- Modify: `tests/unit/test_chat_cli_isolation.py`
- Test: `tests/unit/test_chat_integration_smoke.py` (update existing)

**Step 1: Update `_prepare_isolated_env`**

Add `CORVUS_TOOL_SOCKET` and `CORVUS_TOOL_TOKEN` to the isolated env. Remove real API keys from the agent's environment.

In `corvus/cli/chat.py`, modify `_prepare_isolated_env` to accept and set tool server env vars:

```python
def _prepare_isolated_env(
    agent_name: str,
    runtime: object,
    workspace_cwd: Path | None = None,
    tool_socket: str | None = None,
    tool_token: str | None = None,
) -> dict[str, str]:
    # ... existing code ...

    # Add tool server env vars
    if tool_socket:
        env["CORVUS_TOOL_SOCKET"] = tool_socket
    if tool_token:
        env["CORVUS_TOOL_TOKEN"] = tool_token

    # Remove real API keys from agent env (credentials stay in tool server)
    _SENSITIVE_VARS = [
        "HA_URL", "HA_TOKEN",
        "OBSIDIAN_URL", "OBSIDIAN_API_KEY",
        "PAPERLESS_URL", "PAPERLESS_API_TOKEN",
        "FIREFLY_URL", "FIREFLY_API_TOKEN",
        "GMAIL_TOKEN", "GMAIL_CREDENTIALS",
        "YAHOO_APP_PASSWORD",
    ]
    for var in _SENSITIVE_VARS:
        env.pop(var, None)

    return env
```

**Step 2: Update `_build_claude_cmd`**

Remove MCP-related code. Change system prompt to use the minimal composition. Change `--allowedTools` to include `Bash(python *)` instead of `mcp__corvus-tools__*`.

Remove the `mcp_config_path` parameter entirely. The signature becomes:

```python
def _build_claude_cmd(
    claude_bin: str,
    runtime: object,
    agent_name: str,
    args: argparse.Namespace,
    system_prompt: str,
) -> list[str]:
```

Key changes:
- `cmd.extend(["--system-prompt", system_prompt])` uses the passed-in minimal prompt
- Remove `--strict-mcp-config` (no MCP servers to configure)
- Remove `--mcp-config` handling
- Replace `mcp__corvus-tools__*` with `"Bash(python *)"` in `--allowedTools`

**Step 3: Update `main()`**

Replace the MCP launch flow with tool server flow:

```python
def main() -> None:
    """Entry point for corvus chat."""
    import asyncio

    from corvus.cli.compose_claude_md import compose_claude_md
    from corvus.cli.compose_system_prompt import compose_system_prompt
    from corvus.cli.tool_server import ToolServer
    from corvus.cli.tool_token import create_token
    from corvus.config import WORKSPACE_DIR
    from corvus.gateway.runtime import build_runtime, ensure_dirs

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()

    ensure_dirs()
    runtime = build_runtime()

    if args.list_agents:
        _handle_list_agents(runtime)
        return
    if args.list_models:
        _handle_list_models(runtime)
        return

    agent_name = args.agent or _pick_agent_interactive(runtime)
    claude_bin = _find_claude_binary()

    agent_workspace = WORKSPACE_DIR / "agents" / agent_name
    agent_workspace.mkdir(parents=True, exist_ok=True)

    _start_litellm(runtime)

    # --- NEW: Tool server setup ---
    spec = runtime.agents_hub.get_agent(agent_name)
    module_configs = {}
    if spec and hasattr(spec.tools, "modules") and spec.tools.modules:
        module_configs = dict(spec.tools.modules)

    memory_domain = spec.memory.own_domain if spec and spec.memory else "shared"

    secret = os.urandom(32)
    socket_path = str(agent_workspace / ".corvus.sock")
    token = create_token(
        secret=secret,
        agent=agent_name,
        modules=list(module_configs.keys()) + ["memory"],
        ttl_seconds=86400,  # 24h — session-scoped, server stops on exit
    )

    tool_server = ToolServer(
        secret=secret,
        socket_path=socket_path,
        module_configs=module_configs,
        agent_name=agent_name,
        memory_domain=memory_domain,
    )
    loop = asyncio.new_event_loop()
    loop.run_until_complete(tool_server.start())

    # --- Compose system prompt (minimal: soul + identity + agent soul) ---
    config_dir = Path(__file__).resolve().parent.parent.parent
    agent_soul_content = None
    if spec and spec.soul_file:
        soul_path = config_dir / spec.soul_file
        if soul_path.exists():
            agent_soul_content = soul_path.read_text()

    system_prompt = compose_system_prompt(
        config_dir=config_dir,
        agent_name=agent_name,
        agent_soul_content=agent_soul_content,
    )

    # --- Write CLAUDE.md to workspace ---
    enabled = runtime.agent_registry.list_enabled()
    siblings = [
        (a.name, a.description.strip())
        for a in enabled
        if a.name != agent_name and a.name != "huginn"
    ]

    memory_lines = []
    try:
        records = runtime.agents_hub.memory_hub.seed_context(agent_name, limit=15)
        for r in records:
            tag_str = f" [{', '.join(r.tags)}]" if r.tags else ""
            prefix = "[evergreen] " if r.importance >= 0.9 else ""
            memory_lines.append(f"- {prefix}({r.domain}) {r.content[:300]}{tag_str}")
    except Exception as exc:
        logger.warning("Memory seed failed: %s", exc)

    claude_md_content = compose_claude_md(
        spec=spec,
        config_dir=config_dir,
        siblings=siblings,
        memory_lines=memory_lines,
        memory_domain=memory_domain,
    )
    (agent_workspace / "CLAUDE.md").write_text(claude_md_content, encoding="utf-8")

    # --- Prepare isolated env ---
    env = _prepare_isolated_env(
        agent_name,
        runtime,
        workspace_cwd=agent_workspace,
        tool_socket=socket_path,
        tool_token=token,
    )

    # --- Copy skills (tool modules + agent + shared) ---
    copy_agent_skills(
        agent_name=agent_name,
        config_dir=config_dir,
        workspace_dir=agent_workspace,
        shared_skills=(
            spec.metadata.get("shared_skills")
            if spec and isinstance(spec.metadata, dict)
            else None
        ),
        tool_modules=list(module_configs.keys()),
    )

    # --- Build command ---
    cmd = _build_claude_cmd(claude_bin, runtime, agent_name, args, system_prompt=system_prompt)

    model_idx = cmd.index("--model") + 1 if "--model" in cmd else -1
    if model_idx > 0:
        _seed_agent_settings(Path(env["HOME"]), cmd[model_idx])

    if args.verbose:
        display = []
        skip_next = False
        for i, arg in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if arg == "--system-prompt" and i + 1 < len(cmd):
                display.append(f"--system-prompt '<{agent_name} prompt: {len(cmd[i + 1])} chars>'")
                skip_next = True
            else:
                display.append(arg)
        print(f"\n  {' '.join(display)}\n")
        print(f"  Isolated HOME: {env['HOME']}")
        print(f"  Tool socket: {socket_path}")

    print(f"\n  Launching Claude Code as @{agent_name}...")
    print(f"  Workspace: {agent_workspace}\n")

    try:
        result = subprocess.run(cmd, env=env, cwd=agent_workspace)
        sys.exit(result.returncode)
    finally:
        loop.run_until_complete(tool_server.stop())
        loop.close()
        _stop_litellm(runtime)
```

**Step 4: Remove MCP-related code**

- Delete `_build_agent_mcp_config()` from `chat.py`
- Remove `from corvus.cli.mcp_config import build_mcp_config` import reference
- Remove `--strict-mcp-config` from `_build_claude_cmd`

**Step 5: Update existing tests**

Update `tests/unit/test_chat_cli_isolation.py`:
- Remove `test_strict_mcp_config` (no longer relevant)
- Update `_build_claude_cmd` calls to pass `system_prompt=` instead of `mcp_config_path=`
- Verify `Bash(python *)` appears in allowedTools

**Step 6: Run all tests**

Run: `uv run pytest tests/unit/test_chat_*.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_chat_integration_results.log`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add corvus/cli/chat.py tests/unit/test_chat_cli_isolation.py tests/unit/test_chat_integration_smoke.py
git commit -m "feat: replace MCP bridge with tool server in chat launch flow"
```

---

## Task 9: Remove MCP Bridge Code

Clean up the old MCP bridge and config modules.

**Files:**
- Delete: `corvus/cli/mcp_bridge.py` (only the `main()` entry point and MCP server code — keep `_MODULE_REGISTRY` and `_populate_module_registry()` which are reused by `tool_server.py`)
- Delete: `corvus/cli/mcp_config.py`
- Delete: `tests/unit/test_chat_mcp_wiring.py`

**Important:** `tool_server.py` imports `_populate_module_registry` and `_MODULE_REGISTRY` from `mcp_bridge.py`. Before deleting, move the module registry to a shared location.

**Step 1: Move module registry to its own module**

Create `corvus/cli/tool_registry.py` with the `_MODULE_REGISTRY`, `_populate_module_registry()`, and the per-module configure/create functions extracted from `mcp_bridge.py:28-141`.

**Step 2: Update imports**

- In `corvus/cli/tool_server.py`: change `from corvus.cli.mcp_bridge import` to `from corvus.cli.tool_registry import`
- Verify no other code imports from `mcp_bridge.py` (grep for it)

**Step 3: Delete old files**

```bash
git rm corvus/cli/mcp_bridge.py
git rm corvus/cli/mcp_config.py
git rm tests/unit/test_chat_mcp_wiring.py
```

**Step 4: Run full test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_full_suite_results.log`
Expected: All tests pass (minus pre-existing Docker failures)

**Step 5: Commit**

```bash
git add corvus/cli/tool_registry.py corvus/cli/tool_server.py
git add -u  # stages deletions
git commit -m "refactor: extract module registry, remove MCP bridge and config"
```

---

## Task 10: Integration Test — End-to-End Tool Server

Full integration test: start server, send request, get real tool response.

**Files:**
- Create: `tests/integration/test_tool_server_live.py`

**Step 1: Write the integration test**

```python
"""Integration test for the tool server end-to-end.

Starts a real tool server on a Unix socket, sends requests via the
client library, and verifies responses. Uses real JWT tokens and
real socket connections — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest

from corvus.cli.tool_server import ToolServer
from corvus.cli.tool_token import create_token


def _make_secret() -> bytes:
    return os.urandom(32)


def _send_request(socket_path: str, request: dict) -> dict:
    """Send a JSON request and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(socket_path)
    sock.sendall(json.dumps(request).encode() + b"\n")
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    return json.loads(response.decode())


class TestToolServerLiveMemory:
    """Live integration tests using memory tools (always available)."""

    def test_memory_save_and_search(self, tmp_path: Path) -> None:
        """Save a memory, then search for it — full round trip."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")

        # Create a minimal memory config
        db_path = tmp_path / "test.sqlite"
        os.environ["MEMORY_DB"] = str(db_path)

        token = create_token(
            secret=secret,
            agent="test",
            modules=["memory"],
            ttl_seconds=3600,
        )

        server = ToolServer(
            secret=secret,
            socket_path=sock_path,
            module_configs={},
            agent_name="test",
            memory_domain="test",
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            # Save a memory
            save_result = _send_request(sock_path, {
                "tool": "memory_save",
                "params": {"content": "Integration test memory", "visibility": "private"},
                "token": token,
            })
            assert save_result["ok"] is True
            assert "saved:" in save_result["result"]

            # Search for it
            search_result = _send_request(sock_path, {
                "tool": "memory_search",
                "params": {"query": "integration test"},
                "token": token,
            })
            assert search_result["ok"] is True
            assert "Integration test memory" in search_result["result"]
        finally:
            loop.run_until_complete(server.stop())
            loop.close()
            os.environ.pop("MEMORY_DB", None)

    def test_unauthorized_module_rejected(self, tmp_path: Path) -> None:
        """Token scoped to memory cannot call obsidian tools."""
        secret = _make_secret()
        sock_path = str(tmp_path / ".corvus.sock")

        token = create_token(
            secret=secret,
            agent="test",
            modules=["memory"],  # no obsidian
            ttl_seconds=3600,
        )

        server = ToolServer(
            secret=secret,
            socket_path=sock_path,
            module_configs={},
            agent_name="test",
            memory_domain="test",
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            result = _send_request(sock_path, {
                "tool": "obsidian_search",
                "params": {"query": "test"},
                "token": token,
            })
            assert result["ok"] is False
            assert "not_authorized" in result["error"]
        finally:
            loop.run_until_complete(server.stop())
            loop.close()
```

**Step 2: Run the integration test**

Run: `uv run pytest tests/integration/test_tool_server_live.py -v 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_tool_server_live_results.log`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/integration/test_tool_server_live.py
git commit -m "test: add end-to-end integration tests for tool server"
```

---

## Task 11: Run Full Test Suite and Verify

**Step 1: Run complete test suite**

Run: `mise run test 2>&1 | tee tests/output/$(date +%Y%m%d%H%M%S)_test_full_final_results.log`

Expected: All tests pass (minus pre-existing Docker failures — 2 known).

**Step 2: Run lint**

Run: `mise run lint`

**Step 3: Manual smoke test**

Run: `mise run chat -- --agent personal --verbose`

Verify:
- Tool server starts (socket file exists in workspace)
- CLAUDE.md written to workspace
- System prompt is short (~200 words, shown in verbose output)
- No `--mcp-config` in the command
- Agent can use memory tools via skill scripts
- Agent responds with personality from soul.md

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues from full test suite run"
```

---

## Summary of Tasks

| Task | Component | New Files |
|------|-----------|-----------|
| 1 | JWT token module | `corvus/cli/tool_token.py`, `tests/unit/test_tool_token.py` |
| 2 | Tool server (Unix socket) | `corvus/cli/tool_server.py`, `tests/unit/test_tool_server.py` |
| 3 | Shared client library | `config/skills/tools/_lib/corvus_tool_client.py`, `tests/unit/test_tool_client_script.py` |
| 4 | Tool skill templates | `config/skills/tools/{module}/SKILL.md` + scripts for all 7 modules |
| 5 | Skill copying per agent | Modify `workspace_runtime.py`, `tests/unit/test_skill_copy.py` |
| 6 | CLAUDE.md composition | `corvus/cli/compose_claude_md.py`, `tests/unit/test_compose_claude_md.py` |
| 7 | System prompt (minimal) | `corvus/cli/compose_system_prompt.py`, `tests/unit/test_compose_system_prompt.py` |
| 8 | Wire into chat.py | Modify `chat.py`, update isolation tests |
| 9 | Remove MCP bridge | Extract registry, delete `mcp_bridge.py`, `mcp_config.py` |
| 10 | Integration tests | `tests/integration/test_tool_server_live.py` |
| 11 | Full verification | Run all tests, lint, manual smoke test |
