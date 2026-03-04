"""Behavioral tests for Ollama probe — real HTTP against real or absent Ollama.

Tests cover both model discovery and URL resolution with fallback.
"""

import pytest

from corvus.ollama_probe import (
    invalidate_cache,
    probe_ollama_models,
    resolve_ollama_url,
)

# ---------------------------------------------------------------------------
# probe_ollama_models
# ---------------------------------------------------------------------------


def test_probe_returns_empty_list_when_unreachable():
    """Probe should return empty list when Ollama is not running."""
    result = probe_ollama_models("http://localhost:99999")
    assert result == []


def test_probe_returns_empty_list_for_invalid_url():
    """Probe should handle invalid URLs gracefully."""
    result = probe_ollama_models("not-a-url")
    assert result == []


# ---------------------------------------------------------------------------
# resolve_ollama_url — fallback logic
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the probe cache before each test."""
    invalidate_cache()
    yield
    invalidate_cache()


def test_resolve_returns_none_when_all_unreachable():
    """Should return None when no candidate URL is reachable."""
    result = resolve_ollama_url(
        ["http://192.0.2.1:11434", "http://192.0.2.2:11434"],
        timeout=1.0,
    )
    assert result is None


def test_resolve_returns_first_reachable(httpx_responder):
    """Should return the first URL that responds, not necessarily the first in list."""
    # First URL is unreachable, second is reachable
    result = resolve_ollama_url(
        ["http://192.0.2.1:11434", httpx_responder],
        timeout=1.0,
    )
    assert result == httpx_responder


def test_resolve_caches_result(httpx_responder):
    """Second call should return cached result without re-probing."""
    url1 = resolve_ollama_url([httpx_responder], timeout=1.0)
    url2 = resolve_ollama_url([httpx_responder], timeout=1.0)
    assert url1 == url2 == httpx_responder


def test_resolve_force_bypasses_cache(httpx_responder):
    """force=True should re-probe even if cached."""
    resolve_ollama_url([httpx_responder], timeout=1.0)
    # Force re-probe — should still work
    result = resolve_ollama_url([httpx_responder], timeout=1.0, force=True)
    assert result == httpx_responder


def test_resolve_empty_list():
    """Empty candidate list should return None."""
    result = resolve_ollama_url([])
    assert result is None


# ---------------------------------------------------------------------------
# Fixture: lightweight HTTP responder for probe tests
# ---------------------------------------------------------------------------


@pytest.fixture
def httpx_responder():
    """Start a tiny HTTP server that responds to /api/version with 200."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/version":
                body = json.dumps({"version": "test"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress request logs in test output

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
