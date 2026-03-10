"""Test /health endpoint reports backend status."""

import pytest
from fastapi.testclient import TestClient

from corvus.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_includes_backends_key(client):
    """Health response should include a backends dict."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "backends" in data


def test_health_lists_all_backend_names(client):
    """Health should report status for all known backends."""
    resp = client.get("/health")
    data = resp.json()
    backends = data["backends"]
    for name in ("claude", "openai", "ollama", "kimi", "openai_compat"):
        assert name in backends


def test_health_backend_status_values(client):
    """Each backend should report either configured or not_configured."""
    resp = client.get("/health")
    data = resp.json()
    for _name, info in data["backends"].items():
        assert info["status"] in ("configured", "not_configured")


def test_health_overall_status_degraded_when_no_llm(client, monkeypatch):
    """Status should be degraded when no LLM env vars are set."""
    llm_vars = [
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "OLLAMA_BASE_URL",
        "KIMI_BOT_TOKEN",
        "OPENAI_COMPAT_BASE_URL",
    ]
    for var in llm_vars:
        monkeypatch.delenv(var, raising=False)

    resp = client.get("/health")
    data = resp.json()
    assert data["status"] == "degraded"
