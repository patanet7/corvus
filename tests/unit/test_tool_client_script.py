"""Tests for the tool client library used by skill scripts.

Runs against a real Unix socket server — no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
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
        self, tool_client_module, monkeypatch
    ) -> None:
        """Client sends request over Unix socket and parses response."""
        secret = _make_secret()
        tmpdir = tempfile.mkdtemp(prefix="cvs")
        sock_path = os.path.join(tmpdir, "s.sock")
        token = create_token(
            secret=secret, agent="test", modules=["memory"], ttl_seconds=3600,
        )

        monkeypatch.setenv("CORVUS_TOOL_SOCKET", sock_path)
        monkeypatch.setenv("CORVUS_TOOL_TOKEN", token)

        # Start a minimal echo server that returns a canned response
        loop = asyncio.new_event_loop()
        started = threading.Event()

        async def _echo_handler(reader, writer):
            data = await reader.readline()
            req = json.loads(data.decode())
            response = {"ok": True, "result": {"echo": req["tool"]}}
            writer.write(json.dumps(response).encode())
            writer.close()

        def _run():
            server_coro = asyncio.start_unix_server(_echo_handler, path=sock_path)
            server = loop.run_until_complete(server_coro)
            started.set()
            loop.run_forever()
            server.close()
            loop.run_until_complete(server.wait_closed())

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        started.wait(timeout=5)

        try:
            result = tool_client_module.call_tool("memory_search", {"query": "test"})
            assert result["ok"] is True
            assert result["result"]["echo"] == "memory_search"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=5)
            loop.close()
            if os.path.exists(sock_path):
                os.unlink(sock_path)
            os.rmdir(tmpdir)

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
