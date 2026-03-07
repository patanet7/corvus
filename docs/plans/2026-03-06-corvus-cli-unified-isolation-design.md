# Corvus Unified Isolation & ACP Integration Design

## Goal

Unify `corvus chat` with the server's existing isolation infrastructure so each agent gets its own skills as slash commands while being fully isolated from the user's global Claude Code environment (plugins, settings, MCP configs).

Additionally, provide a second execution path — the **Agent Client Protocol (ACP)** — enabling Corvus to spawn and orchestrate external coding agents (Codex, Gemini CLI, OpenCode, etc.) as sandboxed sub-agents with the same isolation guarantees and full observability.

## Architecture

Reuse the same isolation primitives the gateway server already uses (`resolve_claude_runtime_home`, `copy_agent_skills`, `apply_claude_runtime_env`). Each agent gets a scoped `HOME` directory that the `claude` binary treats as its own — blocking global plugins while exposing only agent-specific skills.

## Isolation Model

Each `corvus chat --agent <name>` launches `claude` in a sandboxed filesystem:

```
.data/claude-home/users/cli/agents/{agent}/
├── .claude/
│   ├── .claude.json              ← seeded from config/claude-runtime/claude.json
│   └── skills/
│       ├── docker-operations.md  ← agent-specific skill
│       ├── loki-queries.md       ← agent-specific skill
│       └── memory.md             ← shared skill (opted in via agent.yaml)
├── .config/
├── .cache/
└── .local/{state,share}/
```

### What blocks global state

| Mechanism | What it blocks |
|-----------|---------------|
| `HOME` override | `~/.claude/` (global plugins, settings, session history) |
| `CLAUDE_CONFIG_DIR` override | Global Claude config directory |
| `XDG_*` overrides | Global cache, state, data dirs |
| `--setting-sources project` | User-level settings (only project-level loaded) |
| `--strict-mcp-config` | Global MCP server configurations |

### What each agent sees

| Resource | Visible? | How |
|----------|----------|-----|
| Agent-specific skills (`/docker-operations`) | Yes | `copy_agent_skills()` → `HOME/.claude/skills/` |
| Shared skills (`/memory`) | Yes | Opted in via `agent.yaml` metadata |
| Global plugins (`/superpowers`, `/frontend-design`) | No | Wrong `HOME` — invisible |
| Global MCP servers | No | `--strict-mcp-config` |
| LiteLLM model routing | Yes | `ANTHROPIC_BASE_URL` inherited in env |
| 6-layer system prompt (soul, identity, memory) | Yes | `--system-prompt` flag |
| Agent's tool whitelist | Yes | `--allowedTools` flag |

## Flow

```
corvus chat --agent homelab
    │
    ├── build_runtime()              ← ModelRouter, AgentsHub, MemoryHub
    ├── _start_litellm()             ← proxy on :4000, sets ANTHROPIC_BASE_URL
    ├── _prepare_isolated_env()
    │     ├── resolve_claude_runtime_home()
    │     ├── mkdir HOME/.claude/, XDG dirs
    │     ├── seed .claude.json from template
    │     ├── copy_agent_skills()     ← agent + shared skills → HOME/.claude/skills/
    │     └── return env dict with overrides
    │
    ├── _build_claude_cmd()
    │     ├── --system-prompt (6-layer composition)
    │     ├── --model (from ModelRouter via LiteLLM)
    │     ├── --permission-mode (from agent spec)
    │     ├── --allowedTools (from agent spec)
    │     ├── --setting-sources project
    │     └── --strict-mcp-config
    │
    └── subprocess.run(cmd, env=env)
```

## Changes Required

### `corvus/cli/chat.py`

- **Remove** `--disable-slash-commands` (blocks ALL skills including agent's own)
- **Add** `--setting-sources project` (blocks user-level, keeps project-level)
- Keep `--strict-mcp-config`, isolated env vars, `copy_agent_skills()` (already done)

### Skill file migration

Move repo-root `.claude/skills/` to per-agent and shared locations:

| Current location | New location | Reason |
|-----------------|--------------|--------|
| `.claude/skills/finance.md` | `config/agents/finance/skills/finance.md` | Agent-specific |
| `.claude/skills/email.md` | `config/agents/email/skills/email.md` | Agent-specific |
| `.claude/skills/music.md` | `config/agents/music/skills/music.md` | Agent-specific |
| `.claude/skills/paperless.md` | `config/agents/docs/skills/paperless.md` | Agent-specific |
| `.claude/skills/obsidian.md` | `config/agents/docs/skills/obsidian.md` | Agent-specific |
| `.claude/skills/memory.md` | `config/skills/shared/memory.md` | All agents |

### Agent YAML opt-in for shared skills

```yaml
# config/agents/homelab/agent.yaml
metadata:
  shared_skills:
    - memory
```

### No new files or abstractions

All functions already exist:
- `resolve_claude_runtime_home()` — `corvus/gateway/options.py`
- `copy_agent_skills()` — `corvus/gateway/workspace_runtime.py`
- `_prepare_isolated_env()` — `corvus/cli/chat.py`

## Agent Isolation Guarantees (Claude CLI Path)

- Agent A's skills, sessions, and config cannot leak into Agent B
- No global Claude Code plugins are accessible
- No global MCP servers are accessible
- Model routing goes through LiteLLM (not direct Anthropic API)
- System prompt is fully composed from agent config (not inherited)
- Tool permissions are scoped to the agent's spec

---

# ACP Agent Integration

## Overview

The Agent Client Protocol (ACP) is a JSON-RPC 2.0 bidirectional protocol over stdio, created by Zed Industries and standardized in 2025. It enables structured communication between a client (Corvus) and coding agents (Codex CLI, Gemini CLI, Claude Code, OpenCode, Pi).

ACP agents are a **second execution path** through the same isolation infrastructure. The gateway already isolates agents via `resolve_claude_runtime_home` + stripped environment. ACP adds a new enforcement adapter that uses ACP protocol callbacks (instead of Claude CLI flags) to enforce the same policies.

> **Important disambiguation:** There are two protocols both called "ACP". This design uses the **Zed/JetBrains Agent Client Protocol** (stdio, JSON-RPC 2.0), NOT IBM's Agent Communication Protocol (REST/HTTP, merged into A2A under Linux Foundation).

### Architecture

```
User message -> Router (Huginn) -> dispatch
    |
    |-- backend: claude  -> ClaudeSDKClient (existing path)
    |     |-- --allowedTools, --permission-mode, PreToolUse hooks
    |
    |-- backend: acp     -> CorvusACPClient (new path)
          |-- spawn agent subprocess (codex, gemini, etc.)
          |-- JSON-RPC 2.0 over stdio (NDJSON)
          |-- fs/, terminal/, permission callbacks enforce policy
```

Both paths share:
- `resolve_claude_runtime_home()` for workspace creation
- `prepare_isolated_env()` for environment stripping
- `CapabilityRegistry` for policy decisions
- `ConfirmQueue` for user-facing approval prompts
- Output sanitizer for secret redaction

**ACP agents are always sub-agents** — they inherit a restricted subset of their parent agent's permissions. They cannot escalate privileges.

### Dependency

```bash
uv pip install agent-client-protocol
```

The `agent-client-protocol` Python SDK (PyPI) provides Pydantic models for all ACP messages, async `Client` base class, `spawn_agent_process()`, and helper builders (`text_block()`, `update_tool_call()`, etc.).

---

## ACP Protocol Compliance

Corvus implements the **client side** of the Agent Client Protocol.

### Session Lifecycle

```
1. Spawn agent process (codex-acp, gemini, etc.)
2. initialize         -> negotiate protocol version + capabilities
3. session/new        -> create session with sandboxed cwd, no MCP servers
4. session/prompt     -> send user prompt as ContentBlock array
5. session/update     <- stream agent responses (notifications, no id)
6. fs/*, terminal/*   <- agent requests files/commands, we serve or deny
7. request_permission <- agent asks for explicit approval, we check policy
8. prompt response    <- turn completes with stopReason
9. session/cancel     -> interrupt if user cancels
10. terminate         -> graceful shutdown (close stdin -> SIGTERM -> SIGKILL)
```

### Client Capabilities (conditionally advertised)

Capabilities are advertised based on the parent agent's policy. If the parent agent has `Bash` denied, we don't advertise `terminal` capabilities — the ACP agent won't attempt terminal operations.

```json
{
  "protocolVersion": 1,
  "clientInfo": {"name": "corvus", "version": "1.0.0"},
  "capabilities": {
    "fs": {"readTextFile": true, "writeTextFile": true},
    "terminal": {"create": true, "output": true, "waitForExit": true,
                 "kill": true, "release": true}
  }
}
```

### ACP Agent Registry (config-driven)

```yaml
# config/acp_agents.yaml
agents:
  codex:
    command: "npx @zed-industries/codex-acp"
    default_permissions: approve-reads
  claude:
    command: "npx -y @zed-industries/claude-agent-acp"
    default_permissions: approve-reads
  gemini:
    command: "gemini"
    default_permissions: approve-reads
  opencode:
    command: "npx -y opencode-ai acp"
    default_permissions: deny-all
```

New agents added to this file are immediately available — no code changes needed.

### Agent Spec Configuration

Existing agents opt into ACP via their spec:

```yaml
# config/agents/homelab/agent.yaml
name: homelab
description: Home automation and infrastructure
models:
  preferred: codex-mini
backend: acp
metadata:
  acp_agent: codex
  acp_permissions: approve-reads
  shared_skills:
    - memory
```

### What Is NOT In Scope

- **Corvus as an ACP agent** (exposing Corvus to editors) — future work
- **MCP passthrough** — we send `mcpServers: []` always; ACP agents use only what we serve via `fs/` and `terminal/`

---

## ACP Session Management

ACP sessions are **not ephemeral**. They're tracked, persisted, and visible in the frontend just like Claude agent runs. Every tool call, file read, terminal command, and thought the ACP agent produces flows through Corvus's existing event pipeline.

### Event Translation Layer

ACP `session/update` notifications map to Corvus WebSocket events:

| ACP Update Kind | Corvus Event Type | Frontend Display |
|---|---|---|
| `agent_message_chunk` | `run_output_chunk` + `text` | Streaming response text |
| `agent_thought_chunk` | `thinking` | Reasoning/chain-of-thought panel |
| `tool_call` | `tool_use` | Tool call card (name, status, description) |
| `tool_call_update` | `tool_result` | Tool result (completed/failed + content) |
| `plan` | `task_progress` | Plan steps display |
| `available_commands_update` | `agent_status` | Agent capability changes |
| `current_mode_update` | `agent_status` | Mode change notification |

ACP client callbacks also emit trace events:

| ACP Client Callback | Corvus Trace Event |
|---|---|
| `read_text_file(path)` | `tool_use: {name: "Read", path: ...}` then `tool_result` |
| `write_text_file(path)` | `tool_use: {name: "Write", path: ...}` then `tool_result` |
| `create_terminal(cmd)` | `tool_use: {name: "Bash", command: ...}` then `tool_result` |
| `request_permission(...)` | `confirm_request` then user approve/deny then `confirm_result` |

The frontend sees **exactly the same event stream** whether the agent is Claude or Codex.

### Session State Tracking

```python
acp_session_state = {
    "corvus_session_id": "sess_abc",
    "corvus_run_id": "run_xyz",
    "acp_session_id": "acp_sess_123",
    "acp_agent": "codex",
    "parent_agent": "homelab",
    "process_pid": 12345,
    "status": "ready",  # uninitialized/ready/processing/cancelled
    "created_at": "2026-03-06T...",
    "last_prompt_at": "2026-03-06T...",
    "total_turns": 3,
    "conversation_tokens": {"input": 4200, "output": 1800},
}
```

### Session Resume

`session/load` is capability-dependent (agent must advertise `loadSession: true`):

1. Check if ACP agent process is still alive
2. If yes: `session/prompt` on existing session (multi-turn)
3. If dead: respawn process, attempt `session/load(acp_session_id)`
4. If load fails: `session/new` (fresh start, inject Corvus transcript as context)

### Protocol Visibility Guarantees

| Feature | Protocol Support | Notes |
|---|---|---|
| Streaming text | Yes | `agent_message_chunk` |
| Thinking/reasoning | Yes | `agent_thought_chunk` |
| Tool call visibility | Yes | `tool_call` + `tool_call_update` |
| File/terminal interception | Yes | `fs/*`, `terminal/*` — we serve these, 100% visibility |
| Permission prompts | Yes | `session/request_permission` |
| Session resume | Conditional | Depends on agent advertising `loadSession: true` |
| Cancel mid-turn | Yes | `session/cancel` notification |
| Token usage | Partial | Cumulative fields in session state, not guaranteed per-agent |
| Cost tracking | No | Estimated from token counts + model pricing |
| Context window % | No | Estimated from cumulative tokens vs known model limits |

For file operations and terminal commands we have **100% visibility** because the agent MUST ask Corvus. For agent thinking and tool calls, we see what the agent **chooses to report** via `session/update` — well-behaved agents (Codex, Claude, Gemini) emit rich updates.

### Example Trace

A single user message "fix the auth module" produces:

```
[dispatch]     -> homelab (routing)
[run_start]    -> homelab / codex (acp)
[thinking]     -> "I'll analyze the auth module..."
[tool_use]     -> Read corvus/auth.py
[tool_result]  -> (file content, 245 lines)
[thinking]     -> "The issue is in the JWT validation..."
[tool_use]     -> Write corvus/auth.py
[confirm]      -> "Codex wants to write auth.py (312 bytes)" -> user approves
[tool_result]  -> (write completed)
[tool_use]     -> Bash: python -m pytest tests/test_auth.py
[confirm]      -> "Codex wants to run: pytest tests/test_auth.py" -> user approves
[tool_result]  -> (3 passed, 0 failed)
[text]         -> "Fixed the JWT validation. All tests pass."
[run_complete] -> success, tokens: 6000, cost: ~$0.02
```

All visible in the frontend, scrollable, inspectable — identical to Claude runs.

---

## ACP Security: 7-Layer Defense-in-Depth

Core principle: **ACP agents inherit a restricted subset of their parent agent's permissions. Every layer works independently — if one fails, the others catch it.**

Effective policy = `parent_policy INTERSECT acp_restrictions` (intersection, not union).

### Layer 1: Process Environment Stripping

**When:** Agent process spawn, before any ACP messages.

Reuses `_prepare_isolated_env()` from the CLI isolation design.

```python
ALLOWED_ENV = {"PATH", "TERM", "LANG", "LC_ALL", "TMPDIR", "USER"}

env = {k: v for k, v in os.environ.items() if k in ALLOWED_ENV}
env["HOME"] = str(workspace_dir)
env["TMPDIR"] = str(workspace_dir / "tmp")
# Explicitly absent: ANTHROPIC_API_KEY, OPENAI_API_KEY,
# *_TOKEN, *_SECRET, CORVUS_*, DATABASE_URL, SOPS_*, AWS_*
```

**Blocks:** Secret exfiltration via `env`, `printenv`, `echo $VAR`, or any subprocess the agent spawns internally.

### Layer 2: Workspace Jail

**When:** `session/new` — we set the `cwd`.

```python
workspace = resolve_claude_runtime_home(
    base_home=runtime_home, scope=scope,
    user=user, agent_name=agent_name,
) / "workspace"
workspace.mkdir(parents=True, exist_ok=True)

await conn.new_session(cwd=str(workspace), mcp_servers=[])
```

`mcpServers: []` means the ACP agent gets **zero** external tool servers.

**Blocks:** Access to host filesystem, other agents' workspaces, Corvus config, `.env`, credentials.

### Layer 3: File Operation Gating

**When:** Every `fs/read_text_file` and `fs/write_text_file` request from the agent.

Checks (in order):

1. **Path resolution** — resolve symlinks, normalize to absolute path
2. **Boundary check** — is path under `workspace_root`? (blocks `../../` traversal)
3. **Secret pattern** — matches `.env`, `.pem`, `id_rsa`, `id_ed25519`, `.key`, `.secrets`?
4. **Parent policy** — does parent agent's CapabilityRegistry allow Read/Write?
5. **Confirm gate** — is Read/Write confirm-gated for this parent? Push to ConfirmQueue
6. **Content sanitize** — (reads only) redact any secret patterns in file content before serving

Every file operation emits a trace event regardless of approval/denial.

### Layer 4: Terminal Command Gating

**When:** Every `terminal/create` request.

Checks (in order):

1. **Parent policy** — does parent agent allow Bash at all?
2. **Command blocklist** — known dangerous patterns:
   - `curl|wget` (exfiltration/downloads)
   - `cat .env`, `printenv`, `env` (secret reads)
   - `echo $VAR` (variable exfiltration)
   - `nc|ncat|netcat|ssh|scp|sftp` (network access)
   - `docker` (container escape)
   - `sudo` (privilege escalation)
   - `rm -rf /` (destructive)
   - `chmod 777` (permission weakening)
   - `curl -d` (data exfiltration via POST)
3. **Always confirm** — terminal commands from ACP agents are ALWAYS confirm-gated (no auto-approve)
4. **Sandboxed exec** — runs with stripped env from Layer 1, workspace cwd from Layer 2
5. **Output capture** — stdout/stderr captured for trace display

### Layer 5: Permission Request Policy

**When:** Agent sends `session/request_permission`.

ACP tool kinds map to Corvus capability names:

| ACP Kind | Corvus Tool | Policy |
|---|---|---|
| `read` | `Read` | Check parent CapabilityRegistry |
| `search` | `Grep` | Check parent CapabilityRegistry |
| `edit` | `Write` | Check parent CapabilityRegistry |
| `delete` | `Write` | Treated as write |
| `move` | `Write` | Treated as write |
| `execute` | `Bash` | Check parent CapabilityRegistry |
| `fetch` | `WebFetch` | Check parent CapabilityRegistry |
| `think` | — | Always allowed |
| Unknown | — | **Denied by default** (deny-wins) |

### Layer 6: Output Sanitization

**When:** Every `session/update` notification before it reaches the parent agent or WebSocket.

Scans `agent_message_chunk` and `agent_thought_chunk` content for:
- Secret patterns (`api_key`, `token`, `secret`, `password`, `bearer`, `auth` followed by values)
- Base64-encoded keys (40+ character base64 strings)

Matched content replaced with `[REDACTED]`.

### Layer 7: Process Sandbox

**When:** Agent process spawn.

Two mechanisms:

**Restricted PATH** — only safe system binaries:

```python
env["PATH"] = "/usr/bin:/bin"
# Excludes /usr/local/bin (npm, pip, etc.)
```

**Network namespace isolation:**

```python
# Linux: unshare network namespace
cmd = ["unshare", "--net", "--map-root-user", *agent_cmd]

# macOS: sandbox-exec with no-network profile
cmd = ["sandbox-exec", "-p", SANDBOX_PROFILE, *agent_cmd]
```

The ACP agent process has **no network access**. It can only communicate with Corvus via its stdio pipes.

**Blocks:** Rogue subprocesses phoning home, installing packages, probing local network, reverse shells.

### Defense-in-Depth Matrix

| Attack Vector | L1 Env | L2 Jail | L3 Files | L4 Terminal | L5 Perms | L6 Output | L7 Sandbox |
|---|---|---|---|---|---|---|---|
| Read .env file | No vars | Not in workspace | Pattern blocked | `cat .env` blocked | Denied | Redacted | — |
| Exfiltrate via curl | No API keys | — | — | `curl` blocked | — | — | No network |
| Path traversal `../../` | — | cwd jailed | `.resolve()` + boundary | cwd jailed | — | — | — |
| Privilege escalation | No sudo/root | — | — | `sudo` blocked | Unknown denied | — | — |
| Leak via agent output | — | — | Content redacted | — | — | Output redacted | — |
| Spawn rogue subprocess | Clean env | Jailed cwd | — | — | — | — | No network, restricted PATH |
| Access other agent workspace | Wrong HOME | Different dir | Boundary check | Different cwd | — | — | — |
| Install malicious package | — | — | — | — | — | — | No network, restricted PATH |

Every attack vector has **at least 2 independent blocks**.

---

## Shared vs. Separate: Isolation Primitive Reuse

The same three functions power both Claude CLI isolation AND ACP agent isolation:

| Existing Function | Claude CLI Use | ACP Agent Use |
|---|---|---|
| `resolve_claude_runtime_home()` | Creates `HOME` for `claude` binary | Creates `cwd` + workspace boundary for ACP agent |
| `copy_agent_skills()` | Copies skills to `HOME/.claude/skills/` | Not used — ACP agents don't have Claude skills |
| `_prepare_isolated_env()` | Strips env vars, sets XDG overrides | Same stripped env passed to subprocess |

### Enforcement Comparison

| Enforcement | Claude CLI (existing) | ACP Agent (new) |
|---|---|---|
| Tool restrictions | `--allowedTools` flag | ACP client callbacks (our code) |
| MCP blocking | `--strict-mcp-config` | `mcpServers: []` in `session/new` |
| Skill scoping | `copy_agent_skills()` | N/A |
| Permission model | `--permission-mode` flag | `request_permission()` via CapabilityRegistry |
| Secret blocking | `PreToolUse` hook | `read_text_file()` / `create_terminal()` path checks |
| Output sanitization | `PostToolUse` hook | `session_update()` callback |

The ACP layer is **stricter** than Claude CLI because we validate every single file operation programmatically, rather than relying on the `claude` binary to respect flags.

---

## Integration with run_executor.py

### Branch Point

The run executor checks backend type and delegates:

```python
async def execute_agent_run(*, emitter, runtime, turn, route, ...):
    backend_name, active_model = resolve_backend_and_model(...)

    if backend_name == "acp":
        return await _execute_acp_run(
            emitter=emitter, runtime=runtime, turn=turn,
            route=route, route_index=route_index,
            # ... same args as Claude path
        )

    # Existing Claude SDK path (unchanged)
    async with ClaudeSDKClient(options=client_options) as client:
        ...
```

### What Stays The Same (no changes needed)

| Component | Why it works as-is |
|---|---|
| `SessionEmitter` | ACP path calls same `send()` with same event types |
| `SessionManager` | Same `start_agent_run()`, `update_agent_run()` calls |
| `ConfirmQueue` | ACP permission/confirm requests use same queue and frontend dialog |
| `dispatch_runtime.py` | Fan-out/cancellation logic doesn't care about backend type |
| `task_planner.py` | Route planning is backend-agnostic |
| Frontend WebSocket | Same event types — `run_output_chunk`, `tool_use`, `confirm_request` |

### New Components

| Component | Location | Purpose |
|---|---|---|
| `CorvusACPClient` | `corvus/acp/client.py` | ACP Client with 7-layer enforcement |
| `AcpAgentRegistry` | `corvus/acp/registry.py` | Load agent commands from `config/acp_agents.yaml` |
| `AcpSessionTracker` | `corvus/acp/session.py` | Track ACP session IDs, process PIDs, resume state |
| `_execute_acp_run` | `corvus/gateway/run_executor.py` | ACP execution path |
| `acp_agents.yaml` | `config/acp_agents.yaml` | Agent command registry |
| Backend type `acp` | `config/models.yaml` | New backend type in backends section |

---

## ACP Isolation Guarantees

All Claude CLI guarantees apply, plus:

- ACP agents inherit a **restricted subset** of their parent agent's permissions (never more)
- ACP agents **never** get `credential_store`, secret access, or break-glass elevation
- All `fs/` paths validated against workspace boundary (no traversal)
- All `terminal/` commands filtered against blocklist and **always** confirm-gated
- Agent processes run with **no network access** (unshare/sandbox-exec)
- Agent processes see **restricted PATH** and **empty environment** (no secrets)
- All agent output sanitized before reaching parent agent or WebSocket
- Deny always wins — if parent denies a capability, ACP agent cannot use it regardless of ACP protocol

---

## References

- [Agent Client Protocol Specification](https://agentclientprotocol.com/)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk) (`pip install agent-client-protocol`)
- [OpenClaw acpx](https://github.com/openclaw/acpx) — reference implementation (TypeScript)
- [ACP Protocol Schema](https://agentclientprotocol.com/protocol/schema)
- [Zed ACP](https://zed.dev/acp) — original creators
