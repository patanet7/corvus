---
number: 2
title: "Security policy — deny always wins over allow"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0002: Security Policy — Deny Always Wins Over Allow

## Context

Corvus routes user messages to domain-specific agents that each have access to different tools and services. A permissive-by-default policy risks privilege escalation when new tools are added or agent configs change. The system needs a deterministic resolution when allow and deny rules conflict.

## Decision

Deny always wins over allow at every policy layer. Tool policy uses a cascading five-layer evaluation (global deny list, agent-level deny, capability-level deny, agent-level allow, default-deny). If any layer denies, the tool call is blocked regardless of other layers granting access.

## Alternatives Considered

- **Allow-wins (last-match)**: Rejected because a single misconfigured allow rule could override critical denials.
- **Priority-weighted rules**: Rejected as too complex to audit — deny-wins is trivially verifiable.
- **Role-based access control (RBAC)**: Rejected because Corvus is single-user; per-agent tool policy is simpler and sufficient.

## Consequences

- Adding a new tool to an agent requires explicit allowlisting — no implicit access.
- Global deny list (.env reads, credential files) cannot be overridden even in break-glass mode.
- Policy auditing is straightforward: scan deny lists first, then verify allow lists.
