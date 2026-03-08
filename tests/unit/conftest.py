"""Shared fixtures for unit tests."""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading

import pytest

from corvus.cli.tool_server import ToolServer


@pytest.fixture()
def short_sock_path():
    """Provide a short socket path that fits macOS 104-byte AF_UNIX limit."""
    tmpdir = tempfile.mkdtemp(prefix="cvs")
    path = os.path.join(tmpdir, "s.sock")
    yield path
    if os.path.exists(path):
        os.unlink(path)
    if os.path.exists(tmpdir):
        os.rmdir(tmpdir)


@pytest.fixture()
def server_ctx(short_sock_path):
    """Start a ToolServer on a background event loop, yield (sock_path, secret), then stop."""
    secret = os.urandom(32)
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
