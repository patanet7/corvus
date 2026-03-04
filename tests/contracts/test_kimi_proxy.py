"""Behavioral tests for KimiProxy translation layer.

Tests the message format translation without needing a real Kimi connection.
Uses a real FastAPI test client against a real KimiProxy app.
The KimiBridgeClient is replaced with a FakeBridge that records calls
and returns canned ACP responses -- this is NOT a mock, it's a real
object that implements the same interface with deterministic behavior.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from corvus.kimi_bridge import (
    AcpCapabilities,
    PromptResult,
    SessionInfo,
    SessionMode,
    SessionUpdate,
    SessionUpdateType,
    StopReason,
)


class FakeBridge:
    """Deterministic bridge that records calls and yields canned responses.

    This is a real object, not a mock. It implements the same interface
    as KimiBridgeClient but with predictable behavior for testing.
    """

    def __init__(self):
        self.initialized = False
        self.session_created = False
        self.prompts_sent: list[dict[str, Any]] = []
        self.connected = False
        self._canned_responses: list = []

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    async def initialize(self) -> AcpCapabilities:
        self.initialized = True
        return AcpCapabilities()

    async def create_session(self) -> SessionInfo:
        self.session_created = True
        return SessionInfo(
            session_id="agent:main:main",
            available_modes=[SessionMode(id="default", name="Default")],
        )

    def set_canned_responses(self, responses: list):
        """Set what send_prompt_stream will yield."""
        self._canned_responses = responses

    async def send_prompt_stream(self, session_id: str, text: str) -> AsyncIterator:
        self.prompts_sent.append({"session_id": session_id, "text": text})
        for item in self._canned_responses:
            yield item


@pytest.fixture
def fake_bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def proxy_app(fake_bridge: FakeBridge):
    from corvus.kimi_proxy import create_proxy_app

    return create_proxy_app(bridge=fake_bridge)


@pytest.fixture
def client(proxy_app) -> TestClient:
    return TestClient(proxy_app)


def test_health_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_messages_endpoint_returns_streaming_response(client: TestClient, fake_bridge: FakeBridge):
    """POST /v1/messages with stream=true returns SSE."""
    fake_bridge.set_canned_responses(
        [
            SessionUpdate(
                session_id="agent:main:main",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK.value,
                content={"type": "text", "text": "Hello from K2!"},
            ),
            PromptResult(
                stop_reason=StopReason.END_TURN,
            ),
        ]
    )

    resp = client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    # Parse SSE events
    events = []
    for line in resp.text.strip().split("\n"):
        if line.startswith("data: "):
            data = line[6:]
            if data != "[DONE]":
                events.append(json.loads(data))

    # Should have at least a content_block_delta and message_stop
    event_types = [e.get("type") for e in events]
    assert "content_block_delta" in event_types or "message_start" in event_types


def test_messages_records_prompt(client: TestClient, fake_bridge: FakeBridge):
    """Verify the prompt text is forwarded to the bridge."""
    fake_bridge.set_canned_responses(
        [
            PromptResult(
                stop_reason=StopReason.END_TURN,
            ),
        ]
    )

    client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "stream": True,
        },
    )

    assert len(fake_bridge.prompts_sent) == 1
    assert "2+2" in fake_bridge.prompts_sent[0]["text"]


def test_messages_non_streaming_returns_json(client: TestClient, fake_bridge: FakeBridge):
    """POST /v1/messages without stream returns complete JSON."""
    fake_bridge.set_canned_responses(
        [
            SessionUpdate(
                session_id="agent:main:main",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK.value,
                content={"type": "text", "text": "The answer is 4."},
            ),
            PromptResult(
                stop_reason=StopReason.END_TURN,
            ),
        ]
    )

    resp = client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "What is 2+2?"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "message"
    assert body["stop_reason"] == "end_turn"
    assert any("4" in c.get("text", "") for c in body["content"])


def test_system_prompt_included_in_text(client: TestClient, fake_bridge: FakeBridge):
    """System prompt from the Anthropic request is prepended to prompt text."""
    fake_bridge.set_canned_responses(
        [
            PromptResult(stop_reason=StopReason.END_TURN),
        ]
    )

    client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "system": "You are a math tutor.",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "stream": True,
        },
    )

    assert len(fake_bridge.prompts_sent) == 1
    prompt = fake_bridge.prompts_sent[0]["text"]
    assert "math tutor" in prompt
    assert "2+2" in prompt


def test_multi_turn_messages_concatenated(client: TestClient, fake_bridge: FakeBridge):
    """Multiple messages are concatenated into a single prompt string."""
    fake_bridge.set_canned_responses(
        [
            PromptResult(stop_reason=StopReason.END_TURN),
        ]
    )

    client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "How are you?"},
            ],
            "stream": True,
        },
    )

    assert len(fake_bridge.prompts_sent) == 1
    prompt = fake_bridge.prompts_sent[0]["text"]
    assert "Hello" in prompt
    assert "How are you?" in prompt


def test_streaming_sse_event_sequence(client: TestClient, fake_bridge: FakeBridge):
    """Verify the full SSE event sequence: message_start, block_start, deltas, block_stop, message_delta, message_stop."""
    fake_bridge.set_canned_responses(
        [
            SessionUpdate(
                session_id="agent:main:main",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK.value,
                content={"type": "text", "text": "chunk1"},
            ),
            SessionUpdate(
                session_id="agent:main:main",
                update_type=SessionUpdateType.AGENT_MESSAGE_CHUNK.value,
                content={"type": "text", "text": "chunk2"},
            ),
            PromptResult(stop_reason=StopReason.END_TURN),
        ]
    )

    resp = client.post(
        "/v1/messages",
        json={
            "model": "kimi-k2",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        },
    )

    events = []
    for line in resp.text.strip().split("\n"):
        if line.startswith("data: "):
            data = line[6:]
            if data != "[DONE]":
                events.append(json.loads(data))

    event_types = [e["type"] for e in events]
    assert event_types[0] == "message_start"
    assert event_types[1] == "content_block_start"
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert event_types[-1] == "message_stop"

    # Check deltas contain the text chunks
    deltas = [e for e in events if e["type"] == "content_block_delta"]
    delta_texts = [d["delta"]["text"] for d in deltas]
    assert "chunk1" in delta_texts
    assert "chunk2" in delta_texts
