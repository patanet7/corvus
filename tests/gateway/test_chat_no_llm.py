"""Test WebSocket chat returns error when no LLM backend is configured.

NOTE: Uses monkeypatch.delenv() to clear real env vars — this is NOT mocking.
It modifies the actual process environment so the real _any_llm_configured()
check returns False. Acceptable under no-mocks policy.
"""

from fastapi.testclient import TestClient

from corvus.server import app


def test_chat_without_llm_returns_error(monkeypatch):
    """WebSocket chat should return no_llm_configured error when no LLM backend is set."""
    # Clear all LLM env vars
    llm_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_BASE_URL",
        "KIMI_BOT_TOKEN",
        "OPENAI_COMPAT_BASE_URL",
    ]
    for var in llm_vars:
        monkeypatch.delenv(var, raising=False)

    client = TestClient(app)
    with client.websocket_connect("/ws", headers={"X-Remote-User": "testuser"}) as ws:
        init = ws.receive_json()
        assert init.get("type") == "init"
        ws.send_json({"type": "chat", "message": "hello"})
        resp = ws.receive_json()
        assert resp.get("type") == "error"
        assert "no_llm_configured" in resp.get("error", "")


def test_any_llm_configured_returns_true_when_set(monkeypatch):
    """_any_llm_configured() should return True when any LLM env var is set."""
    from corvus.server import _any_llm_configured

    # Clear all first
    for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "KIMI_BOT_TOKEN", "OPENAI_COMPAT_BASE_URL"]:
        monkeypatch.delenv(var, raising=False)

    assert _any_llm_configured() is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert _any_llm_configured() is True


def test_any_llm_configured_returns_false_when_none_set(monkeypatch):
    """_any_llm_configured() should return False when no LLM env vars are set."""
    from corvus.server import _any_llm_configured

    for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "KIMI_BOT_TOKEN", "OPENAI_COMPAT_BASE_URL"]:
        monkeypatch.delenv(var, raising=False)

    assert _any_llm_configured() is False
