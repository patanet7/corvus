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

# ---------------------------------------------------------------------------
# Credential env isolation — snapshot/restore credential-related env vars
# around every test so injection tests can't pollute routing or other tests.
# ---------------------------------------------------------------------------

_CREDENTIAL_ENV_VARS = [
    # LLM providers
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OLLAMA_BASE_URL", "KIMI_BOT_TOKEN",
    "CODEX_API_KEY",
    "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY",
    # Services (from SERVICE_ENV_MAP)
    "HA_URL", "HA_TOKEN",
    "PAPERLESS_URL", "PAPERLESS_API_TOKEN",
    "FIREFLY_URL", "FIREFLY_API_TOKEN",
    "OBSIDIAN_URL", "OBSIDIAN_API_KEY",
    # Google
    "GOOGLE_CREDS_PATH",
]


@pytest.fixture(autouse=True)
def _isolate_credential_env():
    """Snapshot and restore credential env vars around every test.

    This prevents credential injection tests from polluting the environment
    for subsequent tests (e.g. routing tests that need ANTHROPIC_API_KEY=ollama).
    """
    snapshot = {var: os.environ.get(var) for var in _CREDENTIAL_ENV_VARS}
    yield
    for var, val in snapshot.items():
        if val is not None:
            os.environ[var] = val
        else:
            os.environ.pop(var, None)

# ---------------------------------------------------------------------------
# Tool module global isolation — snapshot/restore module-level config globals
# so configure() calls in one test don't leak into the next.
# ---------------------------------------------------------------------------

from corvus.tools import drive as _drive_mod  # noqa: E402
from corvus.tools import email as _email_mod  # noqa: E402
from corvus.tools import firefly as _firefly_mod  # noqa: E402
from corvus.tools import ha as _ha_mod  # noqa: E402
from corvus.tools import obsidian as _obsidian_mod  # noqa: E402
from corvus.tools import paperless as _paperless_mod  # noqa: E402

_TOOL_MODULE_GLOBALS = [
    (_ha_mod, "_ha_url"),
    (_ha_mod, "_ha_token"),
    (_paperless_mod, "_paperless_url"),
    (_paperless_mod, "_paperless_token"),
    (_firefly_mod, "_firefly_url"),
    (_firefly_mod, "_firefly_token"),
    (_obsidian_mod, "_client"),
    (_email_mod, "_google_client"),
    (_email_mod, "_yahoo_client"),
    (_drive_mod, "_client"),
]


@pytest.fixture(autouse=True)
def _isolate_tool_modules():
    """Snapshot and restore all tool module globals around every test.

    Replaces scattered try/finally blocks and per-file _clean_tool_modules
    fixtures. Any test that calls configure() gets automatic cleanup.
    """
    snapshot = [(mod, attr, getattr(mod, attr)) for mod, attr in _TOOL_MODULE_GLOBALS]
    yield
    for mod, attr, orig_val in snapshot:
        setattr(mod, attr, orig_val)


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
