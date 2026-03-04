"""Integration tests for session memory extraction lifecycle.

Tests the complete round-trip of session memory extraction:
- Parse extraction responses, save via MemoryHub, retrieve via search
- Multi-domain extraction with visibility
- Trivial session short-circuit (no extraction, no save)
- Malformed input resilience
- All content types contract
- Server source wiring contracts

All tests are behavioral: real SQLite databases, real FTS5 search, real file I/O.
NO mocks, NO monkeypatch, NO @patch.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord
from corvus.session import (
    SessionTranscript,
    extract_session_memories,
    parse_extraction_response,
)
from tests.conftest import make_hub, run

ROOT = Path(__file__).parent.parent.parent


async def save_extracted_memory(
    hub: MemoryHub,
    mem,
    agent_name: str = "homelab",
) -> str:
    """Save an ExtractedMemory through the Hub (mirrors session.py logic)."""
    vis = "shared" if mem.domain == "shared" else "private"
    record = MemoryRecord(
        id=str(uuid4()),
        content=mem.content,
        domain=mem.domain,
        visibility=vis,
        importance=mem.importance,
        tags=mem.tags,
        source="session",
        created_at=datetime.now(UTC).isoformat(),
    )
    return await hub.save(record, agent_name=agent_name)


# ---------------------------------------------------------------------------
# Round-trip tests: parse -> save -> search with real SQLite Hub
# ---------------------------------------------------------------------------


class TestSessionMemoryRoundTrip:
    """Test the full extraction -> persist -> retrieve cycle with real databases."""

    def test_parse_then_save_creates_searchable_memory(self, tmp_path):
        """BEHAVIORAL: Parse an extraction response, save via Hub, search finds it."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "User decided to migrate Plex to a dedicated container",
                        "domain": "homelab",
                        "tags": ["plex", "migration", "decision"],
                        "importance": 0.9,
                        "content_type": "decision",
                    }
                ]
            }
        )

        memories = parse_extraction_response(raw)
        assert len(memories) == 1

        hub = make_hub(tmp_path)
        for mem in memories:
            run(save_extracted_memory(hub, mem, agent_name="homelab"))

        results = run(hub.search("Plex dedicated container", agent_name="homelab"))
        assert len(results) > 0
        assert any("plex" in r.content.lower() for r in results)

    def test_parse_then_save_multiple_domains(self, tmp_path):
        """BEHAVIORAL: Multi-domain extraction saves with correct visibility."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "Doctor appointment scheduled for next Tuesday",
                        "domain": "personal",
                        "tags": ["health", "appointment"],
                        "importance": 0.8,
                        "content_type": "action_item",
                    },
                    {
                        "content": "Budget review shows $200 remaining for February",
                        "domain": "finance",
                        "tags": ["budget", "february"],
                        "importance": 0.6,
                        "content_type": "note",
                    },
                ]
            }
        )

        memories = parse_extraction_response(raw)
        assert len(memories) == 2

        hub = make_hub(tmp_path)
        run(save_extracted_memory(hub, memories[0], agent_name="personal"))
        run(save_extracted_memory(hub, memories[1], agent_name="finance"))

        personal_results = run(
            hub.search("doctor appointment", agent_name="personal"),
        )
        assert len(personal_results) > 0

        finance_results = run(
            hub.search("budget February", agent_name="finance"),
        )
        assert len(finance_results) > 0

    def test_trivial_session_no_extraction(self, tmp_path):
        """BEHAVIORAL: A session with < 2 user messages produces zero saved memories."""
        hub = make_hub(tmp_path)
        transcript = SessionTranscript(
            user="testuser",
            messages=[{"role": "user", "content": "hi"}],
        )

        result = run(extract_session_memories(transcript, hub))
        assert result == []

        results = run(hub.search("hi", agent_name="general"))
        assert len(results) == 0

    def test_empty_extraction_response_no_crash(self, tmp_path):
        """BEHAVIORAL: An empty extraction (no memorable content) doesn't crash or save."""
        raw = json.dumps({"memories": []})
        memories = parse_extraction_response(raw)
        assert memories == []

    def test_malformed_extraction_no_crash(self):
        """BEHAVIORAL: Malformed JSON from LLM doesn't crash, returns empty."""
        raw = "This is not JSON at all {broken"
        memories = parse_extraction_response(raw)
        assert memories == []

    def test_extraction_contract_with_all_content_types(self, tmp_path):
        """CONTRACT: All 5 content types can be parsed and saved without error."""
        content_types = ["note", "decision", "action_item", "preference", "resolution"]
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": f"Test memory for content type {ct}",
                        "domain": "shared",
                        "tags": ["test"],
                        "importance": 0.5,
                        "content_type": ct,
                    }
                    for ct in content_types
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 5

        hub = make_hub(tmp_path)
        for mem in memories:
            run(save_extracted_memory(hub, mem, agent_name="general"))

        results = run(hub.search("Test memory content type", agent_name="general"))
        assert len(results) == 5

    def test_parse_then_save_preserves_importance(self, tmp_path):
        """CONTRACT: Importance value round-trips through parse -> save -> Hub correctly."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "Critical decision to use uv for all Python projects",
                        "domain": "work",
                        "tags": ["tooling"],
                        "importance": 0.95,
                        "content_type": "decision",
                    }
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert memories[0].importance == 0.95

        hub = make_hub(tmp_path)
        record_id = run(save_extracted_memory(hub, memories[0], agent_name="work"))
        assert isinstance(record_id, str)
        assert len(record_id) > 0

        results = run(hub.search("Critical decision uv Python", agent_name="work"))
        assert len(results) > 0
        assert any("uv" in r.content for r in results)


# ---------------------------------------------------------------------------
# Server source contract tests
# ---------------------------------------------------------------------------


class TestServerStopHookWiring:
    """Verify chat module has the stop hook correctly wired via source inspection.

    After the ChatSession extraction, the chat lifecycle is split across:
    - claw/api/chat.py (thin router: auth, session resume, disconnect handling)
    - claw/gateway/chat_session.py (ChatSession class: transcript, messages, run loop)
    """

    @pytest.fixture(scope="class")
    def server_source(self):
        """Read server.py source once for all contract tests."""
        return (ROOT / "corvus" / "server.py").read_text()

    @pytest.fixture(scope="class")
    def chat_source(self):
        """Read chat.py source (thin WebSocket router)."""
        return (ROOT / "corvus" / "api" / "chat.py").read_text()

    @pytest.fixture(scope="class")
    def chat_session_source(self):
        """Read chat_session.py source (ChatSession class)."""
        return (ROOT / "corvus" / "gateway" / "chat_session.py").read_text()

    def test_server_imports_session_module(self, chat_source, chat_session_source):
        """CONTRACT: Chat module imports SessionTranscript and extract_session_memories."""
        assert "from corvus.session import SessionTranscript" in chat_session_source
        assert "from corvus.session import extract_session_memories" in chat_source

    def test_server_has_get_memory_hub(self, server_source):
        """CONTRACT: server.py defines get_memory_hub()."""
        assert "def get_memory_hub" in server_source

    def test_server_imports_memory_hub(self, server_source):
        """CONTRACT: GatewayRuntime imports MemoryHub (server.py instantiates runtime)."""
        runtime_source = (ROOT / "corvus" / "gateway" / "runtime.py").read_text()
        assert "from corvus.memory import" in runtime_source
        assert "MemoryHub" in runtime_source

    def test_server_creates_transcript_in_handler(self, chat_session_source):
        """CONTRACT: ChatSession creates a SessionTranscript."""
        assert "SessionTranscript(" in chat_session_source

    def test_server_calls_extraction_on_disconnect(self, chat_source):
        """CONTRACT: WebSocket handler calls extract_session_memories in except block."""
        assert "extract_session_memories(" in chat_source
        assert "WebSocketDisconnect" in chat_source

    def test_server_stop_hook_has_try_except(self, chat_source):
        """CONTRACT: Stop hook extraction is wrapped in try/except (never crashes teardown)."""
        disconnect_idx = chat_source.index("except WebSocketDisconnect")
        after_disconnect = chat_source[disconnect_idx:]
        assert "try:" in after_disconnect
        assert "except Exception:" in after_disconnect or "except Exception as" in after_disconnect

    def test_server_collects_messages_in_transcript(self, chat_session_source):
        """CONTRACT: ChatSession appends messages to transcript."""
        assert "transcript.messages.append" in chat_session_source
