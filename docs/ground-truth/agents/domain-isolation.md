---
subsystem: agents/domain-isolation
last_verified: 2026-03-09
---

# Domain Isolation — Workspace, Memory, and Tool Policies

Corvus enforces domain isolation at three levels: workspace isolation (each session/agent pair gets a dedicated working directory), memory domain ownership (agents can only write to their own domain), and tool policy tiers (strict/default/break_glass with deny-wins-over-allow).

## Ground Truths

- **Workspace isolation**: `workspace_runtime.py` creates per-session/agent directories under `CORVUS_AGENT_WORKSPACE_ROOT` (default `.data/workspaces/agent-runs`); supports git worktree or snapshot copy modes.
- Workspace snapshots exclude security-sensitive paths: `.env`, `.env.*`, `config/`, `CLAUDE.md`, `*.hash`, `lockout.json`, `.corvus`, plus build artifacts.
- **Memory domains**: Each agent declares `memory.own_domain` in its YAML spec; MemoryHub enforces that agents can only write to their `own_domain` or `"shared"`.
- `AgentMemoryConfig` fields: `own_domain` (required), `readable_domains` (optional cross-domain read list), `can_read_shared` (default true), `can_write` (default true).
- Unknown agents receive safe defaults: `own_domain="shared"`, `can_write=False`, `can_read_shared=True`, `readable_domains=None`.
- Cross-domain reading is explicit: `readable_domains` in YAML lists which other domains an agent can read private records from; `None` means own domain only.
- **Tool policies**: `AgentToolConfig.permission_tier` (strict/default/break_glass) determines the policy mode; `extra_deny` adds per-agent deny rules on top of global deny.
- `confirm_gated` tools in YAML specs are expanded from short dotted names (e.g. `obsidian.write`) to full MCP tool name format for SDK hooks.
- Per-agent MCP servers are namespaced: memory server is `memory_{agent_name}`, capability modules are resolved with `skip_modules=HUB_MANAGED_MODULES`.

## Boundaries

- **Depends on:** `corvus.gateway.workspace_runtime`, `corvus.memory.hub.MemoryHub`, `corvus.security.policy.PolicyEngine`, `corvus.capabilities.registry.CapabilitiesRegistry`
- **Consumed by:** `corvus.agents.hub.AgentsHub`, `corvus.gateway` (session setup)
- **Does NOT:** enforce network-level isolation, sandbox filesystem access at the OS level (Darwin sandbox profiles are separate), or manage credential injection
