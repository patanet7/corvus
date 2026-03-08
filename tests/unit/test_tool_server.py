"""Tests for the corvus tool server.

Tests the request handling, JWT auth, and module dispatch logic.
Uses real Unix sockets — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from corvus.cli.tool_server import ToolServer
from corvus.cli.tool_token import create_token


def _make_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def short_sock_path():
    """Provide a short socket path that fits macOS 104-byte AF_UNIX limit."""
    tmpdir = tempfile.mkdtemp(prefix="cvs")
    path = os.path.join(tmpdir, "s.sock")
    yield path
    # Cleanup
    if os.path.exists(path):
        os.unlink(path)
    if os.path.exists(tmpdir):
        os.rmdir(tmpdir)


@pytest.fixture()
def server_ctx(short_sock_path):
    """Start a ToolServer on a background event loop, yield (sock_path, secret, loop), then stop."""
    secret = _make_secret()
    server = ToolServer(secret=secret, socket_path=short_sock_path, module_configs={})

    loop = asyncio.new_event_loop()
    started = threading.Event()

    def _run():
        loop.run_until_complete(server.start())
        started.set()
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    started.wait(timeout=5)

    yield short_sock_path, secret

    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5)
    loop.run_until_complete(server.stop())
    loop.close()


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

    def test_rejects_missing_token(self, server_ctx) -> None:
        """Request without token is rejected."""
        sock_path, secret = server_ctx
        result = _send_request(sock_path, {"tool": "obsidian_search", "params": {}})
        assert result["ok"] is False
        assert "token" in result["error"].lower() or "auth" in result["error"].lower()

    def test_rejects_invalid_token(self, server_ctx) -> None:
        """Request with wrong-secret token is rejected."""
        sock_path, secret = server_ctx
        wrong_secret = _make_secret()
        bad_token = create_token(
            secret=wrong_secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        result = _send_request(
            sock_path,
            {"tool": "obsidian_search", "params": {}, "token": bad_token},
        )
        assert result["ok"] is False

    def test_rejects_unauthorized_module(self, server_ctx) -> None:
        """Token for obsidian cannot call ha tools."""
        sock_path, secret = server_ctx
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        result = _send_request(
            sock_path,
            {"tool": "ha_list_entities", "params": {}, "token": token},
        )
        assert result["ok"] is False
        assert "not_authorized" in result["error"]

    def test_rejects_expired_token(self, server_ctx) -> None:
        """Expired token is rejected."""
        sock_path, secret = server_ctx
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=-1,
        )
        result = _send_request(
            sock_path,
            {"tool": "obsidian_search", "params": {"query": "test"}, "token": token},
        )
        assert result["ok"] is False


class TestToolServerSocket:
    """Tests for socket lifecycle."""

    def test_socket_file_created_on_start(self, short_sock_path: str) -> None:
        """Socket file exists after start()."""
        secret = _make_secret()
        server = ToolServer(secret=secret, socket_path=short_sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        try:
            assert Path(short_sock_path).exists()
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    def test_socket_cleaned_up_on_stop(self, short_sock_path: str) -> None:
        """Socket file is removed after stop()."""
        secret = _make_secret()
        server = ToolServer(secret=secret, socket_path=short_sock_path, module_configs={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server.start())
        loop.run_until_complete(server.stop())
        loop.close()

        assert not Path(short_sock_path).exists()


class TestToolServerDispatch:
    """Tests for tool_name → module mapping."""

    def test_extracts_module_from_tool_name(self, short_sock_path: str) -> None:
        """'obsidian_search' maps to module 'obsidian'."""
        secret = _make_secret()
        server = ToolServer(secret=secret, socket_path=short_sock_path, module_configs={})
        assert server._extract_module("obsidian_search") == "obsidian"
        assert server._extract_module("ha_list_entities") == "ha"
        assert server._extract_module("ha_get_state") == "ha"
        assert server._extract_module("firefly_transactions") == "firefly"
        assert server._extract_module("memory_search") == "memory"

    def test_unknown_tool_returns_error(self, server_ctx) -> None:
        """Request for unregistered tool in an authorized module returns error."""
        sock_path, secret = server_ctx
        token = create_token(
            secret=secret,
            agent="personal",
            modules=["obsidian"],
            ttl_seconds=3600,
        )
        result = _send_request(
            sock_path,
            {"tool": "obsidian_nonexistent", "params": {}, "token": token},
        )
        assert result["ok"] is False
        assert "unknown" in result["error"].lower()
