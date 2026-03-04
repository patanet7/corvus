"""Behavioral tests for claw.session -- session transcript and memory extraction.

All tests are behavioral: real objects, real parsing, real SQLite databases.
NO mocks, NO monkeypatch, NO @patch.
"""

import json
from datetime import UTC, datetime

from corvus.session import (
    EXTRACTION_SYSTEM_PROMPT,
    VALID_CONTENT_TYPES,
    VALID_DOMAINS,
    ExtractedMemory,
    SessionTranscript,
    extract_session_memories,
    parse_extraction_response,
)
from tests.conftest import make_hub, run

# ---------------------------------------------------------------------------
# SessionTranscript tests
# ---------------------------------------------------------------------------


class TestSessionTranscript:
    """Tests for SessionTranscript data collection and formatting."""

    def test_transcript_message_count(self):
        """message_count() counts only user messages, not assistant responses."""
        t = SessionTranscript(user="alice")
        t.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm fine!"},
            {"role": "user", "content": "Great"},
        ]
        assert t.message_count() == 3

    def test_transcript_to_text(self):
        """to_text() produces readable USER:/ASSISTANT: format."""
        t = SessionTranscript(user="bob")
        t.messages = [
            {"role": "user", "content": "What is Docker?"},
            {"role": "assistant", "content": "Docker is a container platform."},
        ]
        text = t.to_text()
        assert "USER: What is Docker?" in text
        assert "ASSISTANT: Docker is a container platform." in text
        # Messages separated by double newlines
        assert "\n\n" in text

    def test_transcript_truncation(self):
        """Long transcripts truncate from the beginning, keeping recent context."""
        t = SessionTranscript(user="charlie")
        # Create messages that exceed the max_chars limit
        for i in range(100):
            t.messages.append({"role": "user", "content": f"Message number {i} with some extra text to pad it out"})
            t.messages.append({"role": "assistant", "content": f"Response number {i} with additional padding text"})

        text = t.to_text(max_chars=500)
        # Should have truncation marker at the start
        assert text.startswith("...[earlier messages truncated]...")
        marker = "...[earlier messages truncated]...\n\n"
        # Tail is at most max_chars (may be shorter due to newline-boundary trim)
        tail = text[len(marker) :]
        assert len(tail) <= 500
        # Most recent messages should be preserved
        assert "Message number 99" in text or "Response number 99" in text

    def test_empty_transcript(self):
        """Empty transcript gives empty text and 0 message count."""
        t = SessionTranscript(user="dave")
        assert t.message_count() == 0
        assert t.to_text() == ""


# ---------------------------------------------------------------------------
# Primary agent tracking tests
# ---------------------------------------------------------------------------


class TestPrimaryAgent:
    """Tests for agent_counts tracking and primary_agent() resolution."""

    def test_primary_agent_single(self):
        """primary_agent() returns the most-used agent by count."""
        t = SessionTranscript(user="t", session_id="s", messages=[], started_at=datetime.now(UTC))
        t.record_agent("personal")
        t.record_agent("personal")
        t.record_agent("work")
        assert t.primary_agent() == "personal"

    def test_primary_agent_empty(self):
        """primary_agent() falls back to 'general' when no agents recorded."""
        t = SessionTranscript(user="t", session_id="s", messages=[], started_at=datetime.now(UTC))
        assert t.primary_agent() == "general"

    def test_record_agent_updates_both(self):
        """record_agent() updates both agents_used set and agent_counts dict."""
        t = SessionTranscript(user="t", session_id="s", messages=[], started_at=datetime.now(UTC))
        t.record_agent("work")
        assert "work" in t.agents_used
        assert t.agent_counts["work"] == 1

    def test_record_agent_increments_count(self):
        """Multiple record_agent() calls increment the count correctly."""
        t = SessionTranscript(user="t", session_id="s", messages=[], started_at=datetime.now(UTC))
        t.record_agent("homelab")
        t.record_agent("homelab")
        t.record_agent("homelab")
        assert t.agent_counts["homelab"] == 3
        assert t.primary_agent() == "homelab"

    def test_primary_agent_tie_breaks_deterministically(self):
        """When counts are tied, max() returns one deterministically."""
        t = SessionTranscript(user="t", session_id="s", messages=[], started_at=datetime.now(UTC))
        t.record_agent("work")
        t.record_agent("personal")
        # Both have count 1, max() picks one — just verify it's one of the two
        assert t.primary_agent() in {"work", "personal"}


# ---------------------------------------------------------------------------
# ExtractedMemory tests
# ---------------------------------------------------------------------------


class TestExtractedMemory:
    """Tests for the ExtractedMemory dataclass."""

    def test_extracted_memory_dataclass(self):
        """All fields are accessible and store correct values."""
        mem = ExtractedMemory(
            content="User prefers dark mode for all editors",
            domain="personal",
            tags=["preference", "ui"],
            importance=0.4,
            content_type="preference",
        )
        assert mem.content == "User prefers dark mode for all editors"
        assert mem.domain == "personal"
        assert mem.tags == ["preference", "ui"]
        assert mem.importance == 0.4
        assert mem.content_type == "preference"


# ---------------------------------------------------------------------------
# parse_extraction_response tests
# ---------------------------------------------------------------------------


class TestParseExtractionResponse:
    """Tests for LLM response parsing — the core validation/sanitization logic."""

    def test_parse_valid_extraction(self):
        """Valid JSON with memories parses into ExtractedMemory objects correctly."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "User decided to use PostgreSQL for the new project",
                        "domain": "work",
                        "tags": ["database", "decision"],
                        "importance": 0.9,
                        "content_type": "decision",
                    },
                    {
                        "content": "Firewall rules updated for port 8443",
                        "domain": "homelab",
                        "tags": ["network", "security"],
                        "importance": 0.7,
                        "content_type": "note",
                    },
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 2
        assert memories[0].content == "User decided to use PostgreSQL for the new project"
        assert memories[0].domain == "work"
        assert memories[0].tags == ["database", "decision"]
        assert memories[0].importance == 0.9
        assert memories[0].content_type == "decision"
        assert memories[1].domain == "homelab"

    def test_parse_empty_extraction(self):
        """An empty memories array returns an empty list."""
        raw = json.dumps({"memories": []})
        memories = parse_extraction_response(raw)
        assert memories == []

    def test_parse_malformed_json(self):
        """Non-JSON input returns an empty list without raising."""
        memories = parse_extraction_response("not json at all {{{")
        assert memories == []

    def test_parse_rejects_invalid_domain(self):
        """Invalid domain is remapped to 'shared'."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "Some fact about cooking",
                        "domain": "cooking",
                        "tags": [],
                        "importance": 0.5,
                        "content_type": "note",
                    }
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 1
        assert memories[0].domain == "shared"

    def test_parse_clamps_importance(self):
        """importance values outside [0.0, 1.0] are clamped."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "Very important thing",
                        "domain": "work",
                        "tags": [],
                        "importance": 5.0,
                        "content_type": "note",
                    },
                    {
                        "content": "Negative importance thing",
                        "domain": "work",
                        "tags": [],
                        "importance": -0.5,
                        "content_type": "note",
                    },
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 2
        assert memories[0].importance == 1.0
        assert memories[1].importance == 0.0

    def test_parse_missing_content_skipped(self):
        """Memory items with empty or missing content are skipped."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "",
                        "domain": "work",
                        "tags": [],
                        "importance": 0.5,
                        "content_type": "note",
                    },
                    {
                        "domain": "work",
                        "tags": [],
                        "importance": 0.5,
                        "content_type": "note",
                    },
                    {
                        "content": "   ",
                        "domain": "work",
                        "tags": [],
                        "importance": 0.5,
                        "content_type": "note",
                    },
                    {
                        "content": "This one is valid",
                        "domain": "work",
                        "tags": [],
                        "importance": 0.5,
                        "content_type": "note",
                    },
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 1
        assert memories[0].content == "This one is valid"

    def test_parse_invalid_content_type_remapped(self):
        """Unknown content_type is remapped to 'note'."""
        raw = json.dumps(
            {
                "memories": [
                    {
                        "content": "Some fact",
                        "domain": "personal",
                        "tags": ["test"],
                        "importance": 0.5,
                        "content_type": "banana",
                    }
                ]
            }
        )
        memories = parse_extraction_response(raw)
        assert len(memories) == 1
        assert memories[0].content_type == "note"

    def test_parse_max_five_memories(self):
        """More than 5 memories are truncated to exactly 5."""
        items = [
            {
                "content": f"Memory number {i}",
                "domain": "work",
                "tags": [],
                "importance": 0.5,
                "content_type": "note",
            }
            for i in range(10)
        ]
        raw = json.dumps({"memories": items})
        memories = parse_extraction_response(raw)
        assert len(memories) == 5
        # The first 5 should be kept (truncation from the end)
        assert memories[0].content == "Memory number 0"
        assert memories[4].content == "Memory number 4"

    def test_parse_missing_memories_key(self):
        """JSON without 'memories' key returns an empty list."""
        raw = json.dumps({"other": True, "data": [1, 2, 3]})
        memories = parse_extraction_response(raw)
        assert memories == []

    def test_parse_strips_markdown_code_fences(self):
        """JSON wrapped in ```json ... ``` fences is parsed correctly."""
        inner = json.dumps(
            {
                "memories": [
                    {
                        "content": "Deployed new Grafana dashboard",
                        "domain": "homelab",
                        "tags": ["grafana"],
                        "importance": 0.7,
                        "content_type": "note",
                    }
                ]
            }
        )
        # LLMs sometimes wrap JSON in markdown code fences
        raw = f"```json\n{inner}\n```"
        memories = parse_extraction_response(raw)
        assert len(memories) == 1
        assert memories[0].content == "Deployed new Grafana dashboard"
        assert memories[0].domain == "homelab"

    def test_parse_strips_plain_code_fences(self):
        """JSON wrapped in ``` ... ``` (no language tag) is also handled."""
        inner = json.dumps(
            {
                "memories": [
                    {
                        "content": "User prefers vim keybindings",
                        "domain": "personal",
                        "tags": ["editor"],
                        "importance": 0.4,
                        "content_type": "preference",
                    }
                ]
            }
        )
        raw = f"```\n{inner}\n```"
        memories = parse_extraction_response(raw)
        assert len(memories) == 1
        assert memories[0].content == "User prefers vim keybindings"


# ---------------------------------------------------------------------------
# EXTRACTION_SYSTEM_PROMPT tests
# ---------------------------------------------------------------------------


class TestExtractionPrompt:
    """Tests that the extraction prompt contains required structural elements."""

    def test_extraction_prompt_structure(self):
        """Prompt contains required schema fields: memories, domain, importance, content_type."""
        assert "memories" in EXTRACTION_SYSTEM_PROMPT
        assert "domain" in EXTRACTION_SYSTEM_PROMPT
        assert "importance" in EXTRACTION_SYSTEM_PROMPT
        assert "content_type" in EXTRACTION_SYSTEM_PROMPT

    def test_extraction_prompt_limits(self):
        """Prompt contains the maximum 5 memories instruction."""
        assert "5" in EXTRACTION_SYSTEM_PROMPT
        # More specific check
        assert "Maximum 5 memories" in EXTRACTION_SYSTEM_PROMPT

    def test_extraction_prompt_security(self):
        """Prompt instructs the LLM to exclude credentials."""
        prompt_lower = EXTRACTION_SYSTEM_PROMPT.lower()
        assert "password" in prompt_lower or "credential" in prompt_lower
        # Check it's an exclusion instruction, not an inclusion
        assert "do not include" in prompt_lower


# ---------------------------------------------------------------------------
# VALID_DOMAINS / VALID_CONTENT_TYPES sanity checks
# ---------------------------------------------------------------------------


class TestConstants:
    """Sanity checks on module-level constants."""

    def test_valid_domains_contains_expected(self):
        """VALID_DOMAINS has all agent domains (minus general) + shared."""
        expected = {"personal", "work", "homelab", "finance", "email", "docs", "music", "home", "shared"}
        assert VALID_DOMAINS == expected

    def test_valid_domains_excludes_general(self):
        """VALID_DOMAINS excludes 'general' — cross-domain memories use actual domain or 'shared'."""
        assert "general" not in VALID_DOMAINS

    def test_valid_content_types_contains_expected(self):
        """VALID_CONTENT_TYPES has all documented types."""
        expected = {"note", "decision", "action_item", "preference", "resolution"}
        assert VALID_CONTENT_TYPES == expected


# ---------------------------------------------------------------------------
# extract_session_memories — trivial session short-circuit tests
# ---------------------------------------------------------------------------


class TestExtractSessionMemories:
    """Tests for the extract_session_memories async function.

    These tests verify short-circuit behavior for trivial sessions.
    They use real SQLite databases (no mocks) but do NOT require an API key
    because the function returns early before making any LLM call.
    """

    def test_extraction_skips_trivial_sessions(self, tmp_path):
        """Sessions with fewer than 2 user messages return [] without LLM call."""
        hub = make_hub(tmp_path)

        # Zero user messages
        t0 = SessionTranscript(user="alice")
        result0 = run(extract_session_memories(t0, hub))
        assert result0 == []

        # One user message (below threshold)
        t1 = SessionTranscript(user="alice")
        t1.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result1 = run(extract_session_memories(t1, hub))
        assert result1 == []

    def test_extraction_skips_empty_transcript(self, tmp_path):
        """Empty transcript returns [] without LLM call."""
        hub = make_hub(tmp_path)

        t = SessionTranscript(user="bob")
        # No messages at all
        result = run(extract_session_memories(t, hub))
        assert result == []

    def test_extraction_uses_primary_agent(self, tmp_path):
        """extract_session_memories uses transcript.primary_agent() by default."""
        hub = make_hub(tmp_path)

        t = SessionTranscript(user="alice")
        t.messages = [
            {"role": "user", "content": "Check my server status"},
            {"role": "assistant", "content": "Your servers are all up."},
            {"role": "user", "content": "What about backups?"},
            {"role": "assistant", "content": "Backups completed at 3am."},
        ]
        t.record_agent("homelab")
        t.record_agent("homelab")
        t.record_agent("work")

        # Provide a fake extractor that returns a valid extraction JSON
        async def fake_extractor(system_prompt: str, user_message: str) -> str:
            return json.dumps(
                {
                    "memories": [
                        {
                            "content": "All servers are healthy, backups ran at 3am",
                            "domain": "homelab",
                            "tags": ["server", "backup"],
                            "importance": 0.7,
                            "content_type": "note",
                        }
                    ]
                }
            )

        # Call WITHOUT explicit agent_name — should use primary_agent()
        result = run(extract_session_memories(t, hub, llm_extractor=fake_extractor))
        assert len(result) == 1
        assert result[0].domain == "homelab"
        # Verify primary_agent was "homelab" (not "general")
        assert t.primary_agent() == "homelab"
