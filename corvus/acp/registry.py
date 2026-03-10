"""ACP Agent Registry — loads agent command definitions from config YAML.

Provides AcpAgentEntry (frozen dataclass) and AcpAgentRegistry for
config-driven lookup of ACP-compatible coding agents (Codex, Gemini, etc.).
"""

import shlex
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger(__name__)

CONFIG_FILENAME = "acp_agents.yaml"


@dataclass(frozen=True)
class AcpAgentEntry:
    """Immutable descriptor for an ACP-compatible agent."""

    name: str
    command: str
    default_permissions: str = "deny-all"

    def command_parts(self) -> list[str]:
        """Split command string into argv list suitable for subprocess."""
        return shlex.split(self.command)


class AcpAgentRegistry:
    """Registry of ACP agents loaded from a YAML config file.

    Args:
        config_dir: Directory containing ``acp_agents.yaml``.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._agents: dict[str, AcpAgentEntry] = {}

    def load(self) -> None:
        """Read acp_agents.yaml and populate the internal registry.

        Warns if the config file is missing. Safe to call multiple times;
        each call replaces the previous registry contents.
        """
        config_path = self._config_dir / CONFIG_FILENAME
        if not config_path.exists():
            logger.warning("acp_agents_config_not_found", config_path=str(config_path))
            self._agents = {}
            return

        raw = yaml.safe_load(config_path.read_text())
        agents_block: dict = raw.get("agents", {}) if raw else {}

        loaded: dict[str, AcpAgentEntry] = {}
        for name, spec in agents_block.items():
            loaded[name] = AcpAgentEntry(
                name=name,
                command=spec["command"],
                default_permissions=spec.get("default_permissions", "deny-all"),
            )

        self._agents = loaded
        logger.info("acp_agents_loaded", count=len(loaded), agents=sorted(loaded.keys()))

    def get(self, name: str) -> AcpAgentEntry | None:
        """Return the agent entry for *name*, or None if not registered."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """Return sorted list of registered agent names."""
        return sorted(self._agents.keys())
