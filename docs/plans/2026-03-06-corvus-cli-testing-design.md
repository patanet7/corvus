# Corvus CLI + QA Testing Strategy Design

## Goal

Build `corvus chat` — an interactive terminal REPL that talks to any Corvus agent with the real stack (memory, model routing, tools, permissions). Enables testing each subsystem separately, then integrated, without the frontend.

## Architecture

### Entry Point

`mise run chat` → `uv run python -m corvus.cli.chat`

```
corvus chat                                        # interactive agent picker
corvus chat --agent homelab                        # auto model from config
corvus chat --agent finance --model ollama/qwen3:8b  # override model
corvus chat --agent homelab --resume sess-abc      # resume previous session
corvus chat --agent homelab --budget 0.50          # spend cap
corvus chat --agent homelab --max-turns 10         # for scripted testing
corvus chat --agent homelab --permission default   # test confirm flows
corvus chat --agent homelab --memory-debug         # show decay scores, seeding
corvus chat --list-agents                          # show agents + default models
corvus chat --list-models                          # show all available models
```

### Wiring — Reuse, Don't Rebuild

```
corvus chat --agent homelab
        │
        ▼
  corvus.cli.chat.main()
        │
        ├── build_runtime()              ← SAME as server.py
        │     ├── ModelRouter
        │     ├── AgentsHub
        │     ├── MemoryHub (FTS5 + overlays)
        │     ├── CapabilitiesRegistry
        │     └── LiteLLMManager
        │
        ├── resolve_backend_and_model()  ← auto from agent config
        │
        ├── build_backend_options()      ← SAME options builder (ws=None)
        │     ├── system_prompt (6-layer composition)
        │     ├── MCP servers (memory tools, capability tools)
        │     ├── can_use_tool callback (permissions + terminal confirm)
        │     ├── hooks (memory save, audit)
        │     ├── cwd → agent workspace with isolated skills
        │     └── setting_sources: ["project"] + allowed_tools includes "Skill"
        │
        ▼
  ClaudeSDKClient(options)
        │
        ├── client.query(user_input)
        ├── async for msg in client.receive_response()
        │     ├── AssistantMessage → streaming text to terminal
        │     ├── ToolUseMessage → render tool call
        │     └── ResultMessage → show session stats
        │
        └── Loop until /quit or Ctrl+D
```

### New Files

```
corvus/cli/chat.py          # Entry point + REPL loop (~200 lines)
corvus/cli/chat_render.py   # ANSI output formatting (~80 lines)
```

Everything else is reuse. Zero changes to existing options builder, runtime, or memory hub.

### REPL Interface

**Input:** `prompt_toolkit` for raw key capture, input history, tab completion.

**Interrupt:** `Escape` key (same as Claude Code).

**Commands:**
- `/agent <name>` — switch agent (new session)
- `/model <id>` — switch model mid-session
- `/fork` — branch conversation (SDK fork_session)
- `/memory search <query>` — search memory directly
- `/memory list` — list recent memories for agent's domain
- `/sessions` — list recent sessions for this agent
- `/info` — current agent, model, session stats, memory domain
- `/permissions <mode>` — switch permission mode mid-session
- `/quit` or `Ctrl+D` — exit

**Output formatting:**
- Agent name in ANSI color
- Tool calls inline: `[tool:bash] docker ps` → output
- Memory events: `[memory:save] homelab — "NAS IP is 10.0.0.50"`
- Streaming text character-by-character

### SDK Features Leveraged

| Feature | Usage |
|---|---|
| `ClaudeSDKClient` | Multi-turn REPL with streaming |
| `resume` | `--resume sess-abc` to continue sessions |
| `interrupt()` | Escape key |
| `fork_session` | `/fork` command |
| `set_model()` | `/model` mid-session switch |
| `set_permission_mode()` | `/permissions` mid-session |
| `max_budget_usd` | `--budget` spend cap |
| `max_turns` | `--max-turns` for scripted tests |
| `fallback_model` | Auto from ModelRouter config |
| `can_use_tool` | Terminal confirm flow |
| `setting_sources` + `Skill` | Demand-loaded skills per agent |
| MCP servers | Memory + capability tools |
| Hooks | Memory save, audit trail |

### Confirm-Gated Tool Flow

When a confirm-gated tool fires:

```
⚠ email_send(to="user@example.com", subject="Budget Report")

  [y] approve  [n] deny  [c] converse  [+note] add note: _
```

- `y` → `PermissionResultAllow()`
- `n` → `PermissionResultDeny(message="User denied")`
- `c` → mini conversation about the tool call, then back to y/n
- `+some note` → annotate the decision (appended to allow/deny)

Built inside the `can_use_tool` callback with `input()`. No extra infrastructure.

---

## Agent Config Restructure

### Current (scattered)

```
corvus/prompts/homelab.md           # prompt
corvus/prompts/souls/homelab.md     # soul
config/agents/homelab.yaml          # config
```

### New (co-located, isolated)

```
config/agents/homelab/
├── agent.yaml              # config (no more prompt_file/soul_file paths)
├── soul.md                 # personality
├── prompt.md               # domain instructions
├── skills/
│   ├── docker-operations.md
│   ├── loki-queries.md
│   └── mcp-tool-authoring.md
└── docs/
    ├── network-map.md
    └── container-inventory.md
```

**Convention over configuration:** AgentsHub loads `soul.md` and `prompt.md` from the agent directory by convention. No path fields needed in `agent.yaml`.

**Skills isolation:** Each agent's workspace gets only its own skills copied into `.claude/skills/`. No cross-agent skill access. Agents with `mcp-tool-authoring` skill + `Write`/`Edit` tools can create/modify their own tools. Agents without that skill can't.

**Shared skills:** Opted in via `agent.yaml`:

```yaml
skills:
  shared:
    - obsidian-vault
    - mcp-tool-authoring
```

Shared skills live in `config/skills/shared/` and get symlinked into opted-in agents' workspaces.

**Docs:** Reference material the agent can `Read` from workspace — not loaded into context unless explicitly read. Zero cost unless used.

---

## QA Testing Strategy — The Testing Ladder

Each rung tests one subsystem in isolation with `corvus chat`. The top rung tests them all together.

### Rung 1: Memory

```bash
corvus chat --agent homelab
> Remember that the NAS IP is 10.0.0.50
> /memory search NAS
# Verify: saved to homelab domain

> /quit
corvus chat --agent homelab --resume sess-xxx
> What's the NAS IP?
# Verify: recalled from memory seed context
```

**Cross-domain isolation:**
```bash
corvus chat --agent personal
> /memory search NAS
# Verify: returns nothing (personal can't read homelab)
```

### Rung 1b: Memory Temporal Behavior

```bash
corvus chat --agent homelab
> Remember that I rebooted the NAS today
> Remember that I installed Grafana last week
> Remember that Docker was set up 6 months ago

> What have I done recently?
# Verify: today's reboot ranks highest, old memories decay
```

**Verbose decay inspection:**
```bash
corvus chat --agent homelab --memory-debug
> /memory search homelab --verbose
# Shows: content, domain, created_at, decay_score, bm25_rank, final_score
```

**Evergreen vs ephemeral:**
```bash
> Remember that the NAS IP is always 10.0.0.50     # evergreen fact
> Remember that I ran a speed test today             # ephemeral

> What do you know about my homelab?
# Verify: NAS IP persists, speed test decays
```

### Rung 2: Model Routing

```bash
corvus chat --list-models
# Verify: Claude, Ollama, Kimi backends from config/models.yaml

corvus chat --agent homelab --model claude-sonnet-4-6
> Hello
# Verify: /info shows model=claude-sonnet-4-6

corvus chat --agent homelab --model ollama/qwen3:8b
> Hello
# Verify: routes through LiteLLM to local Ollama

corvus chat --agent homelab
> /model claude-haiku-4-5
> Hello
# Verify: mid-session model switch
```

### Rung 3: Agent Personality & Prompt

```bash
corvus chat --agent homelab
> /info
# Verify: shows prompt layers (soul + agent soul + identity + prompt + siblings + memory)

> Who are you?
# Verify: responds as homelab agent, not generic

corvus chat --agent finance
> Who are you?
# Verify: different personality
```

### Rung 4: Tool Permissions

```bash
corvus chat --agent homelab --permission default
> Run docker ps
# Verify: executes (homelab has Bash)

corvus chat --agent personal --permission default
> Run docker ps
# Verify: denied (personal doesn't have Bash)

corvus chat --agent homelab --permission default
> Send an email to test@example.com
# Verify: confirm prompt appears with [y/n/c/+note]
```

### Rung 5: Skills (demand-loaded)

```bash
corvus chat --agent homelab
> I need to write a LogQL query for error logs
# Verify: agent invokes loki-queries skill, uses domain knowledge

corvus chat --agent personal
> I need to write a LogQL query
# Verify: agent does NOT have loki skill, gives generic answer
```

### Rung 6: Dispatch (stretch)

```bash
corvus chat --agent huginn
> Check homelab containers and summarize my budget
# Verify: routes to homelab + finance
```

### Rung 7: Full Integration

```bash
corvus chat --agent homelab --budget 0.50
> Check if plex is running on miniserver
# Verify: bash tools, streaming, memory seeds context

> Remember that plex is running on port 32400
# Verify: memory save event

> /fork
> Actually what about on the NAS?
# Verify: forked session

> /info
# Verify: turns, cost, tokens, context %

> /quit
corvus chat --agent homelab --resume sess-xxx
> What port is plex on?
# Verify: recalls from memory
```

---

## Dependencies

- `prompt_toolkit` — Escape key, input history, tab completion, async compat
- Everything else already exists in the codebase

## Implementation Scope

1. **Agent config restructure** — move prompt/soul/skills into `config/agents/<name>/` directories
2. **Workspace skills wiring** — `prepare_agent_workspace` copies agent's skills into `.claude/skills/`
3. **`corvus/cli/chat.py`** — entry point + REPL loop (~200 lines)
4. **`corvus/cli/chat_render.py`** — ANSI formatting (~80 lines)
5. **`mise.toml`** — add `chat` task
6. **Tests** — behavioral tests for each QA rung
