# CLI Agent Prompt & Tool Delivery Redesign

## Goal

Replace the monolithic `--system-prompt` blob and fragile MCP bridge with native Claude Code delivery: minimal system prompt for identity override, CLAUDE.md for compositional context, and skills with bundled scripts over a secure Unix socket tool server for tool access.

## Motivation

### Why move away from MCP

- **Context cost**: A 5-server, 58-tool MCP setup consumes 55,000+ tokens before conversation starts. Skills cost ~30-50 tokens each (description only) with progressive loading.
- **Reliability**: MCP in Claude Code has known issues — 5-minute timeout failures, startup hangs, protocol reuse errors, dual process spawns. Skills + Bash have none of these failure modes.
- **Accuracy**: Anthropic internal testing showed 49% → 74% accuracy improvement when moving from always-loaded tools to on-demand discovery. Skills are on-demand by design.
- **Anthropic's guidance**: "MCP connects Claude to data; Skills teach Claude what to do with that data." For agent tools that make API calls, skills + CLI scripts are the recommended pattern.

### Why split the system prompt

Claude Code has a hardcoded "You are Claude" identity. The `--system-prompt` flag overrides this. But cramming 4,000+ chars of domain instructions, sibling lists, and memory context into a single prompt string wastes the native CLAUDE.md system that Claude Code is optimized to read.

**Split**: system prompt carries identity weight, CLAUDE.md handles everything compositional.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Claude Code subprocess (per agent)             │
│                                                 │
│  --system-prompt   Soul + Identity (~200 words) │
│                    "You are NOT Claude.          │
│                     You are the {agent} agent."  │
│                                                 │
│  CLAUDE.md         Domain instructions           │
│                    Sibling agents                │
│                    Memory seeds (top 15)         │
│                                                 │
│  .claude/skills/   Tool skills (progressive)     │
│    obsidian/         SKILL.md + scripts/         │
│    ha/               SKILL.md + scripts/         │
│    memory/           SKILL.md + scripts/         │
│    ...                                          │
│                                                 │
│  Env:                                           │
│    CORVUS_TOOL_SOCKET=/path/to/.corvus.sock     │
│    CORVUS_TOOL_TOKEN=<agent-scoped JWT>         │
│                                                 │
└──────────────────┬──────────────────────────────┘
                   │ Unix socket
                   ▼
┌─────────────────────────────────────────────────┐
│  Corvus Tool Server (started before claude)     │
│                                                 │
│  - Listens on Unix socket in agent workspace    │
│  - Validates JWT (agent, allowed_modules, exp)  │
│  - Holds real credentials (API keys, tokens)    │
│  - Calls corvus.tools.* with real auth          │
│  - Returns sanitized responses                  │
│  - One server per agent session                 │
└─────────────────────────────────────────────────┘
```

## Component Design

### 1. System Prompt (minimal, ~200 words)

Passed via `--system-prompt`. Contains only what must override Claude Code's default identity:

```
{soul.md content — core principles, identity override, memory tool instructions}

You are the **{agent_name}** agent.
Always identify as the {agent_name} agent when asked who you are.

{agent_soul content — personality/vibe from config/agents/{name}/soul.md}
```

This is the 6-layer composition layers 0, 1, and 2 (soul, agent soul, agent identity). These MUST be in the system prompt to counteract Claude Code's hardcoded identity.

### 2. CLAUDE.md (workspace context)

Written to `{agent_workspace}/CLAUDE.md` at launch. Regenerated each session (fresh memory seeds).

```markdown
# {Agent Name} Agent

{agent_prompt content from config/agents/{name}/prompt.md}

---

# Other Agents

If a question falls outside your domain, tell the user which of these agents can help:
- **work**: Professional partner for meetings, projects...
- **finance**: Budget tracking, transactions...
{...dynamically composed from registry, excluding self}

---

# Memory Context

Your memory domain is **{own_domain}**.
These are your most relevant recent and evergreen memories:
- [evergreen] (personal) Thomas prefers dark mode [preferences]
- (personal) Set up new NAS last week [homelab, hardware]
{...top 15 from MemoryHub.seed_context()}
```

This is layers 3, 4, and 5 (agent prompt, siblings, memory context). Claude Code loads CLAUDE.md natively at session start and preserves it across `/compact`.

### 3. Tool Skills (progressive context)

Each tool module becomes a skill directory, copied into the agent's workspace at launch. Only modules declared in the agent's `tools.modules` spec get copied.

#### Directory structure

```
{agent_workspace}/.claude/skills/{module}/
├── SKILL.md          # When/how to use, param descriptions
├── reference.md      # Detailed API docs (loaded on demand by Claude)
└── scripts/
    └── {module}.py   # Thin wrapper: Unix socket call + print result
```

#### SKILL.md frontmatter

```yaml
---
name: obsidian
description: Search, read, and write Obsidian vault notes. Use when the user asks about notes, knowledge base, or documentation in Obsidian.
allowed-tools: Bash(python *)
user-invocable: false
---
```

- `user-invocable: false` — Claude loads automatically when relevant. No `/obsidian` in the slash menu.
- `allowed-tools: Bash(python *)` — grants Bash execution for the bundled scripts without per-use approval.
- Description kept short (~1 line) since it's always in context.

#### Script pattern

Each `scripts/{module}.py` is a thin wrapper:

```python
#!/usr/bin/env python3
"""corvus tool: obsidian_search"""
import json
import os
import socket
import sys

SOCKET_PATH = os.environ["CORVUS_TOOL_SOCKET"]
TOKEN = os.environ["CORVUS_TOOL_TOKEN"]

def call_tool(tool_name: str, params: dict) -> dict:
    """Call the corvus tool server over Unix socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCKET_PATH)
    request = json.dumps({
        "tool": tool_name,
        "params": params,
        "token": TOKEN,
    })
    sock.sendall(request.encode() + b"\n")
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    return json.loads(response.decode())

if __name__ == "__main__":
    # CLI: python obsidian.py search --query "my query" --limit 10
    action = sys.argv[1]
    # Parse --key value pairs from argv
    params = {}
    i = 2
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            params[key] = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    result = call_tool(f"obsidian_{action}", params)
    print(json.dumps(result, indent=2))
```

Usage from Claude's Bash tool:
```bash
python .claude/skills/obsidian/scripts/obsidian.py search --query "meeting notes"
python .claude/skills/ha/scripts/ha.py call_service --domain light --service turn_off --entity_id light.office
python .claude/skills/memory/scripts/memory.py search --query "Thomas preferences"
```

### 4. Tool Server

New module: `corvus/cli/tool_server.py`

#### Lifecycle

1. Started before `claude` subprocess in `chat.py:main()`
2. Listens on `{agent_workspace}/.corvus.sock`
3. Socket file permissions: `chmod 600`
4. Stopped after `claude` subprocess exits (finally block)

#### Protocol

Simple JSON-over-Unix-socket. One request-response per connection.

**Request:**
```json
{
  "tool": "obsidian_search",
  "params": {"query": "meeting notes", "limit": 10},
  "token": "<JWT>"
}
```

**Response (success):**
```json
{
  "ok": true,
  "result": {"content": [{"type": "text", "text": "..."}]}
}
```

**Response (error):**
```json
{
  "ok": false,
  "error": "not_authorized"
}
```

#### JWT Token

- **Payload**: `{agent: "personal", modules: ["obsidian", "email", "memory"], exp: <unix_timestamp>}`
- **Signing**: HMAC-SHA256 with a per-session random secret (32 bytes from `os.urandom`)
- **Lifetime**: matches the claude subprocess session
- **Secret**: generated at launch, held in memory, never persisted to disk

#### Tool Dispatch

The server reuses existing `corvus.tools.*` functions:

1. Validate JWT — check signature, expiry, extract `modules` list
2. Parse tool name — e.g., `obsidian_search` → module `obsidian`, function `obsidian_search`
3. Check module is in JWT's `modules` list — reject if not
4. Look up function in module registry (same registry as current `mcp_bridge.py`)
5. Call function with params
6. Return sanitized result via `corvus.tools.response.make_tool_response()`

#### Credential Management

- Tool server process inherits the full environment (including API keys from `.env`)
- The `claude` subprocess gets a filtered env (no API keys, only `CORVUS_TOOL_SOCKET` and `CORVUS_TOOL_TOKEN`)
- Existing `configure()` functions per module set up clients with real credentials
- Sanitization via `corvus.sanitize.sanitize()` strips any leaked credentials from responses

#### Memory Tools

Memory tools (search, save, get, list, forget) are registered as module `memory` in the tool server. The server creates a `MemoryHub` instance with bridge-specific resolvers (same as current `mcp_bridge.py:register_memory_tools()`), with agent identity baked into the closure.

### 5. Launch Flow

Updated `corvus/cli/chat.py` main():

```
1. Build runtime                               (unchanged)
2. Pick agent                                   (unchanged)
3. Create agent workspace                       (unchanged)
4. Start LiteLLM proxy                          (unchanged)
5. Generate JWT for this agent session          (NEW)
6. Start tool server on Unix socket             (NEW)
7. Prepare isolated env
   - Add CORVUS_TOOL_SOCKET, CORVUS_TOOL_TOKEN  (NEW)
   - Remove real API keys from agent env         (NEW)
8. Write CLAUDE.md to agent workspace           (NEW — replaces part of system prompt)
9. Copy allowed skills only                     (CHANGED — tool skills, not just agent skills)
10. Build claude cmd
    - --system-prompt is soul + identity only    (CHANGED — much shorter)
    - No --mcp-config                            (REMOVED)
    - --allowedTools: builtin + Bash(python *)   (CHANGED — no mcp__* patterns)
11. Seed settings                                (unchanged)
12. Launch subprocess                            (unchanged)
13. Stop tool server                             (NEW — in finally block)
```

### 6. Skill Copying

Updated `copy_agent_skills()` or new function in `corvus/gateway/workspace_runtime.py`:

1. Read agent spec's `tools.modules` → list of allowed module names
2. For each allowed module, copy the skill directory from `config/skills/tools/{module}/` to `{agent_workspace}/.claude/skills/{module}/`
3. Always copy `config/skills/tools/memory/` (all agents get memory)
4. Copy agent-specific skills from `config/agents/{name}/skills/` (unchanged)
5. Copy shared skills from `config/skills/shared/` (unchanged)

Skills are **templates**: the `SKILL.md` and `reference.md` are static, but the `scripts/{module}.py` wrapper is the same for all agents (it reads socket/token from env). The scoping is done by which skill directories get copied, not by the script content.

## What Gets Removed

| Component | Status |
|-----------|--------|
| `corvus/cli/mcp_bridge.py` | Replaced by `corvus/cli/tool_server.py` |
| `corvus/cli/mcp_config.py` | No longer needed |
| `_build_agent_mcp_config()` in `chat.py` | Removed |
| `--mcp-config` in `_build_claude_cmd()` | Removed |
| `mcp__corvus-tools__*` in `--allowedTools` | Replaced by `Bash(python *)` |
| `fastmcp` dependency | Remove if not used elsewhere |
| `tests/unit/test_chat_mcp_wiring.py` | Replace with tool server tests |

## Security Model

### Defense in Depth

| Layer | Protects Against |
|-------|-----------------|
| Skills only copied for allowed modules | Agent can't call tools whose scripts don't exist in workspace |
| Unix socket with `chmod 600` | Other system processes can't connect to the tool server |
| Agent-scoped JWT | Token only authorizes this agent's allowed modules; rejects unauthorized tool calls |
| Per-session random signing secret | Tokens can't be forged or reused across sessions |
| Credentials only in tool server process | Agent environment never contains real API keys/tokens |
| Sanitized responses | No credential leakage in tool output |
| Process environment isolation | Each agent subprocess has its own env; can't read other agents' tokens |

### Known Risk: Filesystem Traversal

The agent has Bash access and could theoretically traverse to the corvus project root or other agents' workspaces. The JWT prevents unauthorized tool calls even with socket access, but source code read access is not blocked.

**Future mitigation options:**
- Restrict Bash tool paths via `--allowedTools` deny patterns
- Run agent subprocess in a chroot or container
- Use filesystem namespace isolation (Linux namespaces)

This is noted as a known risk, not a launch blocker. The JWT is the real security boundary.

## File Layout (New/Changed)

```
corvus/
├── cli/
│   ├── chat.py                  # CHANGED — new launch flow
│   ├── tool_server.py           # NEW — Unix socket tool server
│   ├── mcp_bridge.py            # REMOVED
│   └── mcp_config.py            # REMOVED
├── tools/                       # UNCHANGED — existing tool functions
│   ├── obsidian.py
│   ├── ha.py
│   ├── firefly.py
│   ├── email.py
│   ├── drive.py
│   └── paperless.py
├── memory/
│   └── toolkit.py               # UNCHANGED — memory tools reused by tool server

config/
├── skills/
│   └── tools/                   # NEW — tool skill templates
│       ├── obsidian/
│       │   ├── SKILL.md
│       │   ├── reference.md
│       │   └── scripts/obsidian.py
│       ├── ha/
│       │   ├── SKILL.md
│       │   ├── reference.md
│       │   └── scripts/ha.py
│       ├── memory/
│       │   ├── SKILL.md
│       │   └── scripts/memory.py
│       ├── firefly/
│       │   ├── SKILL.md
│       │   ├── reference.md
│       │   └── scripts/firefly.py
│       ├── email/
│       │   ├── SKILL.md
│       │   ├── reference.md
│       │   └── scripts/email.py
│       ├── drive/
│       │   ├── SKILL.md
│       │   └── scripts/drive.py
│       └── paperless/
│           ├── SKILL.md
│           ├── reference.md
│           └── scripts/paperless.py
├── agents/                      # UNCHANGED
│   ├── personal/
│   ├── work/
│   └── ...

tests/
├── unit/
│   ├── test_tool_server.py      # NEW — JWT validation, dispatch, auth
│   ├── test_skill_copy.py       # NEW — verify only allowed skills copied
│   ├── test_claude_md_compose.py # NEW — verify CLAUDE.md output
│   └── test_chat_mcp_wiring.py  # REMOVED
├── integration/
│   └── test_tool_server_live.py # NEW — end-to-end socket + tool call
```

## Testing Strategy

### Unit Tests

- **JWT generation/validation**: correct payload, expiry enforcement, invalid signature rejection
- **Tool dispatch**: valid module passes, unauthorized module rejected, unknown tool returns error
- **Skill copying**: only allowed modules copied, memory always copied, shared skills included
- **CLAUDE.md composition**: correct sections, memory seeds included, siblings listed
- **System prompt composition**: soul + identity + agent soul, nothing else

### Integration Tests

- **Tool server end-to-end**: start server, connect via socket, call tool, verify response
- **Unauthorized call**: valid token for `obsidian`, try calling `ha_call_service`, verify 403
- **Expired token**: verify rejection after expiry
- **Full launch flow**: build runtime → start tool server → verify socket exists → verify CLAUDE.md written → verify skills copied

### No Mocks

Per project policy: real SQLite for memory, real Unix sockets, real JWT signing. Temp directories for workspace isolation in tests.
