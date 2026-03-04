"""LIVE integration tests for RouterAgent against a real Ollama model.

NO mocks. Real HTTP requests to a real Ollama instance running locally.
Tests verify that the routing pipeline actually classifies user intent
correctly using a local LLM via the Anthropic-compatible Messages API.

Requires:
    - Ollama running on localhost:11434
    - qwen3-coder:30b model pulled
    - Env: ANTHROPIC_BASE_URL=http://localhost:11434
           ANTHROPIC_API_KEY=ollama
           ROUTER_MODEL=qwen3-coder:30b

Run: ANTHROPIC_BASE_URL=http://localhost:11434 ANTHROPIC_API_KEY=ollama \
     ROUTER_MODEL=qwen3-coder:30b uv run pytest tests/integration/test_routing_live.py -v
"""

import asyncio
import os

import pytest
import requests

from corvus.router import VALID_AGENTS, RouterAgent

OLLAMA_URL = os.environ.get("ANTHROPIC_BASE_URL", "http://localhost:11434")


def _ollama_available() -> bool:
    """Check if Ollama is running and has the required model."""
    try:
        resp = requests.get(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        models = [m["name"] for m in resp.json().get("models", [])]
        return any("qwen3-coder" in m for m in models)
    except (requests.ConnectionError, requests.Timeout):
        return False


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running or qwen3-coder model not available",
)


@pytest.fixture()
def router() -> RouterAgent:
    """Create a RouterAgent configured for Ollama."""
    return RouterAgent(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "ollama"),
        model=os.environ.get("ROUTER_MODEL", "qwen3-coder:30b"),
    )


# ---------------------------------------------------------------------------
# Core routing tests — does the model actually pick the right agent?
# ---------------------------------------------------------------------------


@skip_no_ollama
class TestRoutingClassification:
    """Each test sends a real message to a real LLM and verifies the result."""

    def test_personal_todo(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Check my todo list for today"))
        assert result == "personal"

    def test_homelab_docker(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Deploy the new Docker container on optiplex"))
        assert result == "homelab"

    def test_finance_spending(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("How much did I spend on groceries last month?"))
        assert result == "finance"

    def test_home_lights(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Turn off the living room lights"))
        assert result == "home"

    def test_email_inbox(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("What emails do I have from yesterday?"))
        assert result == "email"

    def test_music_practice(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Help me practice Chopin nocturne"))
        assert result == "music"

    def test_docs_paperless(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Find my tax documents in Paperless"))
        assert result == "docs"

    def test_work_report(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Review the quarterly report for the team"))
        assert result == "work"


# ---------------------------------------------------------------------------
# Edge cases — ambiguous messages, fallback behavior
# ---------------------------------------------------------------------------


@skip_no_ollama
class TestRoutingEdgeCases:
    """Test ambiguous or tricky routing scenarios."""

    def test_general_fallback_for_greeting(self, router: RouterAgent) -> None:
        """Simple greetings should route to general."""
        result = asyncio.run(router.classify("Hello, how are you?"))
        assert result == "general"

    def test_result_always_valid_agent(self, router: RouterAgent) -> None:
        """No matter the input, result must be a valid agent name."""
        messages = [
            "What's the weather like?",
            "Tell me a joke",
            "asdfghjkl random gibberish",
            "",
        ]
        for msg in messages:
            result = asyncio.run(router.classify(msg))
            assert result in VALID_AGENTS, f"Invalid agent '{result}' for message: {msg}"

    def test_classify_returns_string(self, router: RouterAgent) -> None:
        result = asyncio.run(router.classify("Check my email"))
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# System contract tests — verify router + Ollama integration plumbing
# ---------------------------------------------------------------------------


@skip_no_ollama
class TestOllamaIntegration:
    """Verify the Ollama ↔ Anthropic SDK bridge works correctly."""

    def test_ollama_health(self) -> None:
        """Ollama is running and responsive."""
        resp = requests.get(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=5)
        assert resp.status_code == 200

    def test_ollama_has_model(self) -> None:
        """qwen3-coder model is available."""
        resp = requests.get(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        assert any("qwen3-coder" in m for m in models), f"Available models: {models}"

    def test_anthropic_messages_api_works(self) -> None:
        """Ollama's Anthropic-compatible endpoint responds correctly."""
        resp = requests.post(
            f"{OLLAMA_URL.rstrip('/')}/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": "ollama"},
            json={
                "model": os.environ.get("ROUTER_MODEL", "qwen3-coder:30b"),
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            timeout=60,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "message"
        assert len(data["content"]) > 0
        assert data["content"][0]["type"] == "text"
