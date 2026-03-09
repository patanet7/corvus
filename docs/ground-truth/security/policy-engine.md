---
subsystem: security/policy
last_verified: 2026-03-09
---

# PolicyEngine

The `PolicyEngine` loads `policy.yaml` and composes permission deny lists per agent per tier. It implements a three-tier permission model (strict, default, break_glass) where deny always wins over allow. The engine is stateless after initialization and produces deny lists consumed by both the Corvus-layer `ToolContext` and the CLI-layer `RuntimeAdapter`.

## Ground Truths

- Loaded from `policy.yaml` via `PolicyEngine.from_yaml(path)`
- `global_deny` is a list of glob patterns (e.g., `*.env*`, `*.ssh/*`) that always apply regardless of tier
- Three tiers exist, each a `TierConfig` dataclass:
  - `strict`: mode=allowlist, confirm_default=deny
  - `default`: mode=allowlist_with_baseline, confirm_default=deny
  - `break_glass`: mode=allow_all, confirm_default=allow, requires_auth=True, token_ttl=3600, max_ttl=14400
- `compose_deny_list(tier, extra_deny)` merges global_deny with per-agent extra_deny, deduplicates, and sorts
- `confirm_default(tier)` returns "deny" for unknown tiers (safe fallback)
- `tier_config(tier)` returns `None` for unknown tier names

## Boundaries

- **Depends on:** `config/policy.yaml`
- **Consumed by:** `ToolContext`, `RuntimeAdapter`, `AgentsHub`
- **Does NOT:** execute tool calls, manage sessions, handle authentication
