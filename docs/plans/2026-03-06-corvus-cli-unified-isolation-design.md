# Corvus CLI Unified Isolation Design

## Goal

Unify `corvus chat` with the server's existing isolation infrastructure so each agent gets its own skills as slash commands while being fully isolated from the user's global Claude Code environment (plugins, settings, MCP configs).

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

## Agent Isolation Guarantees

- Agent A's skills, sessions, and config cannot leak into Agent B
- No global Claude Code plugins are accessible
- No global MCP servers are accessible
- Model routing goes through LiteLLM (not direct Anthropic API)
- System prompt is fully composed from agent config (not inherited)
- Tool permissions are scoped to the agent's spec
