---
number: 5
title: "No lazy imports — all imports at module level"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0005: No Lazy Imports — All Imports at Module Level

## Context

Lazy imports (imports inside functions or behind conditionals) hide missing dependencies until runtime, making failures non-deterministic and hard to debug. In a security-critical system where tool policy and credential isolation must be reliable, import-time failures are preferable to runtime surprises.

## Decision

All imports must be at module level. No lazy imports, no conditional imports, no deferred imports inside functions. If an import fails, the process fails at startup rather than at an unpredictable point during operation.

## Alternatives Considered

- **Lazy imports for optional dependencies**: Rejected because it creates code paths that are only exercised when specific backends are active, hiding breakage.
- **importlib-based plugin loading**: Rejected because Corvus uses modules (not plugins) with explicit registration — dynamic loading adds complexity without benefit.

## Consequences

- Startup is slightly slower as all modules are loaded eagerly.
- Missing dependencies are caught immediately at process start, not mid-conversation.
- All code paths have their imports validated by simply importing the module in tests.
