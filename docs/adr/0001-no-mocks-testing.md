---
number: 1
title: "Behavioral tests only — no unittest.mock"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0001: Behavioral Tests Only — No unittest.mock

## Context

Early test suites relied on MagicMock and monkeypatch to isolate units, but those tests passed even when real integrations were broken. The system's security guarantees (tool policy, credential isolation, sanitization) require end-to-end behavioral verification against real backends. Mock-heavy tests create a false sense of coverage without proving that contracts hold at runtime.

## Decision

All tests must be behavioral — exercise real setup/teardown with real databases, real files, real HTTP, and testcontainers for external services. No MagicMock, no monkeypatch, no @patch, no unittest.mock, no fakes. Tests verify contracts (input shape to output shape, status codes, required fields), not implementation details.

## Alternatives Considered

- **unittest.mock / monkeypatch**: Rejected because mocked tests pass even when the real integration is broken, hiding regressions.
- **Thin mock layer with integration tests alongside**: Rejected to avoid split-brain test suites where mocked and real tests diverge.
- **Contract-testing frameworks (Pact)**: Rejected as overkill for a single-user self-hosted system.

## Consequences

- Tests require real SQLite databases, temp directories, and testcontainers, making them slower.
- If a test cannot run without mocking, the production code must be refactored to make it testable.
- Higher confidence that passing tests reflect actual runtime behavior.
