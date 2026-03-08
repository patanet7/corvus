# Security Hardening & MCP Stdio Executor Design

**Date:** 2026-03-08
**Status:** Approved
**Scope:** Full security remediation (SEC-001 through SEC-027) + executor architecture redesign

---

## Overview

Replace the current Bash-based tool system with an in-process MCP stdio executor, implement a three-tier permission model with break-glass authentication, and remediate all 27 security findings from the Corvus security audit.

**Design principles:**
- Runtime-agnostic core — Claude CLI is one consumer, swappable via `RuntimeAdapter`
- Credentials never leave the Corvus process
- Double enforcement — our policy engine + CLI-level `permissions.deny`
- Hooks for side-effects (audit, summary, memory) — no extra LLM calls
- Per-agent tool isolation — agents only see tools they declare

---

## 1. MCP Stdio Executor Architecture

### Current State (to be replaced)
- `tool_server.py` — Unix socket + JWT auth
- `tool_token.py` — JWT token generation
- `hooks.py` — Bash blocklist (trivially bypassed)
- `Bash(python *)` in `--allowedTools` — tools executed as Bash wrappers
- Credentials serialized to env vars or socket payloads

### New Architecture

Corvus parent process serves as MCP stdio server using `create_sdk_mcp_server` from `claude-agent-sdk`. Claude CLI subprocess connects via stdio. No separate executor process.

```
┌─────────────────────────────────────────────────┐
│  Corvus Parent Process                          │
│                                                 │
│  ┌──────────────┐    ┌───────────────────────┐  │
│  │ Agent Spawner │───▶│ MCP Stdio Server      │  │
│  │ (chat.py)     │    │ (create_sdk_mcp_server)│  │
│  └──────┬───────┘    │                       │  │
│         │            │ ┌───────────────────┐ │  │
│         │            │ │ Tool Registry     │ │  │
│         │            │ │ (per-agent subset)│ │  │
│         │            │ └───────────────────┘ │  │
│         │            │ ┌───────────────────┐ │  │
│         │            │ │ ToolContext       │ │  │
│         │            │ │ - credentials     │ │  │
│         │            │ │ - permissions     │ │  │
│         │            │ │ - agent_name      │ │  │
│         │            │ └───────────────────┘ │  │
│         │            └───────────┬───────────┘  │
│         │                        │ stdio        │
│         ▼                        ▼              │
│  ┌─────────────────────────────────────┐        │
│  │ Claude CLI subprocess              │        │
│  │ --mcp-config (stdio server)        │        │
│  │ --system-prompt (minimal)          │        │
│  │ CLAUDE.md (tool docs + skills)     │        │
│  │ settings.json (permissions.deny)   │        │
│  └─────────────────────────────────────┘        │
└─────────────────────────────────────────────────┘
```

### Files Deleted
- `corvus/cli/tool_server.py` — replaced by in-process MCP stdio
- `corvus/cli/tool_token.py` — no longer needed (no JWT auth between processes)
- `corvus/hooks.py` — Bash blocklist replaced by permissions.deny + no Bash access

### Runtime Portability

CLI-specific concerns isolated behind a `RuntimeAdapter` protocol:

```python
class RuntimeAdapter(Protocol):
    def compose_permissions(self, tier: PermissionTier, policy: Policy) -> dict: ...
    def build_launch_cmd(self, workspace: Path, mcp_config: dict) -> list[str]: ...
    def inject_system_prompt(self, prompt: str) -> dict: ...

class ClaudeCodeAdapter(RuntimeAdapter): ...
```

All other layers (tool registry, policy engine, credential store, workspace composition) are runtime-agnostic.

| Layer | Portable? | Notes |
|-------|-----------|-------|
| MCP stdio tool server | Yes | Standard protocol |
| Tool registry + ToolContext | Yes | Pure Python |
| Policy engine (policy.yaml) | Yes | Our own system |
| Credential store + injection | Yes | Our own system |
| Workspace composition | Yes | Generates directories |
| `permissions.deny` in settings.json | CLI-specific | Thin adapter |
| `--system-prompt` / `--mcp-config` flags | CLI-specific | Thin adapter |

---

## 2. Permission & Policy Engine

### Three-Tier Model

```yaml
# policy.yaml — global source of truth
global_deny:
  - "*.env*"
  - "*.ssh/*"
  - "*credentials*"
  - "*/secrets/*"

tiers:
  strict:
    mode: allowlist
    confirm_default: deny

  default:
    mode: allowlist_with_baseline
    confirm_default: deny

  break_glass:
    mode: allow_all
    confirm_default: allow
    requires_auth: true
    token_ttl: 3600   # 1h default
    max_ttl: 14400    # 4h max
```

### Per-Agent Overlay

Agent YAML declares tool modules, permission tier, confirm-gated tools, and extra denies:

```yaml
# config/agents/homelab/agent.yaml
tools:
  modules:
    ha: { call_service: true, get_states: true }
    memory: { store: true, recall: true }
  permission_tier: default
  confirm_gated:
    - ha.call_service
  extra_deny:
    - "ha.restart_*"
```

### Composition at Spawn Time

```
global_deny (policy.yaml)
  + tier baseline (strict/default/break_glass)
  + agent extra_deny (agent.yaml)
  + agent confirm_gated (agent.yaml)
  ─────────────────────────────
  = Final permissions.deny (settings.json)  ← CLI-specific adapter
  = Final tool registrations (MCP server)   ← runtime-agnostic
  = Final ToolContext.permissions            ← runtime-agnostic
```

### Double Enforcement

1. **Our layer** — MCP tool handlers check `ToolContext.permissions` before executing. Works with ANY runtime.
2. **CLI layer** — `permissions.deny` in `settings.json` as defense-in-depth. Claude CLI won't even ask to use denied patterns.

If the CLI goes away, enforcement layer 1 still holds.

---

## 3. Break-Glass Authentication

### Flow

```
User requests break-glass → Password prompt (CLI or WebSocket challenge)
  → Argon2id verify (existing break_glass.py + escalating lockout)
  → Generate session token (HMAC-SHA256, 1h TTL, session-bound)
  → Agent spawns with tier: break_glass
  → On TTL expiry: drop to default tier (session stays alive)
```

### Token Properties
- **HMAC-SHA256 signed** by Corvus server secret
- **1h TTL** default, configurable up to 4h max
- **Bound to agent_name + session_id** — no reuse across agents/sessions
- **Validated on every tool call** in ToolContext

### Changes from Current System
- **Keep:** Argon2id verification, escalating lockout (3 fails → 30s, 5 → 5min)
- **Add:** Token generation (HMAC-SHA256, TTL, session-bound)
- **Add:** Token validation middleware in tool handlers
- **Remove:** `CORVUS_BREAK_GLASS` env var check in `config.py:41` (SEC-013)

### Graceful Degradation
When token expires:
- Session stays alive
- Tier drops to `default`
- Tools re-check permissions against default tier
- User notified: "Break-glass expired, reverting to default permissions"
- Must re-authenticate for break-glass again

---

## 4. Credential Injection & ToolContext

### ToolContext

Passed to every tool handler at invocation:

```python
@dataclass
class ToolContext:
    agent_name: str
    session_id: str
    permission_tier: PermissionTier  # strict | default | break_glass
    credentials: dict[str, str]      # pre-resolved from declared deps
    permissions: ToolPermissions     # resolved deny/allow/confirm sets
    break_glass_token: str | None    # if break-glass active
```

### Tool Registration with Credential Declaration

```python
class ObsidianSearchTool:
    name = "obsidian_search"
    description = "Search notes"  # ~30 tokens, minimal
    requires_credentials = ["OBSIDIAN_URL", "OBSIDIAN_API_KEY"]

    async def execute(self, ctx: ToolContext, query: str) -> str:
        client = ObsidianClient(
            url=ctx.credentials["OBSIDIAN_URL"],
            api_key=ctx.credentials["OBSIDIAN_API_KEY"],
        )
        return await client.search(query)
```

### Resolution Flow

```
Agent YAML declares tools.modules.obsidian
  → Registry looks up ObsidianSearchTool
  → Reads requires_credentials: ["OBSIDIAN_URL", "OBSIDIAN_API_KEY"]
  → Credential store resolves values
  → Values injected into ToolContext.credentials
  → Tool handler receives ctx — never touches env vars or global state
```

### Security Properties
- Tool A cannot read Tool B's credentials (only declared deps injected)
- No `os.environ` access needed in tool code
- Credential store is the single audit point
- Missing credential → spawn fails loudly, not runtime crash

### Environment Whitelist

Replaces `_SENSITIVE_VARS` blocklist:

```python
_ALLOWED_ENV = [
    "PATH", "HOME", "SHELL", "TERM", "LANG",
    "ANTHROPIC_BASE_URL",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
]
```

Claude CLI subprocess gets ONLY these. Credentials flow through ToolContext in-process, never through env vars to the subprocess.

---

## 5. Workspace Composition

### Purpose-Built Directory

No project snapshot. Corvus generates a minimal workspace per session:

```
/tmp/corvus-workspaces/
  └── {agent_name}-{session_id}/
      ├── .claude/
      │   ├── settings.json      # permissions.deny (composed)
      │   └── CLAUDE.md          # tool docs + skills + instructions
      ├── skills/                # only skills this agent needs
      │   ├── memory-workflow.md
      │   └── obsidian-search.md
      └── (no source code, no .env, no config/)
```

### CLAUDE.md Composition (6 layers)

1. Soul (base personality)
2. Agent soul (domain personality)
3. Identity (name, description, capabilities)
4. Tool documentation (detailed usage for each registered MCP tool)
5. Skill instructions (workflow guidance)
6. Sibling awareness + memory seed

### settings.json Composition

```json
{
  "permissions": {
    "deny": ["*.env*", "*.ssh/*", "*credentials*", "ha.restart_*"]
  },
  "enabledPlugins": {},
  "strictKnownMarketplaces": []
}
```

### SEC-002 Fix
- No `.env` files in workspace
- No `config/` directory
- No project root CLAUDE.md
- No source code (tools run in-process)
- Marketplace/plugins disabled
- Workspace deleted on session end

---

## 6. Session Lifecycle & Summarization

### Lifecycle Stages

```
1. SPAWN → resolve spec, policy, credentials, compose workspace, register tools, start CLI
2. EXECUTE → tool calls via MCP stdio, permissions checked per call, hooks fire
3. SUMMARIZE → on_session_end hook builds summary from audit trail
4. CLEANUP → delete workspace, tear down MCP server, invalidate tokens, log duration
```

### Hook-Driven Side-Effects

```yaml
hooks:
  on_session_end:
    - action: summarize_session
      store_to: memory
      surface_to: chat_ui

  on_tool_call:
    - action: audit_log

  on_memory_write:
    - action: index_memory

  on_mutation:
    - action: record_mutation
```

### Summary Structure

```python
@dataclass
class SessionSummary:
    agent_name: str
    session_id: str
    started_at: datetime
    ended_at: datetime
    user_request: str
    actions_taken: list[str]
    tools_used: list[ToolCall]
    mutations: list[str]
    memory_writes: list[str]
    outcome: str               # success | partial | failed
    next_steps: list[str]
```

### How Summary Gets Built

Corvus builds the summary from hook-captured audit data during the session — **no extra LLM call**. The agent doesn't summarize itself. Tool calls, mutations, and memory writes are already captured by `on_tool_call`, `on_mutation`, and `on_memory_write` hooks.

The conversation transcript can optionally be compressed and stored, but the structured summary comes from hooks — fast, cheap, deterministic.

---

## 7. Context Window Optimization

### Strategy 1: Per-Agent Tool Registration

Agent YAML declares `tools.modules`. MCP server only registers those tools for that agent. ~5-8 tools per agent instead of 30+.

### Strategy 2: Minimal MCP Descriptions + CLAUDE.md Detail

MCP tool descriptions kept to ~30 tokens each (name + one-liner). Detailed usage instructions, examples, and parameter docs go in CLAUDE.md.

### Future: Tool Search API

For large tool catalogs, Claude queries a tool catalog on-demand rather than loading all schemas into context. Triggered when tool count exceeds a configurable threshold.

---

## 8. Security Remediation Map

| SEC | Issue | Fix |
|-----|-------|-----|
| 001 | Bash blocklist trivially bypassed | Bash removed. Tools are native MCP. `permissions.deny` at CLI level. |
| 002 | Workspace snapshot leaks secrets | Purpose-built workspace. No .env, no config/, no source. |
| 003 | Confirm queue auto-allows | Deny-default. Allow only in authenticated break-glass. |
| 004 | `parent_allows_*` hardcoded True | Policy engine — tier determines permissions. |
| 005 | Darwin sandbox `allow default` | Subprocess gets env whitelist only. Tools run in-process. |
| 006 | No tool-call audit | `on_tool_call` hook logs every invocation. |
| 007 | WebSocket auto-auth localhost | Needs auth middleware (flagged for separate follow-up). |
| 008 | No rate limiting on tools | ToolContext can enforce rate limits per tool per session. |
| 009 | Cross-domain memory write | ToolContext.permissions enforces domain isolation. |
| 010 | Skills lack integrity check | Skills copied to workspace at spawn — Corvus controls what gets copied. |
| 011 | No session timeout | TTL on sessions (configurable). Hooks clean up on expiry. |
| 012 | Tool results unvalidated | MCP tools return typed responses. Corvus validates before forwarding. |
| 013 | Break-glass via env var | Env var removed. Password-only with time-limited token. |
| 014-027 | Various | Policy engine, ToolContext isolation, env whitelist, audit hooks, workspace composition. |

---

## Key Decisions Summary

| Decision | Choice |
|----------|--------|
| Executor model | MCP stdio in-process (Corvus IS the server) |
| Tool registration | Per-agent (only declared tools) |
| Context window | Minimal MCP descriptions + CLAUDE.md detail |
| Policy structure | Global `policy.yaml` + per-agent YAML overrides |
| Break-glass | Password (Argon2id) → 1h time-limited token |
| Permission enforcement | `permissions.deny` dynamically composed per tier |
| Workspace | Purpose-built directory (not snapshot) |
| Confirm queue default | Deny-default, allow only in break-glass |
| Credential access | ToolContext with pre-resolved declared dependencies |
| Summarization | Hook-driven from audit trail, no extra LLM call |
| Runtime portability | RuntimeAdapter protocol, CLI is swappable |
| Future scaling | Tool Search API for large catalogs |
