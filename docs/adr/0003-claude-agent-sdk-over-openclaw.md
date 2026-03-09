---
number: 3
title: "Claude Agent SDK over OpenClaw"
status: accepted
date: 2026-02-26
superseded_by: null
---

# ADR-0003: Claude Agent SDK Over OpenClaw

## Context

Corvus originally ran on OpenClaw as its agent runtime. Three independent architecture reviews (2026-02-26) found that OpenClaw only provided three capabilities not available elsewhere (web UI, hybrid-search memory, webhook endpoint), while requiring 30+ hours of tightly-coupled plugin development for Slices 12-20. The Claude Agent SDK was identified as a higher-level alternative that provides agent loop, subagent routing, hooks, MCP support, and permissions natively.

## Decision

Replace OpenClaw with the Claude Agent SDK (`claude-agent-sdk` on PyPI) as the agent runtime. Build the gateway (FastAPI + WebSocket), memory system (SQLite FTS5), and domain tools as Corvus-owned Python modules rather than OpenClaw plugins.

## Alternatives Considered

- **Keep OpenClaw (Option A)**: Rejected due to 30+ hours of remaining plugin work, underdocumented SDK, and deep coupling to a project we do not maintain.
- **Raw Claude SDK (Option B original)**: Rejected because it required rebuilding agent loop, tool execution, hooks, and session management (~200-300 lines of glue) that the Agent SDK provides natively.
- **Claude Code as runtime (Option C)**: Rejected because it has no web UI, no persistent server, and no webhook endpoint — unsuitable as a primary assistant.

## Consequences

- Web UI and webhook endpoint must be built in-house (FastAPI + WebSocket).
- Memory system rebuilt on SQLite FTS5 with optional overlays (Cognee, sqlite-vec).
- Full ownership of the stack — no upstream breakage risk from OpenClaw releases.
- MCP tools built for Corvus are portable to Claude Code, VS Code, and other MCP clients.
