"""Configuration loader for Corvus Gateway."""

import os
from pathlib import Path


def _resolve_data_dir() -> Path:
    """Resolve DATA_DIR: env var > /data (Docker) > .data/ (local dev)."""
    if env := os.environ.get("DATA_DIR"):
        return Path(env)
    docker_path = Path("/data")
    if docker_path.is_dir():
        return docker_path
    # Local dev fallback: .data/ in project root
    return Path(__file__).resolve().parent.parent / ".data"


# Paths — Docker mounts host data dir as /data; local dev uses .data/
DATA_DIR = _resolve_data_dir()
MEMORY_DIR = DATA_DIR / "workspace" / "memory"
MEMORY_DB = Path(os.environ.get("MEMORY_DB", str(DATA_DIR / "memory" / "main.sqlite")))
WORKSPACE_DIR = DATA_DIR / "workspace"
CLAUDE_RUNTIME_HOME = Path(os.environ.get("CORVUS_CLAUDE_HOME", str(DATA_DIR / "claude-home")))
CLAUDE_HOME_SCOPE = os.environ.get("CORVUS_CLAUDE_HOME_SCOPE", "per_agent").strip().lower()
CLAUDE_CONFIG_TEMPLATE = Path(
    os.environ.get("CORVUS_CLAUDE_CONFIG_TEMPLATE", "config/claude-runtime/claude.json")
)
ISOLATE_CLAUDE_HOME = os.environ.get("CORVUS_ISOLATE_CLAUDE_HOME", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "18789"))

# Auth
ALLOWED_USERS = [u for u in os.environ.get("ALLOWED_USERS", "").split(",") if u]
MAX_PARALLEL_AGENT_RUNS = max(1, int(os.environ.get("MAX_PARALLEL_AGENT_RUNS", "4")))

# Google multi-account (new pattern)
# GOOGLE_ACCOUNT_{name}_EMAIL, GOOGLE_ACCOUNT_{name}_CREDENTIALS, GOOGLE_ACCOUNT_{name}_TOKEN
# GOOGLE_DEFAULT_ACCOUNT
# Legacy: GMAIL_TOKEN, GMAIL_CREDENTIALS, GMAIL_ADDRESS (still supported)

# Yahoo multi-account
# YAHOO_ACCOUNT_{name}_EMAIL, YAHOO_ACCOUNT_{name}_APP_PASSWORD
# Legacy: YAHOO_EMAIL, YAHOO_APP_PASSWORD

# Service credentials (HA, Paperless, Firefly, Obsidian) are injected at runtime
# via SERVICE_ENV_MAP in credential_store.py → os.environ. Tool modules read
# directly from os.environ in their configure() functions.

# Scheduling
SCHEDULES_CONFIG = Path(os.environ.get("SCHEDULES_CONFIG", "config/schedules.yaml"))
CAPABILITIES_CONFIG = Path(os.environ.get("CAPABILITIES_CONFIG", "config/capabilities.yaml"))
TASK_ROUTING_CONFIG = Path(os.environ.get("TASK_ROUTING_CONFIG", "config/task_routing.yaml"))
MEMORY_CONFIG = Path(os.environ.get("MEMORY_CONFIG", "config/memory.yaml"))

# Logging — /var/log/corvus in Docker, .data/logs locally
LOG_DIR = Path(os.environ.get("LOG_DIR", str(DATA_DIR / "logs")))
EVENTS_LOG = LOG_DIR / "events.jsonl"
