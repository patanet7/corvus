---
title: "CLI MCP Tools Bridge Design"
type: spec
status: superseded
date: 2026-03-07
review_by: 2026-04-09
supersedes: null
superseded_by: docs/specs/archive/2026-03-08-cli-agent-prompt-tools-design.md
ground_truths_extracted: false
---

# CLI MCP Tools Bridge Design

## Goal

Give `corvus chat` agents access to their full domain toolset (Obsidian, HA, Paperless, email, finance, memory) by generating per-agent MCP configs that reuse the existing Python tool functions. Also support external MCP servers declared in agent.yaml.

## Architecture

```
corvus chat --agent homelab
    |
    +-- build_runtime()
    +-- CapabilitiesRegistry.resolve(agent_spec)   <- determines allowed tools
    |
    +-- _build_mcp_config(agent_name, resolved_tools)
    |     +-- Entry 1: corvus-tools bridge server
    |     |     command: uv run python -m corvus.cli.mcp_bridge
    |     |     args: [--agent, homelab, --modules-json, <tool config>]
    |     |     env: {only OBSIDIAN_URL, OBSIDIAN_API_KEY, HA_URL, HA_TOKEN, ...}
    |     |
    |     +-- Entry 2+: external MCP servers from agent.yaml (if any)
    |     |     command: npx some-external-mcp-server
    |     |     env: {whatever the config says}
    |     |
    |     +-- Writes JSON to: {isolated_home}/.corvus-mcp.json
    |
    +-- _build_claude_cmd()
    |     +-- adds: --mcp-config {isolated_home}/.corvus-mcp.json
    |
    +-- subprocess.run(claude, env=stripped_isolated_env)
                          |
                          +-- claude connects to corvus-tools bridge via stdio
                              (bridge has credentials, claude does not)
```

The bridge server runs as a child of the claude process (stdio MCP). Claude talks to it over stdin/stdout pipes. The bridge has the real credentials in its env. Claude's env is stripped -- it can't read secrets directly, only call tools through the bridge.

## MCP Bridge Server (`corvus/cli/mcp_bridge.py`)

A thin stdio MCP server that:

1. Receives `--agent <name>` and `--modules-json <json>` args at startup
2. Calls the same `configure()` and `create_tools()` functions from `modules.py`
3. Exposes those tools over the MCP stdio protocol
4. Also exposes the memory toolkit (recall/store) for the agent's domain

Uses the `mcp` Python SDK which provides `Server`, `@server.tool()`, and `stdio_server()`.

```python
# Simplified shape:
def main():
    agent_name, module_configs = parse_args()
    server = Server("corvus-tools")

    # For each module this agent is allowed to use:
    for module_name, module_cfg in module_configs.items():
        entry = get_module_entry(module_name)
        entry.configure(module_cfg)
        tools = entry.create_tools(module_cfg)
        for tool_fn in tools:
            register_tool(server, tool_fn)

    # Memory toolkit
    memory_tools = create_memory_toolkit(hub, agent_name, own_domain)
    for tool in memory_tools:
        register_tool(server, tool)

    run_stdio(server)
```

The bridge process inherits credentials via its own env (passed in the MCP config). The claude subprocess does NOT get these env vars.

### Memory Toolkit

The bridge initializes a lightweight `MemoryHub` (no AgentsHub, no EventEmitter, no server machinery):

1. `MemoryConfig.from_file("config/memory.yaml")`
2. `MemoryHub(config)`
3. `create_memory_toolkit(hub, agent_name, own_domain)` -- scoped to agent's domain
4. Register recall/store as MCP tools alongside module tools

Same SQLite DB (`.data/memory/main.sqlite`) as the server path.

## Agent YAML Extension for External MCP Servers

Optional `mcp_servers` field in `AgentToolConfig`:

```yaml
# config/agents/homelab/agent.yaml
tools:
  builtin:
    - Bash
    - Read
  modules:
    obsidian: { read: true, write: false }
    ha: { enabled: true }
  mcp_servers:
    - name: komodo-mcp
      command: npx
      args: ["-y", "@komodo/mcp-server"]
      env:
        KOMODO_URL: "${KOMODO_URL}"
        KOMODO_TOKEN: "${KOMODO_TOKEN}"
    - name: loki-mcp
      transport: http
      url: "http://localhost:3100/mcp"
  confirm_gated: []
```

Rules:
- `mcp_servers` defaults to `[]`
- Each entry becomes an additional key in the generated MCP config JSON
- `env` values support `${VAR}` syntax -- resolved from the Corvus process env at config generation time
- Supports `stdio` (command + args) and `http` (url) transports
- Scoped per-agent -- homelab's external servers are invisible to finance

## Credential Isolation

Three layers of env var scoping:

| Process | What it sees | How |
|---------|-------------|-----|
| Corvus CLI (parent) | Everything | Normal process |
| Bridge server (child of claude) | Only its modules' env vars | MCP config `env` block -- cherry-picked from `requires_env` |
| Claude subprocess | Stripped env -- no credentials | `_prepare_isolated_env()` |
| External MCP servers | Only declared env vars | MCP config `env` block -- `${VAR}` resolved at generation |

Example generated config:

```json
{
  "mcpServers": {
    "corvus-tools": {
      "command": "uv",
      "args": ["run", "python", "-m", "corvus.cli.mcp_bridge", "--agent", "homelab",
               "--modules-json", "{\"obsidian\": {\"read\": true}, \"ha\": {}}"],
      "env": {
        "OBSIDIAN_URL": "https://127.0.0.1:27124",
        "OBSIDIAN_API_KEY": "actual-key-here",
        "HA_URL": "http://ha.local:8123",
        "HA_TOKEN": "actual-token-here"
      }
    },
    "komodo-mcp": {
      "command": "npx",
      "args": ["-y", "@komodo/mcp-server"],
      "env": {
        "KOMODO_URL": "http://komodo.local:8090",
        "KOMODO_TOKEN": "actual-token-here"
      }
    }
  }
}
```

MCP config file written with `0600` permissions in per-agent-scoped directory.

## Files Changed

### New files

| File | Purpose |
|------|---------|
| `corvus/cli/mcp_bridge.py` | Stdio MCP server wrapping tool functions + memory |
| `corvus/cli/mcp_config.py` | Generates per-agent MCP config JSON |

### Modified files

| File | Change |
|------|--------|
| `corvus/cli/chat.py` | Call `build_mcp_config()`, pass `--mcp-config` to claude cmd |
| `corvus/agents/spec.py` | Add `mcp_servers` field to `AgentToolConfig` |
| `pyproject.toml` | Add `mcp` SDK dependency |

### Unchanged

- `corvus/capabilities/modules.py` -- bridge imports the same functions
- `corvus/capabilities/registry.py` -- bridge reuses `resolve()` for env gates
- `corvus/gateway/options.py` -- server path untouched
- `corvus/memory/` -- bridge instantiates `MemoryHub` directly
- All existing tests

## Testing

- Unit tests for `mcp_config.py` -- JSON shape, env scoping, external server merging
- Unit tests for `mcp_bridge.py` -- tool registration, module filtering
- Integration smoke test -- verify tools are wired without launching a full session
