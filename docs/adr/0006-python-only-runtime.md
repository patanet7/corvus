---
number: 6
title: "100% Python runtime — no Node.js"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0006: 100% Python Runtime — No Node.js

## Context

The initial architecture reviews (2026-02-26) showed code examples in TypeScript and considered Express/Fastify for the gateway. However, the team's primary expertise is Python, and running two language runtimes in a single-user self-hosted system adds deployment complexity (two package managers, two dependency chains, two build systems).

## Decision

Corvus is 100% Python. The gateway uses FastAPI + WebSocket. The `claude-agent-sdk` Python SDK communicates with the Claude Code CLI under the hood. All domain tools, memory system, and infrastructure are Python modules. No Node.js commands (node, npm, npx) in Docker compose, scripts, or deployment.

## Alternatives Considered

- **TypeScript gateway (Express/Fastify)**: Rejected to avoid dual-runtime complexity and because FastAPI provides equivalent async WebSocket capabilities.
- **Hybrid (Python backend + Node MCP servers)**: Rejected because in-process Python MCP servers via the SDK eliminate the need for separate Node processes.

## Consequences

- Single runtime simplifies Docker images, CI, and dependency management.
- Community MCP servers written in Node.js require wrapper scripts or reimplementation in Python.
- ACP sub-agents (Codex, Gemini CLI) may use Node.js externally, but Corvus code itself remains Python.
