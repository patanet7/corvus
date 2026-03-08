"""Tests for the corvus tool server.

Tests the request handling, JWT auth, and module dispatch logic.
Uses real Unix sockets — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

import pytest

from corvus.cli.tool_server import ToolServer
from corvus.cli.tool_token import create_token

# Fixtures (short_sock_path, server_ctx) auto-discovered from conftest.py.


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
        assert result["error"] == "auth_failed"

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
        """Expired token is rejected with generic auth_failed."""
        sock_path, secret = server_ctx
        # Construct expired token manually (create_token rejects ttl <= 0)
        import hashlib
        import hmac as hmac_mod
        import time

        from corvus.cli.tool_token import _b64encode

        header = _b64encode(json.dumps({"alg": "HS256", "typ": "CVT"}).encode())
        payload_dict = {
            "agent": "personal",
            "modules": ["obsidian"],
            "exp": int(time.time()) - 10,
        }
        payload = _b64encode(json.dumps(payload_dict).encode())
        signing_input = f"{header}.{payload}".encode()
        sig = _b64encode(hmac_mod.new(secret, signing_input, hashlib.sha256).digest())
        expired_token = f"{header}.{payload}.{sig}"

        result = _send_request(
            sock_path,
            {"tool": "obsidian_search", "params": {"query": "test"}, "token": expired_token},
        )
        assert result["ok"] is False
        assert result["error"] == "auth_failed"


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
    """Tests for tool_name -> module mapping."""

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
