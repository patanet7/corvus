"""Generate per-agent MCP config JSON for corvus chat CLI.

Builds a config file that tells the claude subprocess which MCP servers
to connect to. The primary entry is the corvus-tools bridge server
(wrapping our Python tool functions). External MCP servers from agent.yaml
are merged alongside it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def resolve_bridge_env(requires_env: list[str]) -> dict[str, str]:
    """Cherry-pick only the required env vars for the bridge server.

    Returns a dict of var_name -> value for vars that exist and are non-empty.
    Missing vars are silently skipped (the bridge will fail gracefully).
    """
    env: dict[str, str] = {}
    for var in requires_env:
        value = os.environ.get(var, "").strip()
        if value:
            env[var] = value
    return env


def _resolve_env_references(env: dict[str, str]) -> dict[str, str]:
    """Resolve ${VAR} references in env values from os.environ."""
    resolved: dict[str, str] = {}
    pattern = re.compile(r"\$\{([^}]+)\}")
    for key, value in env.items():

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")

        resolved[key] = pattern.sub(_replace, value)
    return resolved


def _build_external_entry(server: dict) -> dict:
    """Build a single MCP config entry from an external server declaration."""
    transport = server.get("transport", "stdio")

    if transport == "http":
        entry: dict = {"type": "http", "url": server["url"]}
        if "env" in server:
            entry["env"] = _resolve_env_references(server["env"])
        return entry

    # stdio transport (default)
    entry = {
        "command": server["command"],
        "args": server.get("args", []),
    }
    if "env" in server:
        entry["env"] = _resolve_env_references(server["env"])
    return entry


def build_mcp_config(
    *,
    agent_name: str,
    module_configs: dict[str, dict],
    requires_env_by_module: dict[str, list[str]],
    external_mcp_servers: list[dict],
    output_dir: Path,
    memory_domain: str,
) -> Path:
    """Generate MCP config JSON and write it to output_dir.

    Args:
        agent_name: Agent name for the bridge server.
        module_configs: Dict of module_name -> module config from agent spec.
        requires_env_by_module: Dict of module_name -> list of required env vars.
        external_mcp_servers: List of external MCP server dicts from agent.yaml.
        output_dir: Directory to write the config file to.
        memory_domain: Agent's memory domain for the memory toolkit.

    Returns:
        Path to the written config file.
    """
    mcp_servers: dict[str, dict] = {}

    # 1. Bridge server -- wraps our Python tools + memory
    all_required_env: list[str] = []
    for module_name in module_configs:
        all_required_env.extend(requires_env_by_module.get(module_name, []))
    bridge_env = resolve_bridge_env(list(set(all_required_env)))

    modules_json = json.dumps(module_configs)
    mcp_servers["corvus-tools"] = {
        "command": "uv",
        "args": [
            "run",
            "python",
            "-m",
            "corvus.cli.mcp_bridge",
            "--agent",
            agent_name,
            "--modules-json",
            modules_json,
            "--memory-domain",
            memory_domain,
        ],
        "env": bridge_env,
    }

    # 2. External MCP servers from agent.yaml
    for server in external_mcp_servers:
        name = server.get("name", "unnamed")
        mcp_servers[name] = _build_external_entry(server)

    config = {"mcpServers": mcp_servers}
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / ".corvus-mcp.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    config_path.chmod(0o600)
    return config_path
