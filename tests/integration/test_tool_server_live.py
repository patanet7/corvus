"""Integration test for the tool server end-to-end.

Starts a real tool server on a Unix socket, sends requests via
raw socket connections, and verifies responses. Uses real JWT tokens,
real memory tools, and real socket connections — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import threading

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


@pytest.fixture()
def _short_sock_path():
    """Short socket path for macOS AF_UNIX 104-byte limit."""
    tmpdir = tempfile.mkdtemp(prefix="cvs")
    path = os.path.join(tmpdir, "s.sock")
    yield path
    if os.path.exists(path):
        os.unlink(path)
    if os.path.exists(tmpdir):
        os.rmdir(tmpdir)


@pytest.fixture()
def memory_server(_short_sock_path, tmp_path):
    """Start a ToolServer with memory tools on a background thread."""
    secret = _make_secret()
    db_path = tmp_path / "test_memory.sqlite"

    # Point memory config at temp DB
    old_db = os.environ.get("MEMORY_DB")
    old_config = os.environ.get("MEMORY_CONFIG")
    os.environ["MEMORY_DB"] = str(db_path)
    # Ensure no config file is required — MemoryConfig.from_file handles missing
    os.environ.pop("MEMORY_CONFIG", None)

    server = ToolServer(
        secret=secret,
        socket_path=_short_sock_path,
        module_configs={},
        agent_name="test",
        memory_domain="test",
    )

    loop = asyncio.new_event_loop()
    started = threading.Event()

    def _run():
        loop.run_until_complete(server.start())
        started.set()
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    started.wait(timeout=10)

    token = create_token(
        secret=secret,
        agent="test",
        modules=["memory"],
        ttl_seconds=3600,
    )

    yield _short_sock_path, secret, token

    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5)
    loop.run_until_complete(server.stop())
    loop.close()

    # Restore env
    if old_db is not None:
        os.environ["MEMORY_DB"] = old_db
    else:
        os.environ.pop("MEMORY_DB", None)
    if old_config is not None:
        os.environ["MEMORY_CONFIG"] = old_config


class TestToolServerLiveMemory:
    """Live integration tests using memory tools (always available)."""

    def test_memory_save_and_search(self, memory_server) -> None:
        """Save a memory, then search for it — full round trip."""
        sock_path, secret, token = memory_server

        # Save a memory
        save_result = _send_request(sock_path, {
            "tool": "memory_save",
            "params": {"content": "Integration test memory about corvus tool server", "visibility": "private"},
            "token": token,
        })
        assert save_result["ok"] is True, f"Save failed: {save_result}"

        # Search for it
        search_result = _send_request(sock_path, {
            "tool": "memory_search",
            "params": {"query": "corvus tool server"},
            "token": token,
        })
        assert search_result["ok"] is True, f"Search failed: {search_result}"
        assert "corvus tool server" in search_result["result"].lower()

    def test_unauthorized_module_rejected(self, memory_server) -> None:
        """Token scoped to memory cannot call obsidian tools."""
        sock_path, secret, token = memory_server

        result = _send_request(sock_path, {
            "tool": "obsidian_search",
            "params": {"query": "test"},
            "token": token,
        })
        assert result["ok"] is False
        assert "not_authorized" in result["error"]

    def test_wrong_secret_rejected(self, memory_server) -> None:
        """Token signed with wrong secret is rejected."""
        sock_path, secret, token = memory_server

        bad_token = create_token(
            secret=os.urandom(32),
            agent="test",
            modules=["memory"],
            ttl_seconds=3600,
        )

        result = _send_request(sock_path, {
            "tool": "memory_search",
            "params": {"query": "test"},
            "token": bad_token,
        })
        assert result["ok"] is False
        assert "auth_failed" in result["error"]

    def test_missing_token_rejected(self, memory_server) -> None:
        """Request without token is rejected."""
        sock_path, secret, token = memory_server

        result = _send_request(sock_path, {
            "tool": "memory_search",
            "params": {"query": "test"},
        })
        assert result["ok"] is False
        assert "missing_token" in result["error"]
