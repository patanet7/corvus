---
number: 8
title: "Sandbox-by-default, deny-first tool policy"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0008: Sandbox-by-Default, Deny-First Tool Policy

## Context

Corvus agents execute Bash commands, read/write files, and call external APIs. An agent with unrestricted tool access could read secrets, modify system files, or exfiltrate data. The system needs a default posture that limits blast radius when an agent misbehaves or is manipulated via prompt injection.

## Decision

All agents run in a sandbox-by-default, deny-first posture. On Darwin, sandbox uses `deny default` with workspace-only file access. Each agent gets only the tools explicitly listed in its spec. PreToolUse hooks block .env reads and credential file access. Tool results are sanitized before reaching agent context. ACP sub-agents inherit a restricted subset (intersection, never union) of their parent's permissions.

## Alternatives Considered

- **Allow-by-default with blocklist**: Rejected because new tools would be auto-available to all agents, violating least privilege.
- **Per-request user approval for all tools**: Rejected as too disruptive for a personal assistant used throughout the day.
- **Network-level isolation only**: Rejected as insufficient — file-system and tool-level restrictions are also necessary.

## Consequences

- New tools require explicit allowlisting per agent before they become available.
- Agents cannot access files outside their designated workspace without policy changes.
- Destructive operations (Gmail send, HA service calls) require explicit user confirmation via canUseTool callback.
- Security posture is auditable from agent spec YAML without reading code.
