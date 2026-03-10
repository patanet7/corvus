---
subsystem: agents/prompt-composition
last_verified: 2026-03-09
---

# Prompt Composition — 6-Layer Model

AgentsHub assembles agent prompts from 6 ordered layers via `_compose_prompt_layers()`. Each layer is a `PromptLayer` dataclass with `layer_id`, `title`, `source`, and `content`. Layers are joined with `\n\n---\n\n` separators for the final runtime prompt string.

## Ground Truths

- **Layer 0 — Soul**: Loaded from `config/corvus/prompts/soul.md`; fallback text asserts "You are NOT Claude" identity override. Layer ID: `soul`.
- **Layer 1 — Agent Soul**: Optional per-agent personality from `spec.soul_file`; resolved relative to `config_dir`. Layer ID: `agent_soul`.
- **Layer 2 — Agent Identity**: Dynamically generated assertion: "You are the **{name}** agent." Layer ID: `agent_identity`.
- **Layer 3 — Agent Prompt**: Loaded from `spec.prompt_file` via `spec.prompt(config_dir=...)`; falls back to a generic description if no file is set. Layer ID: `agent_prompt`.
- **Layer 4 — Sibling Agents**: Dynamically composed from all other enabled agents in the registry; includes name and description for cross-domain referral. Layer ID: `sibling_agents`.
- **Layer 5 — Memory Context**: Seeded from `MemoryHub.seed_context()` with up to 15 records; evergreen records are prefixed with `[evergreen]`. Layer ID: `memory_context`.
- `build_prompt_preview()` supports safe mode where workspace-backed layers are redacted; clips individual layers at `clip_chars` (default 1200) and total at `max_chars` (default 12000).
- `build_system_prompt()` is a thin wrapper that composes the full runtime prompt for the root SDK session (defaults to huginn).
- Missing prompt files log warnings but do not fail the build; missing soul files are silently skipped.

## Boundaries

- **Depends on:** `corvus.agents.registry.AgentRegistry` (spec lookup, enabled listing), `corvus.memory.hub.MemoryHub` (seed_context), filesystem (soul.md, prompt files)
- **Consumed by:** `AgentsHub.build_agent()` (runtime prompt), `AgentsService.get_agent_prompt_preview()` (frontend inspector)
- **Does NOT:** cache composed prompts, handle conversation history injection, or manage token budget trimming
