"""Integration test conftest -- shared fixtures for memory hub integration tests.

Provides:
- seeded_hub: hub pre-loaded with multi-domain test data
- Ollama/LLM availability markers for extraction tests
- llm_extractor: async callable for real LLM extraction tests
- llm_extraction_config: dict with provider/model/base_url details

Re-exports from root conftest:
- run: async-to-sync helper
- make_hub: hub factory function
- memory_config, memory_hub, fts5_backend: composable fixtures (via pytest)

All fixtures use tmp_path for automatic cleanup. NO mocks anywhere.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from anthropic import AsyncAnthropic

from corvus.memory.config import MemoryConfig
from corvus.memory.hub import MemoryHub
from corvus.memory.record import MemoryRecord
from corvus.session import _default_anthropic_extractor
from tests.conftest import make_hub, run  # noqa: F401 -- re-exported for test files

# ---------------------------------------------------------------------------
# Hub fixture alias for integration tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def hub(tmp_path: Path) -> MemoryHub:
    """Create a MemoryHub with a fresh FTS5 primary backend.

    This is an alias that integration tests can use alongside the root-level
    ``memory_hub`` fixture. Uses its own db name to avoid conflicts with
    tests that need multiple hubs.
    """
    return make_hub(tmp_path)


# ---------------------------------------------------------------------------
# Seed data used by seeded_hub
# ---------------------------------------------------------------------------

SEED_MEMORIES = [
    # Homelab domain -- private
    {
        "id": "seed-homelab-1",
        "content": "Deployed Komodo on optiplex for container orchestration",
        "domain": "homelab",
        "visibility": "private",
        "importance": 0.8,
        "tags": ["komodo", "docker", "optiplex"],
        "source": "session",
        "agent_name": "homelab",
    },
    {
        "id": "seed-homelab-2",
        "content": "SWAG reverse proxy uses wildcard cert for example.com",
        "domain": "homelab",
        "visibility": "private",
        "importance": 0.7,
        "tags": ["swag", "ssl", "proxy"],
        "source": "agent",
        "agent_name": "homelab",
    },
    # Finance domain -- private
    {
        "id": "seed-finance-1",
        "content": "Monthly budget target is 3000 for household expenses",
        "domain": "finance",
        "visibility": "private",
        "importance": 0.6,
        "tags": ["budget", "household"],
        "source": "session",
        "agent_name": "finance",
    },
    {
        "id": "seed-finance-2",
        "content": "Firefly III running on miniserver for transaction tracking",
        "domain": "finance",
        "visibility": "private",
        "importance": 0.7,
        "tags": ["firefly", "tracking"],
        "source": "agent",
        "agent_name": "finance",
    },
    # Personal domain -- private
    {
        "id": "seed-personal-1",
        "content": "Prefers dark mode for all editors and terminals",
        "domain": "personal",
        "visibility": "private",
        "importance": 0.4,
        "tags": ["preference", "ui"],
        "source": "session",
        "agent_name": "personal",
    },
    # Shared domain -- visible to all agents
    {
        "id": "seed-shared-1",
        "content": "All hosts use SSH key authentication with NOPASSWD sudo",
        "domain": "shared",
        "visibility": "shared",
        "importance": 0.95,
        "tags": ["security", "ssh", "sudo"],
        "source": "agent",
        "agent_name": "general",
    },
    {
        "id": "seed-shared-2",
        "content": "System timezone is set to America/New_York across all services",
        "domain": "shared",
        "visibility": "shared",
        "importance": 0.5,
        "tags": ["config", "timezone"],
        "source": "agent",
        "agent_name": "general",
    },
]


@pytest.fixture()
def seeded_hub(tmp_path: Path) -> MemoryHub:
    """Create a MemoryHub pre-loaded with test data across multiple domains.

    Contains memories in: homelab, finance, personal, shared.
    Suitable for testing cross-domain visibility, search, and filtering.
    """
    config = MemoryConfig(primary_db_path=tmp_path / "seeded.sqlite")
    h = MemoryHub(config)
    now = datetime.now(UTC).isoformat()

    for seed in SEED_MEMORIES:
        record = MemoryRecord(
            id=seed["id"],
            content=seed["content"],
            domain=seed["domain"],
            visibility=seed["visibility"],
            importance=seed["importance"],
            tags=seed["tags"],
            source=seed["source"],
            created_at=now,
        )
        run(h.save(record, agent_name=seed["agent_name"]))

    return h


# ---------------------------------------------------------------------------
# LLM availability detection for extraction tests
# ---------------------------------------------------------------------------


def _ollama_available() -> bool:
    """Check if Ollama is running and has at least one model available."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            return len(models) > 0
        return False
    except (httpx.ConnectError, httpx.TimeoutException, Exception):
        return False


def _anthropic_available() -> bool:
    """Check if ANTHROPIC_API_KEY is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# Evaluate once at import time to avoid repeated HTTP calls
OLLAMA_AVAILABLE = _ollama_available()
ANTHROPIC_AVAILABLE = _anthropic_available()
LLM_AVAILABLE = ANTHROPIC_AVAILABLE or OLLAMA_AVAILABLE

# Determine which Ollama model to use for extraction (prefer smaller/faster models)
OLLAMA_EXTRACTION_MODEL = "qwen3:4b"  # Small, fast, good at structured JSON output

skip_no_llm = pytest.mark.skipif(
    not LLM_AVAILABLE,
    reason="No LLM available (neither ANTHROPIC_API_KEY nor local Ollama)",
)


@pytest.fixture()
def llm_extraction_config():
    """Provide LLM configuration for extraction tests.

    Returns a dict with the keys needed to configure extraction:
    - 'provider': 'anthropic' or 'ollama'
    - 'model': model name string
    - 'base_url': API base URL (only for Ollama)

    Usage in tests: apply @skip_no_llm marker, then use this fixture
    to get the correct configuration.
    """
    if ANTHROPIC_AVAILABLE:
        return {
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "base_url": None,
        }
    if OLLAMA_AVAILABLE:
        return {
            "provider": "ollama",
            "model": OLLAMA_EXTRACTION_MODEL,
            "base_url": "http://localhost:11434",
        }
    pytest.skip("No LLM available")


# ---------------------------------------------------------------------------
# LLM extractor callables for use with extract_session_memories()
# ---------------------------------------------------------------------------


async def _ollama_extractor(system_prompt: str, user_message: str) -> str:
    """LLM extractor using Ollama's Anthropic-compatible API.

    Ollama exposes an Anthropic-compatible endpoint, so we use the same
    AsyncAnthropic client pointed at localhost. No extra SDKs needed.
    This is a real LLM call, no mocks, no fakes. The model runs locally.
    """
    client = AsyncAnthropic(
        base_url="http://localhost:11434",
        api_key="ollama",  # Ollama doesn't need auth, but SDK requires a value
    )
    response = await client.messages.create(
        model=OLLAMA_EXTRACTION_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


@pytest.fixture()
def llm_extractor():
    """Provide a real LLM extractor callable for extraction tests.

    Returns an async callable with signature (system_prompt, user_message) -> str
    that can be passed directly to extract_session_memories(llm_extractor=...).

    Prefers Anthropic when ANTHROPIC_API_KEY is set, falls back to Ollama.
    Skips the test if neither is available.
    """
    if ANTHROPIC_AVAILABLE:
        # Use the default Anthropic extractor from corvus.session
        return _default_anthropic_extractor
    if OLLAMA_AVAILABLE:
        return _ollama_extractor
    pytest.skip("No LLM available")
