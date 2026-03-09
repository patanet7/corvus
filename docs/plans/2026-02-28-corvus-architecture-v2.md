# Corvus Architecture v2 -- Unified System Design

> **Date:** 2026-02-28
> **Status:** Approved design -- supersedes ARCHITECTURE.md and docs/general.md
> **Scope:** Complete system architecture for Corvus (formerly Claw), covering Agent Gateway, Memory Hub, Capabilities Hub, security model, observability, scheduling, and developer experience.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Terminology Guide](#2-terminology-guide) — Corvus concepts + SDK boundary mapping
3. [Claude Agent SDK Mapping](#3-claude-agent-sdk-mapping) — All hooks, options, permissions, confirm-gating
4. [Agent Gateway](#4-agent-gateway)
5. [Memory Hub](#5-memory-hub)
6. [Capabilities Hub](#6-capabilities-hub)
7. [Security Model](#7-security-model)
8. [Observability](#8-observability) — Security event stream, metrics, alerting
9. [Scheduling and Background Tasks](#9-scheduling-and-background-tasks)
10. [Module Contracts](#10-module-contracts) — All type definitions, concurrency model, failure modes, startup ordering
11. [Developer Experience](#11-developer-experience)
12. [Evolution Path](#12-evolution-path)

---

## 1. System Overview

Corvus is a local-first, self-hosted, security-first multi-agent system. A single chat surface routes into domain-specific agents (personal, work, homelab, finance, email, docs, music, home, general), each with isolated tool policies, memory domains, and vault paths.

### 1.1 High-Level Architecture

```
                          Internet
                            |
                     SWAG (optiplex)
                            |
                     Authelia SSO
                            |
    +-----------------------v-----------------------+
    |              AGENT GATEWAY                     |
    |         FastAPI + WebSocket (:18789)            |
    |                                                |
    |  RouterAgent -----> Intent Classification      |
    |       |              (Claude Haiku, ~20 tok)    |
    |       v                                        |
    |  Agent Dispatch -----> 9 Domain Subagents      |
    |       |                                        |
    |  +----v-----------+  +-----------+  +--------+ |
    |  +--------+ +------------+ +----------+ +--------+ |
    |  |AGENTS  | |CAPABILITIES| |  MEMORY  | | HOOKS  | |
    |  |HUB     | |HUB         | |  HUB     | |        | |
    |  |        | |            | |          | | Pre/   | |
    |  |Defini- | |Tool Modules| | Primary: | | Post   | |
    |  |tions:  | | obsidian   | |  FTS5    | | Tool   | |
    |  | YAML   | | email      | | Overlays:| | Use    | |
    |  | + DB   | | drive      | |  cognee  | |        | |
    |  |Live    | | paperless  | |  vec     | | Stop   | |
    |  |reload  | | firefly    | |  corpgen | | Hook   | |
    |  |        | | ha         | |          | +--------+ |
    |  +--------+ +------------+ +----------+            |
    |       |                    |                    |
    |  +----v--------------------v---------+         |
    |  | INFRASTRUCTURE                    |         |
    |  |                                   |         |
    |  |  CredentialStore (SOPS+age)       |         |
    |  |  AgentRegistry (YAML+DB)         |         |
    |  |  ToolProviderRegistry             |         |
    |  |  AgentSupervisor (heartbeat)      |         |
    |  |  CronScheduler (APScheduler)      |         |
    |  |  EventEmitter -> JSONL -> Loki    |         |
    |  |  ModelRouter (per-agent backends)  |         |
    |  +-----------------------------------+         |
    +------------------------------------------------+
              |              |              |
     Obsidian Vault    SQLite DBs     External APIs
    (/mnt/vaults)    (/data/memory)   (Paperless, HA,
                                       Firefly, Gmail)
```

### 1.2 Core Invariants

These are non-negotiable. If code contradicts these, the code is wrong.

1. **100% Python.** No Node.js, no TypeScript, no additional runtimes.
2. **No secrets in prompts, tool args, tool output, memory, logs, or workspace files.** Ever.
3. **No mocks in tests.** Real databases, real files, real HTTP. Behavioral contracts only.
4. **Default-deny tooling.** Agents get only the tools they need. Deny wins over allow.
5. **Identity via closures, not env vars.** Agent identity is baked at spawn time.
6. **Primary always works.** If all overlays fail, the system still functions on FTS5.
7. **Modules, not plugins.** SDK plugins create namespace packages (`.claude-plugin/`). Corvus extensions are "modules" — `ToolModule` protocol, not SDK plugin manifests. Future PyPI distribution uses Python entry points, not SDK plugins. See Section 2.2 for full naming boundary.

### 1.3 Component Boundaries

```
+----------------+ +----------------+ +----------------+ +----------------+
| AGENT GATEWAY  | | AGENTS HUB     | | MEMORY HUB     | | CAPABILITIES   |
|                | |                | |                | | HUB            |
| Owns:          | | Owns:          | | Owns:          | | Owns:          |
|  - Routing     | |  - Agent defs  | |  - MemoryRecord| |  - Tool reg.   |
|  - Session mgmt| |  - YAML+DB    | |  - Search/merge| |  - Tool policy |
|  - Auth        | |  - Live reload | |  - Temporal    | |  - Sanitization|
|  - Webhooks    | |  - Permissions | |    decay       | |  - Confirm-gate|
|                | |  - Prompts     | |  - Visibility  | |  - Health chks |
|                | |  - Tool assign.| |  - Audit trail | |                |
|                | |  - Model assign| |  - Pruner      | |                |
|                | | USER-FACING:   | |                | |                |
| Depends on:    | | create/edit    | |                | | Depends on:    |
|  Agents Hub    | |                | |                | |  CredentialStore|
|  Memory Hub    | | Depends on:    | | Depends on:    | |  Agents Hub    |
|  Capabilities  | |  CredentialStor| |  Agents Hub    | |                |
+----------------+ +----------------+ +----------------+ +----------------+
         |                |                   |                   |
         +--------+-------+--------+----------+--------+----------+
                  |                |                    |
          +-------v-------+ +-----v-------+    +-------v-------+
          | CREDENTIAL    | | AGENT       |    | EVENT         |
          | STORE         | | REGISTRY    |    | EMITTER       |
          | (SOPS+age)    | | (YAML+DB)   |    | (JSONL->Loki) |
          +---------------+ +-------------+    +---------------+
```

### 1.4 Data Flow: Chat Message Lifecycle

```
User Message
    |
    v
1. WebSocket /ws receives message (or POST /api/agents/{name}/spawn)
    |
    +--- Auto-route (default):              Direct spawn (user picks agent):
    |    AgentsHub.route(message)            AgentsHub.spawn("finance")
    |      a. Read enabled agents             a. Skip classification
    |      b. Classify [Haiku, ~20 tokens]    b. AgentsHub.get("finance")
    |      c. Get spec + build definition     c. Build definition
    |                                   |
    +-----------------------------------+
    |
2. ClaudeSDKClient.query(message)
    |
    +---> PreToolUse hook: block .env reads, enforce confirm-gating
    |
    +---> Tool execution (thin proxy -> Capabilities Hub dispatch)
    |         |
    |         +---> Per-turn resolution: registry lookup + policy eval
    |         +---> Cascading deny-wins policy (5 layers)
    |         +---> sanitize() redacts any credential leaks
    |
    +---> PostToolUse hook: emit structured event to JSONL
    |
3. Response streamed back to WebSocket
    |
4. On disconnect: Stop hook extracts memories -> Memory Hub
```

---

## 2. Terminology Guide

Precise terminology prevents confusion between Corvus concepts and SDK primitives. The Claude Agent SDK uses many of the same words (Agent, Tool, Skill, Hook, Plugin) with different meanings. This section defines the boundary.

### 2.1 Corvus Concepts

| Term | Meaning | NOT |
|------|---------|-----|
| **Module** | A Corvus extension unit (tool module, memory module). First-class concept. | Not "plugin" -- SDK uses that word for namespace-creating packages |
| **Hub** | A coordinator that owns a subsystem (Agents Hub, Memory Hub, Capabilities Hub). Hubs enforce policy, manage lifecycle, and expose APIs. | Not a passive registry -- Hubs are active orchestrators |
| **Gateway** | The entry point: FastAPI + WebSocket + routing + auth | Not a proxy -- it actively orchestrates |
| **Agent Spec** | A data-driven agent config (YAML or DB) -- description, prompt, tools, permissions. Corvus's representation. | Not hard-coded in Python. Not an SDK `AgentDefinition` (that is what we build FROM the spec). |
| **Backend** | A storage implementation (FTS5 backend, Cognee backend) | Not a model provider -- that is a "provider" |
| **Provider** | An LLM model backend (Claude, Ollama, Kimi) | Not a tool backend |
| **Tool Module** | A set of related tools behind a service API (obsidian, email). Implements `ToolModule` protocol. | Not an SDK plugin. Not a standalone MCP server. |
| **Memory Module** | An overlay backend for the Memory Hub | Not an SDK plugin |
| **Toolkit** | SDK tools with closure-injected identity (MemoryToolkit) | Not a generic utility library |
| **Overlay** | An optional memory backend that augments the primary | Not a replacement -- primary always works |
| **Huginn** | Branding for routing/agents layer (docs/README only) | Not in code |
| **Muninn** | Branding for memory/knowledge layer (docs/README only) | Not in code |

### 2.2 SDK Term ↔ Corvus Term Boundary

The Claude Agent SDK provides primitives. Corvus wraps them with its own abstractions. This table shows exactly where each SDK concept lives in Corvus and what Corvus calls it.

| SDK Term | SDK Meaning | Corvus Wrapper | Boundary |
|----------|------------|----------------|----------|
| `ClaudeSDKClient` | Stateful multi-turn agent session. Manages tool execution, context, streaming. | **Gateway** creates one per WebSocket session. Not exposed to Corvus modules. | Gateway owns the client lifecycle. Modules never see or touch it. |
| `ClaudeAgentOptions` | Configuration object: system prompt, tools, MCP servers, hooks, permissions, model. | **Gateway** builds this from `AgentSpec` + Hub lookups at session creation. | Corvus config is `AgentSpec` (YAML). `ClaudeAgentOptions` is an SDK output format, not an input. |
| `AgentDefinition` | Subagent spec: description, prompt, tools, model. Used by SDK to route `Task` tool calls. | **Agents Hub** builds these from `AgentSpec` data. One per domain agent. | Corvus owns the definition data (YAML+DB). SDK just consumes the built `AgentDefinition`. |
| `HookMatcher` | Event filter: regex pattern + callback list. Routes hook events to handlers. | **Gateway** constructs matchers at startup from Corvus hook config. | Corvus defines WHICH hooks fire (Section 3.3). SDK provides the execution mechanism. |
| `McpServerConfig` / `create_sdk_mcp_server` | MCP server registration: stdio, SSE, HTTP, or in-process SDK servers. | **Capabilities Hub** creates in-process MCP servers per tool module. Each server = one module's tools for one agent. | Corvus never uses external MCP servers for its own tools (except Gmail MCP and HA MCP). All domain tools are in-process SDK MCP servers. |
| `Tool` (SDK built-in) | Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Task, etc. | **Agent Spec** allowlists which built-in tools each agent gets. Listed under `tools.builtin`. | SDK provides the tool implementations. Corvus only controls which agents can use which built-ins. |
| `@tool` decorator | Defines a custom MCP tool with name, description, input schema. | **Tool Modules** define their tools as methods. `CapabilitiesHub.create_proxy_tools()` wraps them in `@tool` proxies. | Module methods are the real implementation. `@tool` is the SDK registration mechanism. |
| `Skill` (SDK) | A slash command from `.claude/skills/SKILL.md`. Loads prompt, hooks, permissions. | **Not directly used.** Corvus's per-agent prompt files serve a similar purpose but are loaded via `AgentSpec.prompt_file`, not the SDK skill mechanism. | If SDK skills are used in the future, they complement (not replace) agent prompts. |
| `Plugin` (SDK) | A namespace package from `.claude-plugin/plugin.json`. Contains commands, agents, skills, hooks, MCP servers. | **Not used.** Corvus uses "modules" instead. SDK plugins create namespace prefixes that conflict with Corvus's MCP naming. | Corvus modules are NOT SDK plugins. Future `corvus-obsidian` PyPI packages use Python entry points, not SDK plugin manifests. |
| `Hook` (SDK) | Event callback: PreToolUse, PostToolUse, Stop, etc. Runs synchronously in the agent loop. | **Corvus Hooks** (Section 3.3) use SDK hook callbacks but add Corvus-specific behavior: security blocking, confirm-gating, telemetry, memory extraction. | SDK provides the hook dispatch mechanism. Corvus defines the hook implementations and adds custom hook types. |
| `Session` (SDK) | Conversation state: message history, tool results, context window. Can be resumed or forked. | **Gateway** manages session lifecycle tied to WebSocket connections. Session IDs track conversations. | Corvus adds session metadata (agent used, cost, timestamps) beyond what the SDK tracks. |
| `PermissionMode` | Global permission level: default, acceptEdits, plan, bypassPermissions. | **Agent Spec** sets per-agent permission mode. Break-glass mode uses `set_permission_mode()` dynamically. | Corvus wraps SDK permission modes with its own cascading policy (Section 6.4) that is finer-grained. |
| `canUseTool` callback | Human-in-the-loop permission check. Called when a tool isn't auto-allowed. | **Confirm-gating** in Section 6.7 uses this callback for destructive operations (Gmail send, HA service calls, financial transactions). | SDK provides the callback mechanism. Corvus defines WHICH tools need confirmation via agent spec YAML. |
| `ResultMessage` | Final message with cost, duration, token usage, session ID. | **Gateway** uses this for telemetry: `total_cost_usd`, `usage`, `num_turns` → EventEmitter → JSONL → Loki. | Corvus extracts metrics from ResultMessage; does not modify the SDK type. |
| `StreamEvent` | Partial message for token-level streaming (requires `include_partial_messages=True`). | **Gateway** can forward stream events to WebSocket for real-time UI updates. | Corvus passes through; does not modify stream events. |
| `output_format` | Structured JSON output with schema validation. Agent returns validated JSON. | **Memory extraction** can use Pydantic schemas for guaranteed structure (planned). | Corvus defines the schemas; SDK validates and retries. |
| `SandboxSettings` | OS-level sandbox: network restrictions, command exclusions. | **Per-agent sandbox** configured in agent spec. Homelab agent gets network access; finance agent gets restricted. | Corvus sets sandbox settings per agent; SDK enforces them at OS level. |

### 2.3 Key Naming Rules

1. **"Agent" in Corvus = data definition.** An `AgentSpec` in YAML. NOT a running process, NOT an SDK `Agent` class.
2. **"Module" in Corvus = extension unit.** A `ToolModule` or memory backend. NOT an SDK "plugin."
3. **"Hub" in Corvus = active coordinator.** Enforces policy, manages lifecycle, exposes API. NOT a passive dict/registry.
4. **"Toolkit" in Corvus = SDK tool closures.** Functions with baked-in identity. NOT a utility library.
5. **When wrapping SDK types, Corvus adds a prefix or different name.** `AgentSpec` wraps `AgentDefinition`. `ToolModule` wraps `@tool`. `Corvus Hook` wraps `HookMatcher`. This prevents import confusion.
6. **"Plugin" is reserved for future PyPI distribution.** `corvus-obsidian`, `corvus-email` etc. -- Python packages using `[corvus.plugins.tools]` entry points. NOT SDK `.claude-plugin` packages.

---

## 3. Claude Agent SDK Mapping

The Claude Agent SDK (`claude-agent-sdk` on PyPI) provides primitives. Here is how Corvus uses each.

### 3.1 SDK Primitives Used

| SDK Primitive | Corvus Usage | Why |
|--------------|-------------|-----|
| `ClaudeSDKClient` | Gateway wraps one client per WebSocket session. Uses `query()`, `receive_messages()`, `interrupt()`, `disconnect()`. | Core agent loop -- stateful, multi-turn, supports interruption. |
| `ClaudeAgentOptions` | Configures system prompt, subagents, MCP servers, hooks, model, permissions, sandbox, budget. Built from `AgentSpec` at session creation. | Single options object per session. See 3.1.1 for all fields used. |
| `AgentDefinition` | Built from AgentSpec at session creation (Agents Hub). One per domain agent. | SDK routes `Task` tool calls based on description field. |
| `HookMatcher` | All 10 hook events (Section 3.3). Security, telemetry, memory extraction, confirm-gating, lifecycle tracking. | Intercept every tool call, session event, and agent lifecycle event. |
| `create_sdk_mcp_server` | In-process MCP servers for each tool module. `@tool` decorator for proxy tools. | Credential isolation: closure captures secrets, agent never sees them. |
| Built-in tools | Bash, Read, Write, Edit, Glob, Grep — per agent spec allowlist. | Battle-tested file/shell operations. |
| `canUseTool` callback | Bridges confirm-gated tools to WebSocket for user approval. | Human-in-the-loop for destructive operations (Gmail send, HA service calls, financial transactions). |
| `ResultMessage` | Extracts `total_cost_usd`, `usage`, `num_turns`, `session_id` for telemetry. | Cost tracking, per-agent metrics, budget enforcement. |
| `SandboxSettings` | Per-agent sandbox configuration. Homelab gets network; finance gets restricted. | OS-level isolation per agent. |
| `set_permission_mode()` | Dynamic permission escalation for break-glass mode. | Upgrade to `bypassPermissions` temporarily, then revert. |
| `interrupt()` | Cancel agent execution mid-task from WebSocket disconnect or user action. | Clean cancellation without losing session state. |
| `StreamEvent` | Token-level streaming forwarded to WebSocket for real-time UI. | Live typing indicator in chat interface. |

#### 3.1.1 ClaudeAgentOptions — Fields Used by Corvus

```python
# Built by Gateway.build_options(agent_spec) at session creation

options = ClaudeAgentOptions(
    # --- Agent Identity ---
    system_prompt=agent_spec.prompt,               # Per-agent prompt from YAML/DB
    agents=agents_hub.build_definitions(),          # 9 domain subagents as AgentDefinitions

    # --- Tools ---
    tools=agent_spec.builtin_tools,                # ["Bash", "Read", ...] from spec
    allowed_tools=agent_spec.allowed_tools,         # Full allowlist including MCP proxies
    disallowed_tools=agent_spec.disallowed_tools,   # Explicit deny list (cascading policy)
    mcp_servers=capabilities_hub.build_servers(agent_spec),  # In-process MCP per module

    # --- Permissions ---
    permission_mode=agent_spec.permission_mode,     # "default" for most; "acceptEdits" for homelab
    can_use_tool=confirm_gate_callback,             # Bridges to WebSocket for user approval

    # --- Hooks ---
    hooks=build_hooks(agent_spec),                  # All 10 hook events (Section 3.3)

    # --- Model ---
    model=agent_spec.model,                         # "claude-sonnet-4-6" or per-agent override
    fallback_model=agent_spec.fallback_model,       # "claude-haiku-4-5-20251001" for rate limits

    # --- Cost Control ---
    max_turns=agent_spec.max_turns,                 # Per-session turn limit (default: 50)
    max_budget_usd=agent_spec.max_budget_usd,       # Per-session spending cap (default: 1.00)

    # --- Extended Thinking ---
    effort=agent_spec.effort,                       # "low" for triage, "high" for homelab ops

    # --- Sandbox ---
    sandbox=build_sandbox(agent_spec),              # Per-agent sandbox settings

    # --- Streaming ---
    include_partial_messages=True,                  # Enable token-level streaming for UI

    # --- Working Directory ---
    cwd=agent_spec.cwd or "/app",
    add_dirs=agent_spec.additional_dirs,            # Extra paths (vault, scripts, infra)

    # --- Environment ---
    env={"MEMORY_AGENT": agent_spec.name},          # Legacy compat (being replaced by closures)

    # --- Session ---
    continue_conversation=False,                    # New session per WebSocket connect
    # resume=session_id,                            # Used for session restoration (planned)
    # fork_session=True,                            # Used for "what-if" branches (planned)

    # --- Beta Features ---
    # betas=["context-1m-2025-08-07"],              # 1M context window (planned for long sessions)

    # --- Structured Output ---
    # output_format=memory_schema,                  # Planned for memory extraction
)
```

### 3.2 SDK Primitives NOT Used (and Why)

| SDK Primitive | Status | Rationale |
|--------------|--------|-----------|
| `Agent` class | Not used | Corvus does not run persistent agent processes. Agents are data (YAML+DB), converted to `AgentDefinition` at session creation. |
| SDK Plugins (`.claude-plugin/`) | Not used | SDK plugins create namespace prefixes that conflict with Corvus MCP naming. Corvus uses "modules" instead. Future PyPI distribution uses Python entry points, not SDK plugin manifests. |
| `query()` (stateless) | Not used | Corvus uses `ClaudeSDKClient` (stateful) for multi-turn sessions. The stateless `query()` function loses conversation context. |
| SDK Skills (`.claude/skills/`) | Not used directly | Corvus loads per-agent prompts via `AgentSpec.prompt_file`, not the SDK skill mechanism. May use SDK skills in the future for the setup wizard. |
| `rewind_files()` | Not used | File checkpointing is available but not critical for Corvus's use cases (agents don't make risky file edits). |
| Built-in memory | N/A | SDK has no built-in memory. Corvus provides its own Memory Hub. |
| Streaming input (async generator) | Not used | WebSocket messages come one at a time. Streaming input would be useful for multi-modal input (images) in the future. |

### 3.3 Confirm-Gating via `canUseTool`

Corvus uses the SDK's `canUseTool` callback to implement confirm-gating for destructive operations. This replaces ad-hoc PreToolUse blocking with a proper human-in-the-loop flow.

```python
# Simplified confirm-gate flow

async def confirm_gate_callback(
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """Bridge SDK permission check to WebSocket for user approval."""

    # Check if this tool is in the confirm-gated set (from agent spec YAML)
    if tool_name not in current_session.confirm_gated_tools:
        return PermissionResultAllow()  # Auto-allow

    # Send confirmation request to WebSocket
    approval = await websocket.send_confirm_request(
        tool_name=tool_name,
        tool_input=input_data,
        agent_name=current_session.agent_name,
    )

    if approval.approved:
        return PermissionResultAllow()
    else:
        return PermissionResultDeny(
            message=f"User denied {tool_name}: {approval.reason}",
        )
```

**Confirm-gated tools** are defined per-module in the agent spec YAML:

```yaml
# config/agents/finance.yaml
tools:
  modules:
    firefly:
      tools: [transactions, accounts, summary, create_transaction]
      confirm_gated: [create_transaction]   # Requires user approval
```

**Break-glass mode** uses `set_permission_mode("bypassPermissions")` to temporarily skip confirm-gating. This auto-expires on WebSocket disconnect.

### 3.4 Hook System: All SDK Hooks + Corvus Extensions

The Claude Agent SDK provides 10 hook events. Corvus uses ALL of them and layers additional behavior on top. Hooks are the primary mechanism for security enforcement, observability, memory extraction, and user interaction.

#### 3.4.1 SDK Hook Events — Complete Reference

| SDK Hook Event | Trigger | Key Input Fields | Corvus Usage |
|---------------|---------|-----------------|--------------|
| `PreToolUse` | Before any tool executes | `tool_name`, `tool_input`, `tool_use_id` | **Security**: block .env reads. **Policy**: cascading deny-wins. **Confirm-gate**: destructive ops. |
| `PostToolUse` | After successful tool execution | `tool_name`, `tool_input`, `tool_response`, `tool_use_id` | **Telemetry**: emit structured event. **Sanitization**: verify output is clean. |
| `PostToolUseFailure` | Tool execution fails | `tool_name`, `tool_input`, `error`, `is_interrupt` | **Error tracking**: log failures to JSONL. **Recovery**: custom error messages. **Circuit-breaking**: track failure counts per module. |
| `Stop` | Agent execution stops | `stop_hook_active` | **Memory extraction**: `extract_session_memories()` from transcript. **Session archival**: save transcript metadata. |
| `SubagentStart` | Domain subagent starts | `agent_id`, `agent_type` | **Telemetry**: track which agent is active. **Session metadata**: record agent dispatch. |
| `SubagentStop` | Domain subagent completes | `agent_id`, `agent_transcript_path`, `agent_type`, `stop_hook_active` | **Memory extraction**: per-agent transcript processing. **Cost tracking**: per-agent usage. |
| `PreCompact` | Before context auto-compaction | `trigger` ("manual"\|"auto"), `custom_instructions` | **Transcript archival**: save full transcript BEFORE compaction. **Critical**: without this, long sessions lose context silently. |
| `Notification` | Agent status messages | `message`, `title`, `notification_type` | **Alerting**: forward to EventEmitter. **Future**: push to Slack/Alloy. |
| `PermissionRequest` | Permission dialog needed | `tool_name`, `tool_input`, `permission_suggestions` | **Confirm-gating UX**: bridge SDK permission prompt to WebSocket for user approval. |
| `UserPromptSubmit` | User submits a prompt | `prompt` | **Input logging**: audit trail of user queries. **Rate limiting**: track request frequency. |

#### 3.4.2 Hook Callback Signature

```python
from claude_agent_sdk import HookMatcher
from typing import Callable, Awaitable

# Callback signature: (input_data, tool_use_id, context) -> output
HookCallback = Callable[
    [dict, str | None, HookContext],
    Awaitable[HookJSONOutput]
]

# Output controls conversation flow
HookJSONOutput = {
    "continue_": bool,              # Whether to proceed (default True)
    "suppressOutput": bool,         # Hide stdout from transcript
    "stopReason": str,              # Message when continue is False
    "decision": "block" | None,     # Block the operation
    "systemMessage": str,           # Injected into conversation, visible to model
    "reason": str,                  # Feedback for Claude (e.g., why blocked)
    "hookSpecificOutput": {         # Event-specific fields
        "hookEventName": str,
        "permissionDecision": "allow" | "deny" | "ask",
        "permissionDecisionReason": str,
        "updatedInput": dict,       # Modify tool input before execution
        "additionalContext": str,   # Context injected after tool result
    },
}
```

#### 3.4.3 Hook Pipeline — How Corvus Uses Each Hook

```python
# corvus/hooks.py — complete hook configuration

hooks = {
    "PreToolUse": [
        HookMatcher(
            matcher="Bash|Read",
            hooks=[credential_guard],         # Block .env reads, credential exposure
        ),
        HookMatcher(
            matcher="mcp__.*",
            hooks=[cascading_policy_check],   # 5-layer deny-wins policy (Section 6.4)
        ),
        HookMatcher(
            matcher="mcp__.*",
            hooks=[confirm_gate_check],       # Prompt user for destructive ops
        ),
    ],
    "PostToolUse": [
        HookMatcher(
            matcher=".*",
            hooks=[telemetry_emitter],        # Structured event -> JSONL -> Loki
        ),
        HookMatcher(
            matcher="mcp__.*",
            hooks=[output_sanitizer],         # Verify no credential leaks in output
        ),
    ],
    "PostToolUseFailure": [
        HookMatcher(
            matcher="mcp__.*",
            hooks=[failure_tracker],          # Track failures, circuit-breaking
        ),
    ],
    "Stop": [
        HookMatcher(
            matcher=None,                     # All stops
            hooks=[memory_extractor],         # Extract memories from transcript
        ),
        HookMatcher(
            matcher=None,
            hooks=[session_archiver],         # Save session metadata + cost
        ),
    ],
    "SubagentStart": [
        HookMatcher(
            matcher=None,
            hooks=[agent_lifecycle_tracker],  # Record which agent started
        ),
    ],
    "SubagentStop": [
        HookMatcher(
            matcher=None,
            hooks=[agent_lifecycle_tracker],  # Record agent completion + cost
        ),
    ],
    "PreCompact": [
        HookMatcher(
            matcher=None,
            hooks=[transcript_archiver],      # Save FULL transcript before compaction
        ),
    ],
    "Notification": [
        HookMatcher(
            matcher=None,
            hooks=[notification_forwarder],   # Forward to EventEmitter / future: Slack
        ),
    ],
    "PermissionRequest": [
        HookMatcher(
            matcher=None,
            hooks=[permission_bridge],        # Bridge to WebSocket for user confirmation
        ),
    ],
    "UserPromptSubmit": [
        HookMatcher(
            matcher=None,
            hooks=[input_audit_logger],       # Audit trail of user queries
        ),
    ],
}
```

#### 3.4.4 Corvus-Specific Hook Behavior (Beyond SDK)

Corvus adds domain-specific logic INSIDE hook callbacks. These are NOT new hook events — they are specialized behavior within SDK hooks:

| Corvus Behavior | SDK Hook Used | Implementation |
|-----------------|--------------|----------------|
| **Credential guard** | PreToolUse | Block `cat .env`, `Read .env`, `find -name .env -exec`. Deny wins. Emits `credential_access_attempt` event to JSONL → Loki. |
| **Cascading policy** | PreToolUse | 5-layer deny-wins evaluation (Section 6.4). Returns `deny` if any layer blocks. Emits `policy_deny` event with layer name and reason. |
| **Confirm-gating** | PreToolUse + PermissionRequest | PreToolUse returns `ask` for gated tools. SDK fires PermissionRequest. Gateway bridges to WebSocket. Emits `confirm_gate_prompted/approved/denied` events. |
| **Output sanitization** | PostToolUse | `sanitize()` runs on tool output. If credentials detected, redacts and emits `credential_redacted` event with matched pattern. |
| **Circuit-breaking** | PostToolUseFailure | Track consecutive failures per tool module. After threshold (default 5), auto-deny module tools until health recovers. Emits `circuit_breaker_tripped/reset` events. |
| **Memory extraction** | Stop | `extract_session_memories()` calls Haiku to extract facts. Uses `output_format` schema for structured extraction (planned). Emits `memory_extracted` event with count. |
| **Transcript archival** | PreCompact | Save full transcript to `/data/transcripts/{session_id}.jsonl` BEFORE auto-compaction destroys it. Critical for long sessions. Emits `transcript_archived` event. |
| **Session cost tracking** | SubagentStop | Extract `total_cost_usd` and `usage` from `ResultMessage`. Aggregate per-agent and per-session. Emits cost metrics to JSONL. |
| **Agent telemetry** | SubagentStart + SubagentStop | Track agent lifecycle: start time, duration, tool calls, cost. Powers `GET /api/agents/{name}/stats`. |
| **Permission bridge** | PermissionRequest | Convert SDK permission dialog to WebSocket message. User approves/denies in UI. Response sent back to SDK callback. |
| **Input audit** | UserPromptSubmit | Log every user prompt with timestamp and session. Powers rate limiting and query pattern analysis. |

#### 3.4.5 Hook Execution Rules

1. **Deny wins.** If ANY hook returns `deny`, the tool call is blocked. Other hooks are not consulted.
2. **Hooks execute in array order.** First matcher that matches a tool name runs its callbacks in sequence. Use ordering for: security check → policy check → confirm-gate.
3. **Matchers filter by tool name only.** Regex on `tool_name` (e.g., `"Bash|Read"`, `"mcp__.*"`, `".*"`). Cannot filter by file paths or other arguments — that happens inside the callback.
4. **`updatedInput` requires `allow`.** To modify tool input (e.g., adding flags), the hook must also return `permissionDecision: "allow"`.
5. **Async hooks are fire-and-forget.** Returning `{"async_": True}` makes the hook non-blocking. Use for telemetry that shouldn't delay tool execution.
6. **`systemMessage` is injected into the conversation.** Visible to the model. Use for context ("This tool was confirm-gated because..."). May not appear in SDK output to the gateway.
7. **Hook timeout defaults to 60 seconds.** Configurable per `HookMatcher` via `timeout` field.

### 3.5 Skills in Corvus

SDK Skills are slash commands from `.claude/skills/SKILL.md` files. In Corvus, the equivalent functionality is handled differently:

- **Per-agent prompts** are loaded from `AgentSpec.prompt_file` (YAML config), not SDK skill files
- **Per-agent tool allowlists** are in `AgentSpec.tools`, not skill definitions
- **Dynamic capability loading** is the Capabilities Hub's job, not skills
- Skills are NOT used for runtime behavior — they are a developer-time convenience in the SDK
- **Future**: Skills may be used for the setup wizard's interactive prompts

---

## 4. Agent Gateway

### 4.1 Agent Selection: Auto-Route and Direct Spawn

The Agents Hub supports two ways to reach an agent — **auto-route** (the hub classifies and picks) and **direct spawn** (the user picks explicitly). Both paths live inside the hub.

```
                        ┌─────────────────┐
                        │   User Message   │
                        └────────┬────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
             Auto-route                  Direct spawn
          (default chat)            (UI / API / command)
                    │                         │
                    v                         v
        AgentsHub.route(message)    AgentsHub.spawn("finance")
          │                                   │
          │ 1. Read enabled agents            │ Skip classification
          │ 2. RouterAgent.classify()         │ Go straight to spec
          │    [Haiku, ~20 tokens]            │
          │    -> "finance"                   │
          │                                   │
          └──────────┬────────────────────────┘
                     │
                     v
          AgentsHub.get("finance") -> AgentSpec
                     │
                     v
          Build AgentDefinition + CapabilitiesHub tools
                     │
                     v
          Ready to query — fully assembled
```

**Auto-route** is the default: user sends a message, the hub classifies it and picks the right agent. This is invisible — the user just talks.

**Direct spawn** lets the user browse, inspect, and talk to a specific agent:
- **UI**: Agent list panel — see all agents, their status, tools, memory domains. Click to open a session.
- **API**: `POST /api/agents/{name}/spawn` — start a session with a specific agent.
- **Chat command**: "Talk to the finance agent" or "@finance check my balance" — the general agent recognizes the intent and hands off directly.
- **Observation**: View an agent's current sessions, recent conversations, memory, tool usage, and health — all from the UI or API.

**Why routing lives in the hub:** When a user creates a new agent via chat, the router immediately sees it on the next message — because the hub provides the router with the current agent list. No separate config to update, no restart needed.

**RouterAgent** (`corvus/router.py`) is internal to the hub:
- Always uses Haiku (cheapest, fastest) regardless of the target agent's model
- Falls back to "general" on any classification failure
- Parses response with fuzzy matching: exact match -> substring match -> "general"
- Valid agents: dynamically read from `AgentsHub.list_enabled()`

**Why not keyword rules?** Natural language is ambiguous. "Check my server logs for email errors" could be homelab or email. The LLM resolves ambiguity better than rules, and at Haiku speeds (~200ms) the latency is negligible.

### 4.2 Agents Hub

The Agents Hub owns agent definitions, permissions, prompts, and tool assignments. Agent configuration is **data-driven** (YAML + DB overrides), not hard-coded in Python. Changes take effect via live reload -- no server restart required.

**This is a user-facing system, not an admin panel.** The whole point of the Hub architecture is that the user creates, configures, and manages their own agents -- assigning tools from the Capabilities Hub, memory domains from the Memory Hub, and prompts. The Hubs are registries of available capabilities that the user composes into agents.

```
+-------------------------------------------------------+
|                    AGENTS HUB                          |
|                                                        |
|  AgentRegistry                                         |
|    |                                                   |
|    +-- route(message) -> (AgentSpec, AgentDefinition)  |
|    +-- spawn(agent_name) -> (AgentSpec, AgentDefinition)|
|    +-- load(config_dir) -> dict[str, AgentSpec]       |
|    +-- get(agent_name) -> AgentSpec                   |
|    +-- list_enabled() -> list[AgentSpec]               |
|    +-- reload() -> ReloadResult                       |
|    +-- create(spec: AgentSpec) -> AgentSpec            |
|    +-- update(name, patch: AgentPatch) -> AgentSpec   |
|    +-- deactivate(name) -> None                       |
|    +-- validate(spec) -> list[ValidationError]        |
|                                                        |
|  Routing (internal):                                   |
|    +-- RouterAgent.classify() uses hub's agent list    |
|    +-- New agents are immediately routable (no restart)|
|                                                        |
|  Observation + Direct Access:                          |
|    +-- List agents with status, tools, memory domains  |
|    +-- Inspect agent: sessions, recent conversations   |
|    +-- Spawn a direct session (bypass routing)         |
|    +-- View agent health, tool usage, memory stats     |
|                                                        |
|  Config Sources (layered, later wins):                 |
|    1. config/agents/*.yaml  (file per agent, git-backed)|
|    2. DB overrides          (runtime edits via API)    |
|    3. Live patches          (in-memory, session-only)  |
|                                                        |
|  Consumers:                                            |
|    - Gateway (route or spawn -> build agent)           |
|    - UI (browse, inspect, direct spawn)                |
|    - CapabilitiesHub (reads tool assignments)          |
|    - MemoryHub (reads memory domain ownership)         |
+-------------------------------------------------------+
```

#### 4.2.1 Agent Spec Format

Each agent is defined in `config/agents/{name}.yaml`:

```yaml
# config/agents/finance.yaml
name: finance
enabled: true
description: >
  Firefly III transactions, YNAB budgets, spending analysis, account
  balances, invoice tracking, and financial reports

# Model assignment (overrides global default)
model: claude-sonnet-4-6
fallback_model: claude-haiku-4-5-20251001

# Prompt -- inline or file reference
prompt_file: prompts/finance.md    # relative to config dir
# prompt_inline: "..."             # alternative: inline prompt text

# Tool access -- explicit allowlist
tools:
  builtin:
    - Bash
  modules:
    firefly:
      tools: [transactions, accounts, categories, summary, create_transaction]
      confirm_gated: [create_transaction]

# Memory domain
memory:
  own_domain: finance
  readable_domains: [finance, work]  # can read own + work domain's private memories
  can_read_shared: true              # can always read shared-visibility memories
  can_write: true

# Obsidian vault access (optional)
# obsidian:
#   allowed_prefixes: [finance/]
#   read: true
#   write: false
```

#### 4.2.2 Agent Lifecycle

```
Gateway startup:
    AgentRegistry.load(config_dir)
    Reads config/agents/*.yaml + DB overrides
    Validates all specs (tools exist, no conflicts)
    Builds AgentDefinition objects for SDK

WebSocket connect:
    AgentRegistry.get(agent_name) -> AgentSpec
    build_options(spec) -> ClaudeAgentOptions
    ClaudeSDKClient(options) created
    Agent lives for duration of session

WebSocket disconnect:
    Stop hook fires: extract_session_memories()
    Client torn down
    No persistent agent processes

Live reload (admin API or file watcher):
    POST /api/agents/reload
    AgentRegistry.reload()
    Validates new config, swaps atomically
    New sessions use updated definitions
    Existing sessions unaffected (graceful)
```

**Key design decisions:**
- Agents are **NOT persistent processes** -- they are per-session, spawned on connect, torn down on disconnect
- Config changes take effect on **next session**, not mid-session (safe, no state corruption)
- YAML files are git-backed for auditability; DB overrides are for runtime tuning
- Validation runs on reload -- invalid config is rejected, previous config stays active
- **Zero-downtime updates**: edit a YAML, hit reload (or let the file watcher auto-detect), new sessions get the updated config

#### 4.2.2a Hot-Loading and Live Editing

Agent definitions are designed to be modified **without stopping the server**. This is user-facing -- the user creates and manages agents through natural conversation or the API.

```
Three ways agents get created/modified:

1. Chat (primary):
   User: "Create a recipes agent that can search my Obsidian vault
          and save to my recipes folder"
   -> General agent calls /api/agents endpoint
   -> Agents Hub validates, registers, reloads router

2. API (direct):
   POST /api/agents
   PATCH /api/agents/{name}
   -> Immediate effect on next session

3. YAML + file watcher (power user / GitOps):
   Edit config/agents/recipes.yaml
   -> Watchdog detects change (1s debounce)
   -> Auto-triggers reload()
   -> Emits "agent_config_reloaded" event
```

**User creates a new agent via chat:**

```
User: "I want a recipes agent that can read and write to my
       recipes/ folder in Obsidian, and save private memories"

General agent (or a dedicated agent-builder tool):
  1. Lists available tool modules from CapabilitiesHub
  2. Lists available memory domains from MemoryHub
  3. Builds AgentSpec:
     - name: recipes
     - description: (generated from user intent)
     - tools: obsidian(r/w, prefix=recipes/), Bash, Read
     - memory: own_domain=recipes, can_read_shared=true
  4. Calls POST /api/agents with the spec
  5. AgentsHub validates + registers
  6. Router immediately includes "recipes" in classifications

User: "Now give the recipes agent access to Firefly
       so it can log grocery expenses"

  -> PATCH /api/agents/recipes
  -> Adds firefly module with [create_transaction] tool
  -> Confirm-gates create_transaction automatically
```

**User edits an existing agent via chat:**

```
User: "Switch the finance agent to Opus"
  -> PATCH /api/agents/finance { "model": "claude-opus-4-6" }

User: "Remove email access from the work agent"
  -> PATCH /api/agents/work { "tools": {"modules": {"email": null}} }

User: "Disable the music agent for now"
  -> POST /api/agents/music/deactivate
```

**User creates via API directly (for automation / scripts):**

```bash
curl -X POST http://localhost:18789/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "recipes",
    "description": "Recipe management, meal planning, grocery lists",
    "tools": {"builtin": ["Bash", "Read"],
              "modules": {"obsidian": {"tools": ["search", "read", "write"],
                                       "allowed_prefixes": ["recipes/"]}}},
    "memory": {"own_domain": "recipes", "can_read_shared": true, "can_write": true}
  }'
```

**Safety guarantees:**
- Active WebSocket sessions are **never disrupted** by config changes
- Only new sessions pick up updated definitions
- Invalid config is rejected at validation -- the system always has a known-good state
- All config changes emit audit events: `agent_created`, `agent_updated`, `agent_deactivated`, `agent_config_reloaded`
- Tool assignments are validated against what the Capabilities Hub actually has registered -- users can't assign tools that don't exist
- Multiple agents can share a memory domain (e.g., two agents both reading/writing to "recipes")
- `readable_domains` lets agents access other agents' private memories when explicitly granted

#### 4.2.3 Agent Management API

These endpoints are **user-facing** -- agents call them on behalf of the user. The general agent (or a dedicated agent-builder tool) can invoke these during a conversation.

**Agent CRUD:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agents` | GET | List all agents with status, tools, memory domains |
| `/api/agents/{name}` | GET | Full agent spec (description, tools, memory, model) |
| `/api/agents` | POST | Create a new agent |
| `/api/agents/{name}` | PATCH | Update agent config (tools, model, prompt, etc.) |
| `/api/agents/{name}` | PUT | Replace full agent config |
| `/api/agents/{name}/deactivate` | POST | Deactivate agent (soft, reversible) |
| `/api/agents/{name}/activate` | POST | Re-activate a deactivated agent |
| `/api/agents/reload` | POST | Reload all agents from YAML+DB |
| `/api/agents/validate` | POST | Dry-run validate a spec before creating |

**Direct spawn + observation:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agents/{name}/spawn` | POST | Start a direct session with this agent (bypass router) |
| `/api/agents/{name}/sessions` | GET | List active + recent sessions for this agent |
| `/api/agents/{name}/sessions/{id}` | GET | Get session transcript / conversation history |
| `/api/agents/{name}/health` | GET | Agent health: tool availability, memory status |
| `/api/agents/{name}/stats` | GET | Usage stats: sessions, tool calls, memory writes |

**Builder helpers:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/capabilities` | GET | List all available tool modules + tools (for agent builder) |
| `/api/memory/domains` | GET | List all memory domains + ownership (for agent builder) |

**Key patterns:**

The general agent acts as a meta-agent that can build other agents. When the user says "create a recipes agent," the general agent:
1. Calls `GET /api/capabilities` to see what tools are available
2. Calls `GET /api/memory/domains` to see what domains exist
3. Composes an `AgentSpec` from the user's intent + available capabilities
4. Calls `POST /api/agents` to register the new agent
5. The router immediately starts routing relevant queries to it

The user can also interact with agents directly:
- **Browse**: `GET /api/agents` shows all agents, their tools, memory, and status at a glance
- **Inspect**: `GET /api/agents/finance/sessions` shows what the finance agent has been working on
- **Direct talk**: `POST /api/agents/finance/spawn` opens a session — no routing needed, user picks the agent
- **Monitor**: `GET /api/agents/finance/stats` shows usage patterns, recent activity, health

#### 4.2.4 Validation Rules

On load/reload, `AgentRegistry.validate()` checks:

1. **Tool references resolve** -- every listed tool module and tool name exists in CapabilitiesHub
2. **Memory domains valid** -- referenced domains exist or will be auto-created; multiple agents CAN share a domain
3. **Prompt exists** -- `prompt_file` path resolves, or `prompt_inline` is non-empty
4. **Model exists** -- model ID is valid per ModelRouter
5. **Name uniqueness** -- no duplicate agent names
6. **Required fields** -- name, description, tools are non-empty

Invalid specs are rejected with structured errors. The registry emits a `config_validation_error` event.

#### 4.2.5 Default Agent Inventory

| Agent | Description | Tools | Memory Domain |
|-------|-------------|-------|---------------|
| personal | Planning, journaling, ADHD support, health | Bash, Read, Obsidian(r/w) | personal |
| work | Projects, meetings, transcripts, career | Bash, Read, Email(r), Drive(r), Obsidian(r) | work |
| homelab | Servers, Docker, Komodo, Loki, Tailscale | Bash, Read, Grep, Glob, Obsidian(r/w) | homelab |
| finance | Firefly, YNAB, spending, invoices | Bash, Firefly(full) | finance |
| email | Inbox triage, search, compose, archive | Bash, Read, Email(full) | email |
| docs | Paperless-ngx, Google Drive, OCR | Bash, Drive(full), Paperless(full) | docs |
| music | Practice, repertoire, technique | Bash, Read | music |
| home | Smart home via Home Assistant | HA(full) | home |
| general | Cross-domain, daily overview, multi-topic | Bash, Read, Obsidian(r) | shared |

### 4.3 Prompt Injection Defense

The gateway is the first line of defense against prompt injection:

1. **Tool policy enforcement**: Agents cannot call tools outside their allowlist (SDK enforces, allowlist from Agents Hub)
2. **PreToolUse hooks**: Block credential file reads regardless of what the LLM requests
3. **Output sanitization**: `sanitize.py` redacts credential patterns from all tool output
4. **Confirm-gating**: Destructive operations require user confirmation (list from agent spec, not hard-coded)
5. **Prefix isolation**: Obsidian agents can only access vault paths within their `allowed_prefixes` (from agent spec)
6. **Router separation**: The router agent has NO tools -- it only classifies intent
7. **Validation gate**: Agent specs are validated on load -- invalid tool references rejected before they can be used

### 4.4 Per-Agent Tool Set Creation

The gateway reads agent specs from the Agents Hub and creates **thin proxy tools** via the Capabilities Hub. The proxy tool names are fixed at session creation, but their dispatch targets can change at runtime (see Section 6.2 for the full thin proxy design).

```python
# In server.py: build_options()

spec = agents_hub.get(agent_name)  # From Agents Hub

# Create thin proxy tools that delegate to the Capabilities Hub
proxy_tools = capabilities_hub.create_proxy_tools(
    agent_name=agent_name,
    agent_spec=spec,
)
# Each proxy is: mcp__{module}_{agent}__{tool} -> hub.dispatch(module, tool, args)

# Proxy tools are registered as in-process MCP servers
for module_name, tools in proxy_tools.items():
    mcp_servers[f"{module_name}_{agent_name}"] = create_sdk_mcp_server(
        name=f"{module_name}_{agent_name}",
        tools=tools,  # Thin proxies, not direct handlers
    )
```

**Key patterns:**
1. **Thin proxy**: Tool names are stable MCP identifiers. What they *dispatch to* is resolved at call time from the Capabilities Hub registry.
2. **Closure security**: Credential injection and per-agent restrictions are captured in the module instance. The agent cannot override them.
3. **Per-turn resolution**: Each tool call re-evaluates the cascading policy pipeline (Section 6.4) and resolves the current handler from the registry. Config changes take effect on the next agent turn.

This same pattern extends to the Memory Hub (see Section 5).

---

## 5. Memory Hub

### 5.1 Three-Layer Architecture

```
+---------------------------------------------+
|  Layer 3: MemoryToolkit (SDK Tools)          |
|  search / save / get / list / forget         |
|  Agent identity baked into closures          |
+---------------------+-----------------------+
                      |
+---------------------v-----------------------+
|  Layer 2: MemoryHub (Coordination)           |
|  Write fan-out, search merge, temporal decay |
|  Visibility filter, write enforcement, audit |
+-----+-------+-------+-------+--------------+
      |       |       |       |
+-----v-+ +---v---+ +-v-----+ +--v--------+
|Primary| |Overlay| |Overlay | |Overlay    |
|SQLite | |Cognee | |sqlite- | |CORPGEN    |
|FTS5   | |Graph  | |vec     | |Extraction |
|(always)| |(opt)  | |(opt)  | |(opt)      |
+--------+ +-------+ +-------+ +-----------+
```

### 5.2 Data Model: MemoryRecord

```python
@dataclass
class MemoryRecord:
    id: str                          # UUID
    content: str                     # The memory text
    domain: str = "shared"           # finance, homelab, work, shared, etc.
    visibility: str = "private"      # "private" | "shared"
    importance: float = 0.5          # 0.0-1.0; >= 0.9 = evergreen (exempt from decay)
    tags: list[str] = field(default_factory=list)
    source: str = "agent"            # "agent" | "session" | "system"
    created_at: str = ""             # ISO 8601
    updated_at: str | None = None
    deleted_at: str | None = None    # soft-delete (forget sets this)
    score: float = 0.0               # search relevance (populated on retrieval)
    metadata: dict = field(default_factory=dict)
```

### 5.3 Identity Flow

```
Gateway spawns agent
    |
    v
create_memory_toolkit(hub, agent_name="finance")
    |
    v
All tool closures capture agent_name
    |
    v
Agent calls memory_save("quarterly report done", visibility="private")
    |
    v
Hub sets record.domain = "finance" (from agent_config, NOT from agent input)
    |
    v
Agent CANNOT override identity -- domain is auto-set
```

### 5.4 Primary + Overlay Model

- **Primary backend** (SQLite FTS5): Always on. Writes must succeed here or the operation fails. Source of truth. If all overlays die, the system still works.
- **Overlay backends** (Cognee, sqlite-vec, CORPGEN): Optional. Registered via config. Hub fans writes to all enabled overlays (best-effort, log failures, do not block). Search collects from all, merges algorithmically.

### 5.5 Write Flow

```
memory_save(content, visibility, tags, importance)
    |
    v
MemoryHub.save(record, agent_name)
    |
    +-- 1. Write enforcement: verify agent owns record.domain
    |      REJECT if mismatch -> return error
    |
    +-- 2. Save to PRIMARY (must succeed, or operation fails)
    |
    +-- 3. Fan out to OVERLAYS (best-effort, log failures)
    |
    +-- 4. Audit event: {timestamp, agent, op, record_id, domain, visibility}
```

### 5.6 Search Flow

```
memory_search(query, limit, domain)
    |
    v
MemoryHub.search(query, agent_name, limit, domain)
    |
    +-- 1. Resolve readable_domains from agent_config
    |
    +-- 2. Collect results from PRIMARY + all healthy OVERLAYS
    |      (each backend filters by readable_domains at SQL level)
    |
    +-- 3. Weighted merge + dedup (by record.id, highest score wins)
    |
    +-- 4. Temporal decay: score *= e^(-ln(2)/30 * age_days)
    |      Skip records with importance >= 0.9 (evergreen)
    |
    +-- 5. MMR diversity re-ranking (lambda=0.7)
    |
    +-- 6. Return top N results
```

### 5.7 Visibility Rules

| Visibility | Who can read | Who can write |
|-----------|-------------|---------------|
| `"private"` | Agents whose `readable_domains` includes `record.domain` | Agents whose `own_domain` matches `record.domain` |
| `"shared"` | All agents (with `can_read_shared: true`) | Any agent (to `"shared"` domain) or own-domain agent |

**Multi-domain access**: Agents can read private memories from domains listed in their `readable_domains` (configured in agent spec). Multiple agents can share the same `own_domain` -- e.g., a "recipes" agent and a "meal-planner" agent can both own `recipes` domain.

**Examples:**
- Finance agent with `readable_domains: [finance, work]` can read private memories from both domains
- Two agents both set `own_domain: recipes` -- both can read and write to that domain
- General agent with `readable_domains: null` reads only its own domain (`shared`) but sees all shared-visibility memories

### 5.8 Temporal Decay

Exponential decay with configurable half-life:

```
decayed_score = score * e^(-ln(2)/half_life_days * age_days)
```

| Age | Retention (30-day half-life) |
|-----|----------------------------|
| Today | 100% |
| 7 days | ~84% |
| 30 days | 50% |
| 90 days | 12.5% |
| Evergreen (importance >= 0.9) | 100% (exempt) |

### 5.9 Memory Module Registry

```python
@dataclass
class BackendConfig:
    name: str                    # e.g., "cognee", "sqlite-vec"
    enabled: bool = False
    weight: float = 0.3          # search result weight relative to primary (1.0)
    settings: dict = field(default_factory=dict)

@dataclass
class MemoryConfig:
    primary_db_path: Path
    overlays: list[BackendConfig] = field(default_factory=list)
    decay_half_life_days: float = 30.0
    evergreen_threshold: float = 0.9
    mmr_lambda: float = 0.7
    audit_enabled: bool = True
```

### 5.10 Memory Pruner

The memory pruner is a **scheduled concern**, not a continuous process:

- Runs via `CronScheduler` on a configurable schedule (default: weekly)
- Soft-deletes memories with `importance < 0.3` older than 90 days
- Never deletes evergreen memories (importance >= 0.9)
- Produces audit trail of all deletions
- Only the pruner can hard-delete (agents can only soft-delete via `forget()`)

### 5.11 Planned Overlay Modules

| Module | Type | Purpose |
|--------|------|---------|
| SQLite FTS5 | Primary (always on) | BM25 keyword search, source of truth |
| sqlite-vec | Overlay (optional) | Vector similarity using local embeddings |
| Cognee | Overlay (optional) | Knowledge graph, multi-hop reasoning |
| CORPGEN Extraction | Overlay (optional) | System-managed fact extraction from sessions |
| Mem0 | Overlay (future) | Triple-scoped vector + graph memory |

### 5.12 File Structure

```
corvus/memory/
  __init__.py              -- Public API: MemoryHub, MemoryRecord, create_memory_toolkit
  hub.py                   -- MemoryHub class (coordination, merge, decay, audit)
  record.py                -- MemoryRecord dataclass + serialization
  toolkit.py               -- create_memory_toolkit() for SDK tool creation
  config.py                -- MemoryConfig, BackendConfig dataclasses
  backends/
    __init__.py
    protocol.py            -- MemoryBackend protocol (extended)
    fts5.py                -- SQLite FTS5 primary backend (consolidated)
    cognee.py              -- Cognee overlay backend (stub, enabled later)
    vault.py               -- Obsidian vault writer overlay
```

---

## 6. Capabilities Hub

The Capabilities Hub is the registry, validator, and policy enforcer for all tool capabilities. It owns the full lifecycle: discovery, registration, credential injection, per-agent policy enforcement, and runtime dispatch. The key design constraint is that **MCP tool names are fixed at session creation** (SDK limitation), so capabilities use a **thin proxy pattern** — stable tool names that delegate to a dynamic registry that can be reconfigured at runtime.

### 6.1 Architecture

```
+------------------------------------------------------------------------+
|                         CAPABILITIES HUB                                |
|                                                                         |
|  ToolModuleRegistry                                                     |
|    +-- register(module: ToolModule)                                     |
|    +-- unregister(module_name: str)                                     |
|    +-- get_module(name) -> ToolModule                                   |
|    +-- list_modules() -> list[ModuleInfo]                               |
|    +-- health_check_all() -> dict[str, HealthStatus]                    |
|                                                                         |
|  Thin Proxy Layer (SDK-facing)                                          |
|    +-- create_proxy_tools(agent_name) -> list[ProxyTool]                |
|    +-- stable MCP names: mcp__{module}_{agent}__{tool}                  |
|    +-- each proxy delegates to registry.dispatch(module, tool, args)    |
|    +-- proxy set fixed at session creation; backends swap at runtime    |
|                                                                         |
|  Cascading Tool Policy (deny-wins)                                      |
|    +-- Layer 1: Global defaults (corvus.yaml)                           |
|    +-- Layer 2: Agent spec (config/agents/*.yaml)                       |
|    +-- Layer 3: Session overrides (runtime API)                         |
|    +-- Layer 4: Confirm-gating (destructive ops)                        |
|    +-- Layer 5: Sanitization (output filtering)                         |
|    +-- Deny at ANY layer wins — layers can only narrow, never expand    |
|                                                                         |
|  Credential Injection (closures)                                        |
|    +-- CredentialStore.inject() at startup                              |
|    +-- configure(store) per tool module                                 |
|    +-- sanitize.register_credential_patterns()                          |
|                                                                         |
|  Dynamic Registration API                                               |
|    +-- POST /api/capabilities/register   (add module at runtime)        |
|    +-- DELETE /api/capabilities/{name}   (remove module)                |
|    +-- GET /api/capabilities             (list available)               |
|    +-- File watcher on config/tools/*.yaml (hot-reload)                 |
+------------------------------------------------------------------------+
```

### 6.2 SDK Limitation: Why Thin Proxies

The Claude Agent SDK (and OpenClaw) **does not support hot-swapping tools within a live session.** MCP servers and tool definitions are fixed when the session is created via `AgentDefinition.tools`. This is a fundamental SDK constraint, not a Corvus limitation.

**Three options were evaluated:**

| Option | Approach | Trade-off |
|--------|----------|-----------|
| 1. Session-boundary | Only change tools between sessions | User must restart to pick up changes |
| 2. **Thin proxy tools** | Stable tool names delegate to dynamic registry | **Chosen** — runtime flexibility, no restart |
| 3. Session recycling | Kill and rebuild session mid-conversation | Loses conversation context |

**Option 2 (thin proxy tools)** solves this by giving every agent a fixed set of proxy tool names at session creation. Each proxy is a thin function that calls `capabilities_hub.dispatch(module, tool, args)`. The dispatch target can change at runtime — the user adds a tool module, and the next agent call through that proxy uses the new backend.

```python
# How thin proxies work (conceptual)

# At session creation: agent gets these stable tool names
tools = [
    "mcp__email__email_list",       # proxy -> hub.dispatch("email", "email_list", args)
    "mcp__email__email_read",       # proxy -> hub.dispatch("email", "email_read", args)
    "mcp__paperless__search",       # proxy -> hub.dispatch("paperless", "search", args)
    # ...
]

# At runtime: user registers a new tool module
capabilities_hub.register(NewModule("invoice_parser"))
# The agent's tool list didn't change, but if "invoice_parser" tools
# were already in the proxy set, they now resolve to real handlers.
# If not, the user creates a new agent with those tools via Agents Hub.
```

**What changes require a new session vs. runtime:**

| Change | Requires New Session? | Notes |
|--------|----------------------|-------|
| Add/remove tool to existing module | No | Proxy delegates to updated registry |
| Change tool implementation | No | Dispatch resolves to new handler |
| Change confirm-gating | No | Policy checked at dispatch time |
| Change agent's tool allowlist | Yes | `AgentDefinition.tools` is fixed |
| Add entirely new tool module | Yes | New proxy names needed |
| Change model or prompt | Yes | `AgentDefinition` is fixed |

### 6.3 Tool Module Contract

Every tool module implements the `ToolModule` protocol (see Section 10.3 for full contract):

```python
# corvus/tools/paperless.py -- example tool module

class PaperlessModule:
    """Paperless-ngx document management tools."""

    name = "paperless"

    def configure(self, store: CredentialStore) -> None:
        """Inject credentials. Called once at startup or on hot-reload."""
        self._url = store.get("PAPERLESS_URL")
        self._token = store.get("PAPERLESS_TOKEN")

    def get_tools_for_agent(
        self, agent_name: str, config: AgentToolModuleConfig
    ) -> list[Callable]:
        """Return tool functions filtered by agent's spec config."""
        all_tools = {
            "search": self._search,
            "get_document": self._get_document,
            "tag": self._tag,
            "bulk_edit": self._bulk_edit,
        }
        return [all_tools[t] for t in config.tools if t in all_tools]

    async def health_check(self) -> HealthStatus:
        """Verify Paperless-ngx is reachable."""
        ...
```

**Key design rules:**
1. `configure(store)` is called at startup AND on hot-reload (re-reads credentials)
2. Tool methods capture credentials via `self` — never appear as parameters
3. All outputs pass through `sanitize()` before reaching the agent
4. `get_tools_for_agent()` filters by the agent's spec config — least privilege per agent
5. Modules are registered as in-process MCP servers via `create_sdk_mcp_server()`

### 6.4 Cascading Tool Policy (Deny-Wins)

Inspired by OpenClaw's 9-tier cascading policy pipeline, Corvus uses a 5-layer deny-wins policy. Each layer can only **narrow** access — never expand it. Deny at any layer is final.

```
Request: agent "finance" calls "mcp__firefly__create_transaction"
    |
    v
Layer 1: Global Defaults (corvus.yaml)
    Are tools enabled globally? Is this module globally blocked?
    -> ALLOW (firefly module is globally enabled)
    |
    v
Layer 2: Agent Spec (config/agents/finance.yaml)
    Is "firefly" in this agent's tools.modules?
    Is "create_transaction" in the module's tool list?
    -> ALLOW (finance agent has firefly with create_transaction)
    |
    v
Layer 3: Session Overrides (runtime)
    Has the user restricted this agent's tools for this session?
    (e.g., "finance agent: read-only mode for now")
    -> ALLOW (no session restriction active)
    |
    v
Layer 4: Confirm-Gating
    Is this tool in the confirm-gated set?
    -> CONFIRM (create_transaction is destructive)
    -> User approves
    |
    v
Layer 5: Sanitization (output)
    Tool executes. Output passes through sanitize() pipeline.
    -> Credential patterns redacted, result returned to agent.
```

**Deny-wins examples:**
- Global config disables `ha` module → no agent can use Home Assistant, regardless of agent spec
- Agent spec omits `email` → agent cannot send email, even if global allows it
- Session override sets `read_only: true` → all writes blocked for this session
- Confirm-gate blocks `email_send` → user must approve, even if all other layers allow

```python
# corvus/capabilities/policy.py

class ToolPolicy:
    """Cascading deny-wins tool policy evaluator."""

    def evaluate(
        self,
        agent_name: str,
        tool_name: str,
        *,
        global_config: GlobalConfig,
        agent_spec: AgentSpec,
        session_overrides: SessionOverrides | None = None,
    ) -> PolicyDecision:
        """Returns ALLOW, DENY, or CONFIRM."""

        # Layer 1: Global
        if tool_name in global_config.blocked_tools:
            return PolicyDecision.DENY

        module_name = extract_module(tool_name)
        if module_name in global_config.disabled_modules:
            return PolicyDecision.DENY

        # Layer 2: Agent spec
        if module_name not in agent_spec.tools.modules:
            return PolicyDecision.DENY

        module_config = agent_spec.tools.modules[module_name]
        tool_short = extract_tool_name(tool_name)
        if tool_short not in module_config.tools:
            return PolicyDecision.DENY

        # Layer 3: Session overrides
        if session_overrides and session_overrides.is_blocked(tool_name):
            return PolicyDecision.DENY

        # Layer 4: Confirm-gating
        if tool_short in module_config.confirm_gated:
            return PolicyDecision.CONFIRM

        return PolicyDecision.ALLOW
```

### 6.5 Per-Turn Tool Resolution

Inspired by OpenClaw's per-turn tool resolution (`createOpenClawCodingTools()` rebuilds the tool list every agent turn), Corvus re-evaluates tool availability at dispatch time, not session creation time:

```
Agent turn starts
    |
    v
Agent selects tool from its (fixed) proxy list
    |
    v
Proxy calls capabilities_hub.dispatch(module, tool, args)
    |
    v
Hub resolves current handler from registry
    +-- Module still registered? (may have been hot-removed)
    +-- Tool still available? (may have been disabled)
    +-- Policy still allows? (agent spec may have changed)
    |
    v
    ALLOW -> execute handler, sanitize output, return
    DENY  -> return error: "Tool temporarily unavailable"
```

This means tool changes take effect on the **next agent turn** without restarting the session. The agent's tool *list* is fixed, but what those tools *do* (and whether they succeed) is dynamic.

### 6.6 Dynamic Tool Registration

Tool modules can be registered at runtime through three mechanisms:

**1. Startup discovery** (config-driven):
```yaml
# config/tools/paperless.yaml
name: paperless
module: corvus.tools.paperless.PaperlessModule
credentials:
  - PAPERLESS_URL
  - PAPERLESS_TOKEN
tools:
  - search
  - get_document
  - tag
  - bulk_edit
confirm_gated:
  - tag
  - bulk_edit
health_check_interval: 60
```

**2. File watcher hot-reload** (inspired by OpenClaw's 4-mode watcher):
```python
# corvus/capabilities/watcher.py

class ToolConfigWatcher:
    """Watches config/tools/*.yaml for changes.

    Modes:
      smart  — diff old vs new, only reload changed modules (default)
      hot    — reload all modules on any change
      off    — no watching, manual reload only
    """

    def __init__(self, hub: CapabilitiesHub, mode: str = "smart"):
        self._hub = hub
        self._mode = mode

    async def on_change(self, path: Path) -> None:
        """File changed — reload the corresponding module."""
        spec = yaml.safe_load(path.read_text())
        module_cls = import_module_class(spec["module"])
        self._hub.register(module_cls())
```

**3. Runtime API** (user-driven, via chat or direct HTTP):
```
POST /api/capabilities/register
  { "name": "invoice_parser", "module": "corvus.tools.invoice.InvoiceModule" }

DELETE /api/capabilities/invoice_parser

GET /api/capabilities
  -> [{ "name": "paperless", "tools": [...], "health": "ok" }, ...]

GET /api/capabilities/{name}/health
  -> { "status": "ok", "latency_ms": 42 }
```

The user can register tools via chat, just like agents:
```
User:     "Add an invoice parsing tool that reads PDFs from Paperless"
General:  [calls POST /api/capabilities/register with module config]
          "Done — invoice_parser is now available. I'll add it to your
           finance agent's tool list."
          [calls PATCH /api/agents/finance to add invoice_parser module]
```

### 6.7 Confirm-Gating

Destructive or external-facing operations require user confirmation. Confirm-gating is defined per-module in the agent spec (not a global set):

```yaml
# config/agents/finance.yaml
tools:
  modules:
    firefly:
      tools: [transactions, accounts, categories, summary, create_transaction]
      confirm_gated: [create_transaction]   # <-- per-module confirm list
    email:
      tools: [email_list, email_read, email_send]
      confirm_gated: [email_send]
```

When a confirm-gated tool is invoked, the PreToolUse hook returns `{"decision": "confirm"}`, which prompts the user for approval before execution. The cascading policy evaluates confirm-gating at Layer 4 (see Section 6.4).

**Global confirm overrides** can also be set in `corvus.yaml`:
```yaml
# corvus.yaml
capabilities:
  global_confirm_gated:
    - email_send          # Always confirm, regardless of agent spec
    - ha_call_service     # Physical device control always requires approval
```

### 6.8 Sanitization Pipeline

```
Tool output (raw)
    |
    v
sanitize(text)
    |
    +-- Static patterns: Bearer tokens, Authorization headers,
    |   API keys, cookies, Set-Cookie
    |
    +-- Dynamic patterns: registered from actual credential values
    |   at startup via register_credential_patterns()
    |
    +-- Module-specific patterns: each module can register
    |   additional redaction targets (e.g., internal URLs)
    |
    v
Sanitized text -> agent context
```

The dynamic registration is critical: when `CredentialStore.inject()` runs, it also calls `register_credential_patterns(store.credential_values())` so that the exact credential strings are registered as redaction targets. This catches cases where a backend accidentally echoes a token in its response body.

### 6.9 MCP Server Namespacing

Each tool module becomes an in-process MCP server. There are **two naming patterns** depending on whether the module is shared or per-agent:

**Pattern 1: Shared modules** — `mcp__{module}__{tool}`

Used when the module's behavior is identical for all agents (e.g., email, firefly). The agent's allowlist controls access, but the tools themselves don't vary.

```
Module "email"      -> mcp__email__email_list, mcp__email__email_read, ...
Module "firefly"    -> mcp__firefly__transactions, mcp__firefly__accounts, ...
```

**Pattern 2: Per-agent modules** — `mcp__{module}_{agent}__{tool}`

Used when the module needs per-agent configuration (e.g., Obsidian with different `allowed_prefixes` per agent). The agent name is embedded in the MCP server name.

```
Module "obsidian"   -> mcp__obsidian_personal__obsidian_search, ...
                       mcp__obsidian_work__obsidian_read, ...
```

**Why two patterns:** Obsidian servers are per-agent because each agent gets different vault path prefixes — the path restriction is baked into the server at creation time. Other modules are shared across agents and rely on the agent spec's `tools` allowlist for access control, not per-agent server instances.

### 6.10 Plugin Registration Pattern

For third-party or user-developed tool modules, the Capabilities Hub provides an `init()`-time registration API (inspired by OpenClaw's plugin `registerTool()` pattern):

```python
# Third-party plugin: corvus-invoice-parser

def init(api: CapabilitiesAPI) -> None:
    """Called by the Capabilities Hub when the plugin is loaded."""

    api.register_tool(
        module="invoice_parser",
        name="parse_invoice",
        handler=parse_invoice_handler,
        description="Extract structured data from PDF invoices",
        confirm_gated=False,
    )

    api.register_tool(
        module="invoice_parser",
        name="categorize_expense",
        handler=categorize_expense_handler,
        description="Categorize an expense line item",
        confirm_gated=False,
    )
```

**Discovery mechanisms (evolution path):**
```
Current:  config/tools/*.yaml defines modules, Python imports resolve them
    |
    v
Next:     CapabilitiesHub.register(module) with ToolModule protocol
    |
    v
Future:   Entry-point discovery (pyproject.toml [corvus.plugins.tools])
          uv-installable tool module packages
          corvus-obsidian, corvus-email, corvus-paperless, etc.
```

### 6.11 Capabilities Management API

The full capabilities API (user-facing, not admin-only):

```
GET    /api/capabilities                     # List all registered modules
GET    /api/capabilities/{name}              # Module details + tool list
GET    /api/capabilities/{name}/health       # Health check
POST   /api/capabilities/register            # Register a new module
DELETE /api/capabilities/{name}              # Unregister a module
PATCH  /api/capabilities/{name}              # Update module config

GET    /api/capabilities/policy/{agent}      # Show effective policy for agent
POST   /api/capabilities/policy/evaluate     # Dry-run policy evaluation
```

### 6.12 File Structure

```
corvus/capabilities/
    __init__.py
    hub.py              -- CapabilitiesHub: registry, dispatch, lifecycle
    policy.py           -- ToolPolicy: cascading deny-wins evaluator
    proxy.py            -- Thin proxy tool creation for SDK
    watcher.py          -- File watcher for config/tools/*.yaml hot-reload
    registry.py         -- ToolModuleRegistry: register, lookup, health

config/tools/           -- One YAML per tool module (git-backed, hot-reloadable)
    paperless.yaml
    firefly.yaml
    email.yaml
    drive.yaml
    obsidian.yaml
    ha.yaml
```

---

## 7. Security Model

### 7.1 Zero Credential Exposure

The fundamental security invariant: **No LLM ever sees any credential, not in prompts, not in tool args, not in tool output, not in memory, not in logs.**

```
Credential Lifecycle:
    |
    v
1. SOPS+age encrypted file: ~/.secrets/claw.env (symlinked from .env)
    |
2. CredentialStore.load() decrypts at startup (in-memory only)
    |
3. CredentialStore.inject() calls each module's configure()
    |
4. register_credential_patterns() registers values for redaction
    |
5. Module closures capture credentials
    |
6. Agent calls tool -> module uses captured credential internally
    |
7. Module output passes through sanitize() -> credential-free text
    |
8. Agent receives only sanitized data
```

### 7.2 Defense in Depth Layers

| Layer | Mechanism | Catches |
|-------|-----------|---------|
| 1. SDK tool policy | `AgentDefinition.tools` allowlist | Agent cannot call disallowed tools |
| 2. PreToolUse hook | `check_bash_safety()`, `check_read_safety()` | Agent tries to `cat .env` or read secret files |
| 3. Module closures | Credentials captured in constructor, not passed as args | Agent cannot override credentials in tool parameters |
| 4. Path isolation | `allowed_prefixes` per agent in `ObsidianClient` | Agent tries to read another agent's vault paths |
| 5. Output sanitization | `sanitize()` with static + dynamic patterns | Backend accidentally echoes credentials in response |
| 6. Confirm-gating | PreToolUse returns `{"decision": "confirm"}` | Agent tries to perform destructive action without user approval |
| 7. Visibility filtering | SQL WHERE clause in memory backends | Agent tries to read another agent's private memories |
| 8. Write enforcement | Hub checks `own_domain` matches `record.domain` | Agent tries to write to another domain's memory |

### 7.3 Break-Glass Mode

Gateway-level privilege escalation for emergency operations.

```
Activation:
    /break-glass command in chat
        |
        v
    BreakGlassManager.activate(passphrase)
        |
        +-- Argon2id verification (memory_cost=64KB, time_cost=3)
        +-- Escalating lockout: 3 fails -> 15m, 6 -> 1h, 9 -> 24h
        +-- Lockout state persisted to disk (survives restart)
        |
        v
    Per-session flag (in-memory only, never persisted)
        |
        v
    Tool policy expanded for this session only
        |
        v
    All actions logged with "break_glass": true
        |
        v
    Auto-expires on WebSocket disconnect
```

**Critical**: Break-glass mode is **invisible to all agents**. No system prompt, tool, or routing path references it. Only the gateway's tool-policy layer checks the flag. This prevents prompt injection from triggering escalation.

### 7.4 CredentialStore Architecture

```
~/.secrets/
  claw.env               # SOPS+age encrypted (symlinked from .env)
  claw.env.bak           # Previous version (rotation rollback)
  age-key.txt            # age private key (0600 permissions)

~/.corvus/
  passphrase.hash        # Argon2id hash (0600 permissions)
  lockout.json           # Rate-limit state
```

**Credential rotation**: New value stored as pending, validated against service API, promoted to active. Old value kept as previous until next successful rotation.

**Fallback path**: When no SOPS file exists (Docker container with env vars), `CredentialStore.from_env()` builds an in-memory store from well-known environment variable names.

### 7.5 Audit Trail

All security-relevant events are emitted via `EventEmitter`:

| Event | When | Contains |
|-------|------|----------|
| `security_block` | PreToolUse blocks a credential read | tool, reason, tool_use_id |
| `confirm_gate` | PreToolUse requires user confirmation | tool, tool_use_id |
| `tool_call` | PostToolUse logs every tool execution | tool, input_summary (truncated) |
| `routing_decision` | Router dispatches to an agent | agent, backend, query_preview |
| `session_start/end` | WebSocket connect/disconnect | user, session_id, duration |
| `heartbeat` | Supervisor checks provider health | mcp_status map |
| `provider_restart` | Supervisor restarts unhealthy provider | provider, attempt |
| `break_glass` | Break-glass activation | user, session_id (future) |

Events are written to `/var/log/corvus/events.jsonl` via `JSONLFileSink`, shipped to Loki via Alloy, queryable in Grafana.

---

## 8. Observability

### 8.1 Hook-Based Telemetry

All observability flows through the `EventEmitter` + hook system. Every hook fires structured events — security denials, credential access attempts, tool calls, cost tracking, and agent lifecycle events all stream to JSONL → Alloy → Loki → Grafana.

```
Tool call / Security event / Agent lifecycle
    |
    v
Hook fires (PreToolUse, PostToolUse, PostToolUseFailure, Stop, etc.)
    |
    v
emitter.emit(event_type, structured_metadata)
    |
    v
JSONLFileSink writes to /var/log/corvus/events.jsonl
    |
    v
Grafana Alloy ships to Loki
    |
    v
Grafana dashboards + alerting rules
```

### 8.1.1 Security Event Stream

Every security-relevant action emits a structured event. This is non-negotiable — if the system blocks something, denies access, or detects a credential leak, it MUST be logged and visible in Grafana.

| Event Type | Trigger | Logged Fields | Severity |
|-----------|---------|--------------|----------|
| `security_block` | PreToolUse hook denies a tool call (credential guard) | `agent`, `tool_name`, `tool_input_preview`, `reason`, `policy_layer` | **HIGH** |
| `credential_access_attempt` | Agent tries to read `.env`, `cat .env`, `find .env`, etc. | `agent`, `command`, `file_path`, `blocked_by` (hook or sandbox) | **CRITICAL** |
| `credential_redacted` | PostToolUse sanitizer detects and redacts a credential in tool output | `agent`, `tool_name`, `pattern_matched`, `redacted_count` | **HIGH** |
| `policy_deny` | Cascading deny-wins policy blocks a tool at any layer | `agent`, `tool_name`, `denied_at_layer` (1-5), `layer_name`, `reason` | **MEDIUM** |
| `confirm_gate_prompted` | Tool requires user confirmation | `agent`, `tool_name`, `tool_input_preview` | **LOW** |
| `confirm_gate_approved` | User approves a confirm-gated tool | `agent`, `tool_name`, `approval_time_ms` | **LOW** |
| `confirm_gate_denied` | User denies a confirm-gated tool | `agent`, `tool_name`, `denial_reason` | **MEDIUM** |
| `break_glass_activated` | Break-glass passphrase accepted | `agent`, `session_id`, `activated_by` | **CRITICAL** |
| `break_glass_deactivated` | Break-glass session ends | `session_id`, `duration_s`, `actions_taken` | **HIGH** |
| `circuit_breaker_tripped` | Module failures exceed threshold (5 consecutive) | `module`, `failure_count`, `last_error` | **HIGH** |
| `circuit_breaker_reset` | Module health recovers after trip | `module`, `recovery_time_s` | **MEDIUM** |
| `sandbox_violation` | Agent attempts to escape sandbox restrictions | `agent`, `command`, `violation_type` | **CRITICAL** |

**All security events** include: `timestamp`, `session_id`, `agent_name`, `event_type`, and `severity`. This enables Grafana alerting rules:

```yaml
# Grafana alert rule example (LogQL)
alert: CredentialAccessAttempt
expr: count_over_time({job="corvus"} | json | event_type="credential_access_attempt" [5m]) > 0
for: 0m
annotations:
  summary: "Agent {{ .agent }} attempted credential access"
  severity: critical
```

### 8.2 Structured Logging

Events are JSON objects with consistent schema:

```json
{
  "timestamp": "2026-02-28T10:30:00+00:00",
  "event_type": "routing_decision",
  "metadata": {
    "agent": "finance",
    "backend": "claude",
    "source": "websocket",
    "query_preview": "How much did I spend on..."
  }
}
```

### 8.3 Health Checks and Heartbeats

**AgentSupervisor** (`corvus/supervisor.py`) runs a 30-second heartbeat loop:

```
Every 30 seconds:
    |
    +-- registry.health_check_all()
    |     Returns dict[provider_name, HealthStatus]
    |
    +-- For each unhealthy provider:
    |     If restart callable exists AND attempts < 3:
    |       provider.restart()
    |       Increment restart counter
    |     Counter resets when provider recovers
    |
    +-- emitter.emit("heartbeat", uptime, mcp_status)
```

**ProviderHealthStatus** contract (used by AgentSupervisor for infrastructure health):

```python
@dataclass
class ProviderHealthStatus:
    name: str        # "sqlite-fts5", "obsidian", "ha"
    status: str      # "healthy" | "unhealthy" | "degraded" | "restarting"
    uptime: float    # seconds
    restarts: int
    detail: str = "" # error message if unhealthy
```

**Note:** Tool modules use a different health type: `ModuleHealthStatus` (Section 10.3) with `latency_ms`, `message`, and `checked_at` fields. The supervisor aggregates both.

### 8.4 Metrics Collection Points

**Operational metrics:**

| Metric | Source | Use |
|--------|--------|-----|
| Agent routing distribution | `routing_decision` events | Which agents are used most? |
| Tool call frequency | `tool_call` events (PostToolUse) | Which tools are called most? |
| Tool failure rate | `tool_failure` events (PostToolUseFailure) | Which modules are flaky? |
| Session duration | `session_start/end` events (SubagentStart/Stop) | How long are conversations? |
| Memory extraction rate | `memory_extracted` events (Stop hook) | How many facts per session? |
| Provider health | `heartbeat` events (Supervisor) | Are backends healthy? |
| Memory search latency | `memory_search` events (PostToolUse) | Are searches fast enough? |
| Transcript compaction | `transcript_archived` events (PreCompact) | How often do sessions hit context limits? |

**Security metrics:**

| Metric | Source | Use |
|--------|--------|-----|
| Security blocks | `security_block` events (PreToolUse) | Credential access attempts |
| Credential redactions | `credential_redacted` events (PostToolUse) | Leaked credentials caught by sanitizer |
| Policy denials | `policy_deny` events (PreToolUse) | Tool access denied at which layer? |
| Confirm-gate approvals/denials | `confirm_gate_*` events (PermissionRequest) | How often are mutations confirmed vs denied? |
| Break-glass activations | `break_glass_*` events | How often and how long? |
| Circuit breaker trips | `circuit_breaker_*` events | Module reliability |
| Sandbox violations | `sandbox_violation` events | Agent escape attempts |

**Cost metrics:**

| Metric | Source | Use |
|--------|--------|-----|
| Per-session cost | `ResultMessage.total_cost_usd` (SubagentStop) | Session spending |
| Per-agent cost | Aggregated from session costs | Which agents cost the most? |
| Daily/monthly total | Aggregated from all sessions | Budget tracking |
| Token usage (input/output) | `ResultMessage.usage` | Identify context-heavy agents |
| Budget limit hits | `budget_exceeded` events | Sessions that hit `max_budget_usd` |

---

## 9. Scheduling and Background Tasks

### 9.1 CronScheduler

`CronScheduler` (`corvus/scheduler.py`) uses APScheduler for background task execution:

```python
scheduler = CronScheduler(
    config_path=Path("config/schedules.yaml"),  # YAML defaults
    db_path=MEMORY_DB,                           # SQLite for state
    emitter=emitter,                             # Event bus
)
```

### 9.2 Schedule Types

```python
class ScheduleType(str, Enum):
    prompt = "prompt"      # Send a prompt to an agent
    skill = "skill"        # Invoke a skill (future)
    webhook = "webhook"    # Trigger a webhook handler (future)
    script = "script"      # Run a script (future)
```

Currently only `prompt` type is implemented. The scheduler sends a prompt to a specified agent using the same dispatch mechanism as webhooks.

### 9.3 Configuration

Schedules are defined in YAML with DB overrides:

```yaml
# config/schedules.yaml
schedules:
  morning_briefing:
    description: "Daily morning briefing"
    type: prompt
    cron: "0 7 * * *"        # 7:00 AM daily
    agent: general
    prompt_template: >
      Give me a morning briefing covering:
      - Upcoming tasks and deadlines
      - Unread emails summary
      - Homelab health status
    enabled: true

  memory_prune:
    description: "Weekly memory pruning"
    type: prompt
    cron: "0 3 * * 0"        # 3:00 AM Sunday
    agent: general
    prompt_template: "Review and prune old memories with low importance."
    enabled: true
```

DB overrides take precedence for: `cron`, `enabled`, `agent`, `prompt_template`.

### 9.4 Schedule Management API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/schedules` | GET | List all schedules with status |
| `/api/schedules/{name}` | GET | Get single schedule details |
| `/api/schedules/{name}` | PATCH | Update cron, enabled, prompt |
| `/api/schedules/{name}/trigger` | POST | Manually trigger a schedule |

### 9.5 Memory Pruner Schedule

The memory pruner runs as a scheduled task, not a background daemon:

- **Schedule**: Weekly (Sunday 3:00 AM by default)
- **Behavior**: Soft-delete low-importance memories older than 90 days
- **Protection**: Evergreen memories (importance >= 0.9) are never pruned
- **Audit**: All prune operations logged to `memory_audit` table
- **Hard-delete**: Reserved for future admin-only endpoint (not agent-accessible)

---

## 10. Module Contracts

### 10.1 MemoryBackend Protocol

Every memory backend (primary and overlay) must implement:

```python
class MemoryBackend(Protocol):
    async def save(self, record: MemoryRecord) -> str:
        """Persist a memory record. Returns the record ID."""
        ...

    async def search(
        self, query: str, *,
        limit: int = 10,
        domain: str | None = None,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Search memories. readable_domains for SQL-level visibility."""
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Retrieve a specific memory by ID."""
        ...

    async def list_memories(
        self, *,
        domain: str | None = None,
        limit: int = 20,
        offset: int = 0,
        readable_domains: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """List memories with pagination and visibility filtering."""
        ...

    async def forget(self, record_id: str) -> bool:
        """Soft-delete: set deleted_at. Returns True if found."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check backend health."""
        ...
```

**Critical**: The `readable_domains` parameter pushes visibility filtering into the SQL WHERE clause. Backends must never return data the agent should not see.

### 10.2 AgentSpec Contract

```python
@dataclass
class AgentToolModuleConfig:
    """Per-module tool access for an agent."""
    tools: list[str]                    # Allowed tool names within the module
    confirm_gated: list[str] = field(default_factory=list)

@dataclass
class AgentToolConfig:
    """Complete tool access for an agent."""
    builtin: list[str] = field(default_factory=list)    # Bash, Read, Grep, etc.
    modules: dict[str, AgentToolModuleConfig] = field(default_factory=dict)

@dataclass
class AgentMemoryConfig:
    """Memory access for an agent."""
    own_domain: str                     # e.g., "finance" -- can be shared by multiple agents
    readable_domains: list[str] | None = None  # Domains this agent can read private memories from
                                               # None = own_domain only; explicit list for cross-domain
    can_read_shared: bool = True        # Can read shared-visibility memories from any domain
    can_write: bool = True              # Can write memories to own_domain

@dataclass
class AgentObsidianConfig:
    """Obsidian vault access for an agent."""
    allowed_prefixes: list[str] | None = None  # None = unrestricted
    read: bool = True
    write: bool = False

@dataclass
class AgentSpec:
    """Complete agent definition -- the single source of truth."""
    name: str
    description: str
    enabled: bool = True
    model: str | None = None            # None = use global default
    fallback_model: str | None = None
    prompt_file: str | None = None      # Relative to config dir
    prompt_inline: str | None = None    # Alternative to file
    tools: AgentToolConfig = field(default_factory=AgentToolConfig)
    memory: AgentMemoryConfig | None = None
    obsidian: AgentObsidianConfig | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def prompt(self) -> str:
        """Resolve prompt from file or inline."""
        if self.prompt_file:
            return Path(self.prompt_file).read_text()
        return self.prompt_inline or f"You are the {self.name} agent."

    def to_agent_definition(self) -> AgentDefinition:
        """Convert to SDK AgentDefinition for session creation."""
        return AgentDefinition(
            description=self.description,
            prompt=self.prompt,
            tools=self._resolve_tool_names(),
        )
```

### 10.3 ToolModule Contract

```python
class ToolModule(Protocol):
    """Contract for tool modules registered with the Capabilities Hub.

    Modules are the unit of tool registration. Each module:
    - Owns a set of related tool functions
    - Manages its own credential injection
    - Filters tools per-agent based on agent spec config
    - Provides health checking for its backing service
    - Can be registered/unregistered at runtime (thin proxy pattern)
    """

    name: str                           # e.g., "obsidian", "email", "paperless"

    def configure(self, store: CredentialStore) -> None:
        """Inject credentials from the store.

        Called at startup AND on hot-reload (when credentials rotate
        or module config changes). Must be idempotent.
        """
        ...

    def get_tools_for_agent(
        self, agent_name: str, config: AgentToolModuleConfig
    ) -> list[Callable]:
        """Return tool functions accessible by this agent.

        Filters by config.tools (allowlist) and config.confirm_gated.
        The returned callables are bound methods with credentials
        captured via self — credentials never appear as parameters.
        """
        ...

    def get_all_tool_names(self) -> list[str]:
        """Return all tool names this module can provide.

        Used by the proxy layer to create stable MCP tool names
        at session creation time.
        """
        ...

    async def health_check(self) -> ModuleHealthStatus:
        """Check module health (can reach backing service?).

        Returns ModuleHealthStatus with status, latency, and optional message.
        Called periodically by the Capabilities Hub health monitor.
        """
        ...


@dataclass
class ModuleHealthStatus:
    """Health check result for a tool module.

    Distinct from ProviderHealthStatus (Section 8.3) which tracks
    infrastructure-level health with uptime/restart counters.
    """
    status: str                         # "ok", "degraded", "down"
    latency_ms: float | None = None
    message: str | None = None
    checked_at: datetime | None = None
```

### 10.4 EventSink Protocol

```python
class EventSink(Protocol):
    """Protocol for event consumers."""

    async def write(self, event: dict[str, Any]) -> None:
        """Write a single event. Must not raise on failure."""
        ...
```

Current implementation: `JSONLFileSink`. Future: `LokiPushSink`, `StdoutSink`, `WebhookSink`.

### 10.5 ProviderConfig Contract

```python
@dataclass
class ProviderConfig:
    name: str                                       # Unique identifier
    env_vars: list[str]                             # Required env vars
    health_check: Callable[[], Awaitable[HealthStatus]]
    create_tools: Callable[[Any], list]             # Tool factory
    scoping: dict[str, Any] | None = None           # Per-agent scoping
    restart: Callable[[], Awaitable[None]] | None = None
```

### 10.6 Standard Response Format

All tool modules return responses in a consistent format:

```python
def _make_tool_response(data: Any) -> dict[str, Any]:
    """Wrap data in standard tool response format, sanitizing output."""
    text = sanitize(json.dumps(data))
    return {"content": [{"type": "text", "text": text}]}

def _make_error_response(error_msg: str) -> dict[str, Any]:
    """Wrap error in standard tool response format."""
    return {"content": [{"type": "text", "text": sanitize(json.dumps({"error": error_msg}))}]}
```

This format matches what the Claude Agent SDK expects from MCP tool results.

### 10.7 Missing Contracts (Referenced but Not Yet Defined)

These types are referenced throughout the architecture. Definitions here are the canonical source.

```python
# --- Agents Hub contracts ---

@dataclass
class AgentPatch:
    """Partial update for an existing agent spec."""
    description: str | None = None
    model: str | None = None
    fallback_model: str | None = None
    prompt_file: str | None = None
    prompt_inline: str | None = None
    tools: dict | None = None          # Partial merge into existing tools
    memory: dict | None = None         # Partial merge into existing memory config
    enabled: bool | None = None
    permission_mode: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    effort: str | None = None


@dataclass
class ReloadResult:
    """Result of AgentRegistry.reload()."""
    loaded: int                        # Number of agents successfully loaded
    failed: int                        # Number of agents that failed validation
    errors: list[str]                  # Validation error messages
    changed: list[str]                 # Names of agents whose config changed
    unchanged: list[str]               # Names of agents with no changes


class ValidationError:
    """Agent spec validation error (NOT Pydantic's ValidationError)."""
    field: str                         # "tools.modules.email", "memory.own_domain", etc.
    message: str                       # "Tool module 'email' not registered in CapabilitiesHub"
    severity: str                      # "error" (blocks load) | "warning" (logged, load proceeds)


# --- Capabilities Hub contracts ---

class PolicyDecision(str, Enum):
    """Result of cascading deny-wins policy evaluation."""
    ALLOW = "allow"           # Tool call proceeds
    DENY = "deny"             # Tool call blocked (deny wins)
    CONFIRM = "confirm"       # Tool call needs user approval
    NOT_FOUND = "not_found"   # Tool or module not registered


@dataclass
class ModuleInfo:
    """Summary info for a registered tool module."""
    name: str                          # "paperless", "firefly", etc.
    tool_count: int                    # Number of tools in the module
    tool_names: list[str]              # ["search", "get_document", "tag", ...]
    health: ModuleHealthStatus         # Current health status
    confirm_gated: list[str]           # Tools that require user confirmation


@dataclass
class SessionOverrides:
    """Per-session tool policy overrides (runtime API)."""
    blocked_tools: list[str] = field(default_factory=list)     # Additional tools to block
    blocked_modules: list[str] = field(default_factory=list)   # Additional modules to block
    read_only: bool = False            # Block all write/mutating tools
    reason: str = ""                   # Why the override was applied


# --- Global config contracts ---

@dataclass
class GlobalConfig:
    """Top-level Corvus configuration from corvus.yaml."""
    blocked_tools: list[str] = field(default_factory=list)     # Globally blocked tool names
    disabled_modules: list[str] = field(default_factory=list)  # Globally disabled modules
    default_model: str = "claude-sonnet-4-6"
    default_fallback_model: str = "claude-haiku-4-5-20251001"
    default_max_turns: int = 50
    default_max_budget_usd: float = 1.00
    watcher_mode: str = "smart"        # "smart" | "hot" | "off"
    watcher_debounce_s: float = 1.0
    audit_enabled: bool = True
    break_glass_enabled: bool = True


# --- WebSocket protocol contracts ---

@dataclass
class WSClientMessage:
    """Client-to-server WebSocket message."""
    type: str                          # "chat" | "confirm_response" | "ping" | "spawn"
    content: str | None = None         # Chat message text
    agent: str | None = None           # For "spawn": target agent name
    tool_use_id: str | None = None     # For "confirm_response": which tool
    approved: bool | None = None       # For "confirm_response": user decision


@dataclass
class WSServerMessage:
    """Server-to-client WebSocket message."""
    type: str                          # "assistant" | "confirm_prompt" | "error" | "system" |
                                       # "stream" | "agent_switch" | "pong"
    content: str | None = None         # Text content
    agent: str | None = None           # Which agent is speaking
    tool_name: str | None = None       # For "confirm_prompt"
    tool_input: dict | None = None     # For "confirm_prompt"
    tool_use_id: str | None = None     # For "confirm_prompt"
    session_id: str | None = None      # For "system" init
    error: str | None = None           # For "error"
    cost_usd: float | None = None      # For session-end summary
```

### 10.8 Concurrency Model

Corvus handles multiple simultaneous sessions via async Python. Key concurrency concerns:

```
Shared mutable state (module-level singletons):
    ToolProviderRegistry    -- read-heavy, write on reload/register
    AgentSupervisor         -- read-heavy, write on heartbeat
    CronScheduler           -- write on trigger/update
    EventEmitter            -- write-heavy (append-only JSONL)
    CapabilitiesHub         -- read-heavy, write on register/unregister
    AgentsHub               -- read-heavy, write on create/update/reload
    MemoryHub               -- write on save, read on search

Session-isolated state (per WebSocket):
    ClaudeSDKClient         -- one per session
    SessionOverrides        -- per-session policy
    confirm_gated_tools     -- per-session from agent spec
    session_id, agent_name  -- per-session identity
```

**Concurrency rules:**

1. **SQLite WAL mode** for all databases. Concurrent reads are lock-free. Writes are serialized but non-blocking.
2. **asyncio.Lock** on Hub registries for write operations (reload, register, create). Reads are lock-free.
3. **No shared mutable state between sessions** except the Hub registries (which are protected by locks).
4. **Scheduler-session isolation**: Scheduled prompts create their own sessions. They don't interfere with user sessions.
5. **Multiple browser tabs**: Each tab gets its own WebSocket → own session → own ClaudeSDKClient. No shared conversation state.

### 10.9 Failure Modes

| Failure | Detection | Impact | Recovery |
|---------|-----------|--------|----------|
| Anthropic API down | `ResultMessage` error type `"server_error"` | Routing fails (Haiku unavailable), agent queries fail | `fallback_model` if configured; otherwise return error to user |
| Tool module backend down (Paperless, Firefly) | Health check in supervisor heartbeat (30s) | Tools return errors. Agent sees error but continues conversation. | Supervisor attempts restart (max 3). Circuit breaker after 5 consecutive failures. |
| Primary memory DB (SQLite) fails | Write returns error | Memory save fails. Critical error. | Return error to agent. Log CRITICAL event. Do not lose the data silently. |
| Overlay memory backend fails | Write fan-out catches exception | Primary still works. Overlay data is stale. | Log warning. Continue with primary. Auto-recover on next heartbeat. |
| WebSocket disconnect mid-tool | SDK handles cleanup internally | Tool call may complete but result is lost | Stop hook still fires for memory extraction (if SDK delivers it). |
| Credential store decryption fails | Startup error (SOPS/age) | No tools can be configured with credentials | Fall back to `CredentialStore.from_env()` (env vars). Log warning. |
| Invalid agent config on reload | Validation rejects spec | Previous valid config stays active | Return structured errors in `ReloadResult`. Emit `config_validation_error` event. |
| Session hits `max_budget_usd` | SDK enforces internally | Agent stops. `ResultMessage` returned. | User starts new session. Budget is per-session, not global. |
| Context window full | SDK triggers auto-compaction | `PreCompact` hook fires. Full transcript archived. | Conversation continues with summarized context. Long-term memory preserved via Stop hook. |

### 10.10 Startup Ordering

```
1. Load GlobalConfig from corvus.yaml
    |
2. Initialize CredentialStore
    +-- SOPS+age decrypt → in-memory store
    +-- Fallback: from_env() if no SOPS file
    |
3. Initialize EventEmitter + JSONLFileSink
    |
4. Initialize MemoryHub
    +-- Create/migrate SQLite FTS5 primary
    +-- Register overlay backends (best-effort)
    |
5. Initialize CapabilitiesHub
    +-- Register tool modules
    +-- CredentialStore.inject() → configure() each module
    +-- register_credential_patterns() for sanitization
    |
6. Initialize AgentsHub
    +-- AgentRegistry.load(config_dir)
    +-- Validate all specs against CapabilitiesHub + MemoryHub
    +-- Build AgentDefinitions
    |
7. Initialize AgentSupervisor
    +-- Start 30s heartbeat loop
    |
8. Initialize CronScheduler
    +-- Load schedules from YAML + DB
    +-- Start APScheduler
    |
9. Start FastAPI (uvicorn)
    +-- WebSocket /ws ready
    +-- REST API ready
    +-- Health endpoint /health ready
```

**Partial failure policy**: Steps 1-3 must succeed or the server exits. Steps 4-8 log errors but allow startup to continue in degraded mode. Step 9 always starts — the health endpoint reports which subsystems are degraded.

---

## 11. Developer Experience

### 11.1 Test Infrastructure

**NO MOCKS policy** -- all tests exercise real systems:

| Test Type | Approach |
|-----------|----------|
| Database tests | Create real SQLite DB, seed, query, verify, tear down |
| Vault/filesystem | Write real files to temp directory, verify on disk |
| CLI tests | Run scripts as real subprocesses, verify JSON stdout |
| API tests | Use testcontainers for services |
| Memory tests | Real FTS5 search, real SQL queries |
| Tool module tests | Real HTTP against test servers or testcontainers |

**conftest.py patterns:**

```python
# tests/conftest.py -- shared fixtures

@pytest.fixture
def memory_db(tmp_path):
    """Create a real SQLite database with FTS5 for testing."""
    db_path = tmp_path / "test_memory.sqlite"
    backend = SQLiteFTS5Backend(db_path)
    return backend

@pytest.fixture
def memory_hub(memory_db):
    """Create a MemoryHub with a real primary backend."""
    config = MemoryConfig(primary_db_path=memory_db.db_path)
    return MemoryHub(config)
```

**LLM-dependent tests** use a conftest that connects to Ollama, Claude API, or another backend configured via environment:

```python
# tests/conftest.py

@pytest.fixture
def llm_client():
    """Connect to an available LLM backend for integration tests.

    Checks in order: ANTHROPIC_API_KEY (Claude), OLLAMA_URL (local).
    Skips if neither is available.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient()
    if os.environ.get("OLLAMA_URL"):
        return OllamaClient(os.environ["OLLAMA_URL"])
    pytest.skip("No LLM backend configured")
```

### 11.2 Module Development Pattern

Adding a new tool module:

1. Create `corvus/tools/{module_name}.py`
2. Implement `configure()`, tool functions, `_make_tool_response()`
3. Add credential keys to `CredentialStore.inject()` in `credential_store.py`
4. Add tool registration in `server.py` `build_options()`
5. Add agent access rules in `agent_config.py`
6. Add confirm-gated tools to `hooks.py` if destructive
7. Write behavioral tests in `tests/gateway/test_{module_name}.py`

Adding a new memory module:

1. Create `corvus/memory/backends/{module_name}.py`
2. Implement `MemoryBackend` protocol
3. Add to `MemoryConfig.overlays` in config
4. Write tests in `tests/integration/test_memory_{module_name}.py`

### 11.3 Local Development Workflow

```bash
# Setup
git clone <repo>
cd corvus
uv sync                           # Install dependencies
cp config.example/ config/         # Copy default config

# Run
mise run serve                     # Start gateway server

# Test
mise run test                      # Full test suite
mise run test:gateway              # Gateway tests only
mise run test:contracts            # Contract tests only

# Lint + Format
mise run lint
mise run format
```

### 11.4 Test Output Policy

All test runs must save full output to `tests/output/TIMESTAMP_test_XXX_results.log`:

```bash
mise run test:gateway 2>&1 | tee tests/output/$(date +%Y%m%d_%H%M%S)_test_gateway_results.log
```

---

## 12. Evolution Path

### 12.1 Current State (Slices 01-13b Complete)

```
[DONE] Infrastructure: Tailscale, Forgejo, Komodo, Observability, Backups, NFS, Authelia
[DONE] Gateway: FastAPI + WebSocket, 9 agents, hooks, MCP tools, credential store
[DONE] Memory: SQLite FTS5 + Cognee hybrid search, session extraction
[DONE] Tools: Obsidian, Email, Drive, Paperless, Firefly, Home Assistant
[DONE] Scheduling: CronScheduler with DB-backed state
[DONE] Supervisor: Heartbeat loop, auto-restart
[WIP]  Memory Hub: Three-layer architecture (design approved, implementation in progress)
```

### 12.2 Near-Term Evolution

| Priority | Work | Delivers |
|----------|------|----------|
| 1 | Memory Hub implementation | Toolkit -> Hub -> Backends architecture |
| 2 | Agents Hub | YAML-driven agent defs, live reload, admin API |
| 3 | Capabilities Hub | Thin proxy tools, cascading policy, dynamic registration, hot-reload |
| 4 | Repo split (corvus + corvus-infra) | Public framework + private deployment |
| 5 | Setup wizard (`corvus setup`) | Interactive onboarding CLI |
| 6 | SvelteKit web UI | Chat interface replacing raw WebSocket |

### 12.3 Module Rename: claw -> corvus

149 files reference "Claw/claw". The rename is a dedicated task:

1. Rename `corvus/` -> `corvus/` (Python module)
2. Update all imports, pyproject.toml, Dockerfile, compose
3. Extract personal data from prompts -> example templates
4. Update subdomain: `claw.absolvbass.com` -> `corvus.absolvbass.com`

### 12.4 Plugin System Evolution

The current tool modules are registered in `server.py`. The evolution path:

```
Current:  server.py imports and registers each tool module directly
    |
    v
Next:     CapabilitiesHub with thin proxy tools + cascading policy
          - ToolModule protocol for all modules
          - config/tools/*.yaml for module definitions
          - File watcher hot-reload (smart mode)
          - Per-turn resolution via dispatch()
          - Deny-wins policy pipeline
    |
    v
Future:   Entry-point discovery (pyproject.toml [corvus.plugins.tools])
          - uv-installable tool module packages
          - corvus-obsidian, corvus-email, corvus-paperless, etc.
          - Plugin init() API: api.register_tool() pattern
          - User-created plugins via chat
```

### 12.5 Memory Module Evolution

```
Current:  MemoryEngine + SQLiteFTS5Backend (two parallel implementations)
    |
    v
Next:     MemoryHub consolidates both, MemoryToolkit replaces CLI
    |
    v
Future:   Overlay modules via entry-point discovery
          corvus-memory-cognee, corvus-memory-vec, corvus-memory-corpgen
```

### 12.6 Architecture Decision Records

Key decisions that shaped this architecture:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Runtime | Python only | Single language, team expertise, Claude SDK is Python |
| Agent SDK | Claude Agent SDK | Built-in agent loop, MCP, hooks -- saves ~24h of custom code |
| Tool isolation | In-process MCP servers | Credential closure pattern, zero-copy, no IPC overhead |
| Memory primary | SQLite FTS5 | Zero-dependency, local-first, battle-tested |
| Identity injection | Closures | Agent cannot override identity -- baked at spawn time |
| Secret storage | SOPS+age | Encrypted at rest, decrypted only in memory, never in prompts |
| Testing | No mocks | Behavioral contracts, real systems, catches real bugs |
| Routing | LLM-based (Haiku) | Handles natural language ambiguity better than rules |
| Agent lifecycle | Per-session, not hot-loaded | No idle resource consumption, simpler lifecycle |
| Agent config | YAML + DB, not code | Live-editable, git-auditable, no restart for changes |
| Tool dispatch | Thin proxy tools | SDK can't hot-swap tools; proxies delegate to dynamic registry |
| Tool policy | Cascading deny-wins | Inspired by OpenClaw 9-tier model; layers can only narrow access |
| Tool resolution | Per-turn dispatch | Config changes take effect on next turn, no session restart |
| Terminology | "Modules" not "plugins" | Avoids confusion with SDK plugins (namespace packages) |
| Confirm-gating | `canUseTool` callback | SDK-native human-in-the-loop; bridges to WebSocket for user approval |
| Cost control | `max_budget_usd` per session | SDK enforces hard spending cap; prevents runaway agent costs |
| Health types | Two types: `ProviderHealthStatus` + `ModuleHealthStatus` | Infrastructure health (uptime/restarts) vs module health (latency/status) |
| Security observability | All denials/redactions emit structured events | Every security action visible in Grafana; enables alerting rules |
| Hook coverage | All 10 SDK hook events used | Complete lifecycle coverage: tool calls, agent lifecycle, compaction, permissions |
| Naming boundaries | SDK terms wrapped with Corvus prefixes | `AgentSpec` wraps `AgentDefinition`; `ToolModule` wraps `@tool`; prevents import confusion |

---

## Appendix A: File Map

```
corvus/
  __init__.py
  server.py              -- FastAPI gateway, startup, WebSocket handler
  router.py              -- RouterAgent: Haiku-based intent classifier
  agents/
    __init__.py
    hub.py               -- AgentsHub: load, validate, reload, CRUD
    registry.py          -- AgentRegistry: YAML+DB layered config
    spec.py              -- AgentSpec, AgentToolConfig, AgentMemoryConfig dataclasses
    migration.py         -- Migrate agents.py -> config/agents/*.yaml (one-time)
  agent_config.py        -- Per-agent tool + memory access config (legacy, replaced by AgentsHub)
  capabilities/
    __init__.py
    hub.py               -- CapabilitiesHub: registry, dispatch, lifecycle
    policy.py            -- ToolPolicy: cascading deny-wins evaluator
    proxy.py             -- Thin proxy tool creation for SDK
    watcher.py           -- File watcher for config/tools/*.yaml hot-reload
    registry.py          -- ToolModuleRegistry: register, lookup, health
  hooks.py               -- PreToolUse/PostToolUse security + telemetry
  session.py             -- Session transcript + memory extraction
  events.py              -- EventEmitter + JSONLFileSink
  supervisor.py          -- AgentSupervisor heartbeat loop
  scheduler.py           -- CronScheduler with APScheduler
  sanitize.py            -- Credential redaction + path traversal protection
  credential_store.py    -- SOPS+age encrypted credential management
  break_glass.py         -- Passphrase-protected privilege escalation
  config.py              -- Environment config loader
  model_router.py        -- Per-agent model assignment
  client_pool.py         -- SDK client backend resolution
  auth.py                -- Auth framework (Authelia trusted-proxy)
  webhooks.py            -- Webhook handlers (transcript, email, etc.)
  memory_backends.py     -- MemoryBackend protocol + SQLiteFTS5Backend
  kimi_bridge.py         -- Kimi K2.5 provider adapter
  kimi_proxy.py          -- Kimi proxy server
  google_client.py       -- Google API client
  yahoo_client.py        -- Yahoo IMAP client
  providers/
    __init__.py
    registry.py          -- ToolProviderRegistry + HealthStatus
  tools/
    __init__.py
    obsidian.py          -- Obsidian vault tools (search, read, write, append)
    email.py             -- Gmail/Yahoo email tools
    drive.py             -- Google Drive tools
    paperless.py         -- Paperless-ngx document tools
    firefly.py           -- Firefly III finance tools
    ha.py                -- Home Assistant tools
  memory/                -- (WIP) Memory Hub implementation
    __init__.py
    hub.py               -- MemoryHub coordinator
    record.py            -- MemoryRecord dataclass
    toolkit.py           -- create_memory_toolkit()
    config.py            -- MemoryConfig, BackendConfig
    backends/
      __init__.py
      protocol.py        -- MemoryBackend protocol
      fts5.py            -- SQLite FTS5 primary backend
      cognee.py          -- Cognee overlay (stub)
      vault.py           -- Obsidian vault writer
  cli/
    setup.py             -- Setup wizard
    screens/             -- TUI screens for setup
  prompts/               -- Per-agent prompt markdown files
scripts/
  common/
    memory_engine.py     -- Legacy MemoryEngine (being replaced by Hub)
    vault_writer.py      -- Obsidian vault writer
    cognee_engine.py     -- Cognee knowledge graph client
```

## Appendix B: Configuration Files

```
config/
  agents/                -- One YAML per agent (git-backed, live-reloadable)
    personal.yaml
    work.yaml
    homelab.yaml
    finance.yaml
    email.yaml
    docs.yaml
    music.yaml
    home.yaml
    general.yaml
  tools/                 -- One YAML per tool module (git-backed, hot-reloadable)
    paperless.yaml
    firefly.yaml
    email.yaml
    drive.yaml
    obsidian.yaml
    ha.yaml
  models.yaml            -- Global model defaults + fallback chains
  schedules.yaml         -- Cron schedule definitions
  corvus.yaml            -- Main config: global tool policy, feature flags, watcher mode

~/.secrets/
  claw.env               -- SOPS+age encrypted credentials (symlinked from .env)
  age-key.txt            -- age private key (0600)

~/.corvus/
  passphrase.hash        -- Break-glass passphrase hash (0600)
  lockout.json           -- Rate-limit state

/data/
  memory/main.sqlite     -- Memory database (FTS5 + sessions + audit)
  cognee/                -- Cognee LanceDB data

/mnt/vaults/             -- Obsidian vault (bind-mounted RW)

/var/log/corvus/
  events.jsonl           -- Structured event log -> Alloy -> Loki
```

## Appendix C: Migration from Current to Hub Architecture

| Current Component | Becomes | Status |
|------------------|---------|--------|
| `corvus/memory_backends.py` SQLiteFTS5Backend | `corvus/memory/backends/fts5.py` | WIP |
| `corvus/memory_backends.py` MemoryBackend | `corvus/memory/backends/protocol.py` | WIP |
| `corvus/memory_backends.py` MemoryResult | `corvus/memory/record.py` MemoryRecord | WIP |
| `scripts/common/memory_engine.py` MemoryEngine | Absorbed into MemoryHub + fts5.py | WIP |
| `scripts/common/memory_engine.py` SearchResult | Replaced by MemoryRecord | WIP |
| `scripts/memory_search.py` CLI | Replaced by MemoryToolkit SDK tools | WIP |
| `MEMORY_AGENT` env var pattern | Replaced by closure injection | WIP |
| `corvus/agents.py` build_agents() | `corvus/agents/hub.py` AgentsHub | Planned |
| `corvus/agent_config.py` AGENT_TOOL_ACCESS | `config/agents/*.yaml` tool specs | Planned |
| `corvus/agent_config.py` AGENT_MEMORY_ACCESS | `config/agents/*.yaml` memory specs | Planned |
| Direct `server.py` tool registration | CapabilitiesHub thin proxy dispatch | Planned |
| `CONFIRM_GATED_TOOLS` global set | Per-module confirm_gated in agent spec YAML | Planned |
| Ad-hoc tool policy in hooks.py | Cascading deny-wins ToolPolicy | Planned |
| Tool config in agent_config.py | `config/tools/*.yaml` module definitions | Planned |