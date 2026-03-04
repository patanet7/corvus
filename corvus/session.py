"""Session transcript collection and memory extraction for the stop hook.

Collects messages during a WebSocket chat session. On disconnect, uses a
one-shot LLM call to extract key facts worth remembering. Extracted memories
are persisted to both the Obsidian vault and SQLite FTS5 index via MemoryEngine.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from anthropic import AsyncAnthropic

from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord

# Type alias for the LLM extraction callable.
# Signature: (system_prompt: str, user_message: str) -> raw_text_response
LLMExtractor = Callable[[str, str], Awaitable[str]]

logger = logging.getLogger("corvus-gateway")

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

# Module-level client — reused across extraction calls to avoid per-call setup overhead
_anthropic_client: AsyncAnthropic | None = None


def _get_anthropic_client() -> AsyncAnthropic:
    """Return a module-level AsyncAnthropic client, creating it on first use."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic()
    return _anthropic_client


# Validation allowlist for LLM extraction output — matches agent YAML specs
# in config/agents/. "general" excluded: cross-domain queries get tagged by
# actual domain. Update this set when adding new agent domains.
VALID_DOMAINS = {
    "personal",
    "work",
    "homelab",
    "finance",
    "email",
    "docs",
    "music",
    "home",
    "shared",
}
VALID_CONTENT_TYPES = {"note", "decision", "action_item", "preference", "resolution"}


EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction system. Given a
conversation transcript, extract key facts worth remembering for future sessions.

Return a JSON object with this exact schema:
{
  "memories": [
    {
      "content": "The fact or decision to remember (1-3 sentences)",
      "domain": "personal|work|homelab|finance|email|docs|music|home|shared",
      "tags": ["tag1", "tag2"],
      "importance": 0.1-1.0,
      "content_type": "note|decision|action_item|preference|resolution"
    }
  ]
}

Rules:
- Extract ONLY facts that would be useful in future conversations
- Decisions made, action items created, preferences stated, problems resolved
- Do NOT extract: greetings, small talk, questions that were fully answered,
  raw data that was just displayed
- Do NOT include: passwords, API keys, tokens, or any credential-like strings
- If the conversation had no memorable content, return {"memories": []}
- importance: 0.9+ for decisions/action items, 0.5-0.8 for facts, 0.3-0.4 for preferences
- domain: use "shared" only when the fact truly spans multiple domains
- content_type: "decision" for choices made, "action_item" for TODOs,
  "preference" for user preferences, "resolution" for solved problems,
  "note" for everything else
- Maximum 5 memories per session -- be selective
"""


@dataclass
class SessionTranscript:
    """Collects messages during a chat session for stop-hook extraction."""

    user: str
    session_id: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    agents_used: set[str] = field(default_factory=set)
    tool_count: int = 0
    agent_counts: dict[str, int] = field(default_factory=dict)

    def record_agent(self, agent_name: str) -> None:
        """Record an agent being used in this session."""
        self.agents_used.add(agent_name)
        self.agent_counts[agent_name] = self.agent_counts.get(agent_name, 0) + 1

    def primary_agent(self) -> str:
        """Return the most-used agent in this session."""
        if not self.agent_counts:
            return "general"
        return max(self.agent_counts, key=lambda k: self.agent_counts[k])

    def message_count(self) -> int:
        """Count only user messages (not assistant responses)."""
        return len([m for m in self.messages if m["role"] == "user"])

    def to_text(self, max_chars: int = 8000) -> str:
        """Flatten transcript to text for the extraction prompt.

        Truncates from the beginning if too long (keeps recent context).
        """
        lines = []
        for msg in self.messages:
            role = msg["role"].upper()
            lines.append(f"{role}: {msg['content']}")
        full = "\n\n".join(lines)
        if len(full) > max_chars:
            tail = full[-max_chars:]
            # Find next newline boundary to avoid cutting mid-word
            nl = tail.find("\n")
            if nl != -1:
                tail = tail[nl + 1 :]
            full = "...[earlier messages truncated]...\n\n" + tail
        return full


@dataclass
class ExtractedMemory:
    """A single memory extracted from a session transcript."""

    content: str
    domain: str
    tags: list[str]
    importance: float
    content_type: str


def parse_extraction_response(raw: str) -> list[ExtractedMemory]:
    """Parse the LLM's JSON response into ExtractedMemory objects.

    Handles:
    - Malformed JSON -> returns []
    - Missing "memories" key -> returns []
    - Invalid domain -> remaps to "shared"
    - Invalid content_type -> remaps to "note"
    - importance out of range -> clamps to [0.0, 1.0]
    - Missing fields -> skips that memory
    """
    # Strip markdown code fences (```json ... ```) that LLMs sometimes produce
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove opening fence line
        lines = lines[1:]
        # Remove closing fence line if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse extraction response as JSON")
        return []

    if not isinstance(data, dict) or "memories" not in data:
        logger.warning("Extraction response missing 'memories' key")
        return []

    memories = []
    for item in data["memories"]:
        try:
            content = item.get("content", "").strip()
            if not content:
                continue

            domain = item.get("domain", "shared")
            if domain not in VALID_DOMAINS:
                domain = "shared"

            content_type = item.get("content_type", "note")
            if content_type not in VALID_CONTENT_TYPES:
                content_type = "note"

            importance = float(item.get("importance", 0.5))
            importance = max(0.0, min(1.0, importance))

            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [str(t) for t in tags]

            memories.append(
                ExtractedMemory(
                    content=content,
                    domain=domain,
                    tags=tags,
                    importance=importance,
                    content_type=content_type,
                )
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("Skipping malformed memory item: %s", e)
            continue

    return memories[:5]  # Enforce max 5 memories


async def _default_anthropic_extractor(
    system_prompt: str,
    user_message: str,
) -> str:
    """Default LLM extractor using the Anthropic API."""
    client = _get_anthropic_client()
    response = await client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    block = response.content[0] if response.content else None
    return block.text if block is not None and hasattr(block, "text") else ""


async def extract_session_memories(
    transcript: SessionTranscript,
    hub: MemoryHub,
    agent_name: str | None = None,
    llm_extractor: LLMExtractor | None = None,
) -> list[ExtractedMemory]:
    """Extract and persist key facts from a completed session.

    Args:
        transcript: The session transcript to extract from.
        hub: MemoryHub to persist extracted memories.
        agent_name: The agent identity for domain ownership.
            If None, uses transcript.primary_agent() to derive from usage.
        llm_extractor: Optional async callable (system_prompt, user_message) -> str.
            Defaults to Anthropic API. Pass a custom extractor for testing
            with alternative LLM providers (e.g., Ollama).

    Returns the list of memories that were saved (empty if session was trivial).

    Skips extraction entirely if:
    - Fewer than 2 user messages in the session
    - Transcript is empty

    On any extraction failure, logs the error and returns empty list.
    Session memory extraction must never crash the teardown path.
    """
    if transcript.message_count() < 2:
        return []

    text = transcript.to_text()
    if not text.strip():
        return []

    if agent_name is None:
        agent_name = transcript.primary_agent()

    extractor = llm_extractor or _default_anthropic_extractor

    try:
        user_message = f"Extract memories from this session:\n\n{text}"
        raw_text = await extractor(EXTRACTION_SYSTEM_PROMPT, user_message)
        memories = parse_extraction_response(raw_text)

        # Persist each memory
        saved = []
        for mem in memories:
            try:
                vis: Literal["private", "shared"] = "shared" if mem.domain == "shared" else "private"
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
                await hub.save(record, agent_name=agent_name)
                saved.append(mem)
            except Exception:
                logger.exception("Failed to save extracted memory: %s", mem.content[:50])

        logger.info(
            "Session extraction: %d memories extracted, %d saved for user=%s",
            len(memories),
            len(saved),
            transcript.user,
        )
        return saved

    except Exception:
        logger.exception("Session memory extraction failed")
        return []
