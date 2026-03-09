---
last_updated: 2026-03-09
---

# Corvus Ground Truth Index

## Subsystems

| Subsystem | Summary | Status | Ground Truth |
|-----------|---------|--------|--------------|
| Gateway | Central runtime: routing, sessions, WebSocket, agent dispatch | Active | [gateway/](gateway/) |
| Security | Policy engine, auth, audit, rate limiting, sanitization | Active | [security/](security/) |
| TUI | Terminal chat interface (Rich + prompt_toolkit) | Active | [tui/](tui/) |
| Memory | FTS5 + Cognee recall, Obsidian vault | Active | [memory/](memory/) |
| Agents | Domain agents, prompt composition, isolation | Active | [agents/](agents/) |
| Model Routing | LiteLLM proxy, multi-backend dispatch | Active | [model-routing/](model-routing/) |

## Active Specs

| Spec | Status | Date |
|------|--------|------|
| [Documentation System](../specs/active/2026-03-09-documentation-system-design.md) | Approved | 2026-03-09 |

## ADRs

See [docs/adr/](../adr/) for all architecture decision records.
