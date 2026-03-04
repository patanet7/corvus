"""Root conftest -- shared fixtures and test infrastructure.

- Adds the worktree root to sys.path so ``from scripts.<mod>`` imports work
  without per-test sys.path hacks.
- Ensures tests/output/ exists for log files.
- Provides project-wide async helpers and common memory fixtures.
- Exports ``make_hub`` factory function for test files that need to create
  hubs inside methods or with custom paths.

All fixtures use tmp_path for automatic cleanup. NO mocks anywhere.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Set test-safe paths BEFORE any claw module imports, so claw.config picks up
# writable temp directories instead of /data (which doesn't exist locally).
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="claw_test_"))
os.environ.setdefault("DATA_DIR", str(_TEST_DATA_DIR))
os.environ.setdefault("MEMORY_DB", str(_TEST_DATA_DIR / "memory" / "test.sqlite"))
os.environ.setdefault("LOG_DIR", str(_TEST_DATA_DIR / "logs"))
os.environ.setdefault("ALLOWED_USERS", "testuser")

# If no Anthropic API key, default to Ollama's Anthropic-compatible endpoint
if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:11434")
    os.environ.setdefault("ANTHROPIC_API_KEY", "ollama")
# Create directories so SQLite and log writers can open files
(_TEST_DATA_DIR / "memory").mkdir(parents=True, exist_ok=True)
(_TEST_DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
(_TEST_DATA_DIR / "workspace" / "memory").mkdir(parents=True, exist_ok=True)

import pytest  # noqa: E402

from corvus.memory.backends.fts5 import FTS5Backend  # noqa: E402
from corvus.memory.config import MemoryConfig  # noqa: E402
from corvus.memory.hub import MemoryHub  # noqa: E402

WORKTREE_ROOT = Path(__file__).resolve().parents[1]

if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Project-wide async helper
# ---------------------------------------------------------------------------


def run(coro):
    """Run an async coroutine synchronously in tests.

    This is the single canonical run() helper -- all test files should use this
    instead of defining their own ``asyncio.run()`` wrappers.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Hub factory function (plain function, not a fixture)
# ---------------------------------------------------------------------------


_KNOWN_AGENTS = {
    "personal",
    "work",
    "homelab",
    "finance",
    "email",
    "docs",
    "music",
    "home",
}


def _test_memory_access(agent_name: str) -> dict[str, Any]:
    """Test memory access mirroring production: known agents can write, unknown cannot."""
    if agent_name == "general":
        return {"own_domain": "shared", "can_read_shared": True, "can_write": True, "readable_domains": None}
    if agent_name in _KNOWN_AGENTS:
        return {"own_domain": agent_name, "can_read_shared": True, "can_write": True, "readable_domains": None}
    # Unknown agents: read-only, shared domain
    return {"own_domain": "shared", "can_read_shared": True, "can_write": False, "readable_domains": None}


def _test_readable_domains(agent_name: str) -> list[str]:
    """Readable domains for testing: own domain + shared (no cross-domain reads)."""
    own = agent_name if agent_name in _KNOWN_AGENTS else "shared"
    return [own, "shared"] if own != "shared" else ["shared"]


def make_hub(tmp_path: Path, db_name: str = "hub.sqlite") -> MemoryHub:
    """Create a Hub with a fresh FTS5 primary backend.

    This is a plain function (not a fixture) for tests that create hubs
    inside methods or need multiple hubs with custom db names.

    Uses permissive memory access resolvers so tests can write without
    requiring the full AgentsHub YAML configuration.

    Args:
        tmp_path: pytest tmp_path for automatic cleanup.
        db_name: SQLite database filename (default: "hub.sqlite").

    Returns:
        A freshly initialized MemoryHub with write access enabled.
    """
    config = MemoryConfig(primary_db_path=tmp_path / db_name)
    return MemoryHub(
        config,
        get_memory_access_fn=_test_memory_access,
        get_readable_domains_fn=_test_readable_domains,
    )


# ---------------------------------------------------------------------------
# Project-wide memory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_config(tmp_path: Path) -> MemoryConfig:
    """Create a MemoryConfig pointing to a fresh SQLite db in tmp_path."""
    return MemoryConfig(primary_db_path=tmp_path / "memory_test.sqlite")


@pytest.fixture()
def memory_hub(memory_config: MemoryConfig) -> MemoryHub:
    """Create a MemoryHub with safe defaults (read-only, shared domain).

    Uses the default _safe_memory_access resolver — writes will raise
    PermissionError.  For tests that need write access, use make_hub()
    which provides permissive test resolvers.
    """
    return MemoryHub(memory_config)


@pytest.fixture()
def fts5_backend(tmp_path: Path) -> FTS5Backend:
    """Create a standalone FTS5Backend for lower-level backend tests.

    Available project-wide so both gateway and integration tests can use it.
    """
    return FTS5Backend(db_path=tmp_path / "fts5_test.sqlite")
