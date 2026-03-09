---
number: 7
title: "uv over pip for package management"
status: accepted
date: 2026-02-28
superseded_by: null
---

# ADR-0007: uv Over pip for Package Management

## Context

Corvus uses a lockfile-based workflow to ensure reproducible builds across development and deployment. pip does not natively support lockfiles, and pip-tools adds friction. The project needed a fast, deterministic package manager that integrates lockfile generation with dependency resolution.

## Decision

Use `uv` for all package operations. `pyproject.toml` and `uv.lock` are the sources of truth. Use `uv add`/`uv remove` for dependency changes, `uv sync` for installation, and `uv run python` for script execution. Never use bare `pip install` or edit `requirements.txt` directly.

## Alternatives Considered

- **pip + pip-tools**: Rejected due to slow resolution, lack of native lockfile support, and manual compile/sync workflow.
- **poetry**: Rejected due to slower dependency resolution and heavier runtime footprint compared to uv.
- **pdm**: Rejected as less mature ecosystem tooling compared to uv at the time of evaluation.

## Consequences

- Deterministic, reproducible installs via lockfile on every `uv sync`.
- Significantly faster dependency resolution and installation compared to pip.
- Team must use `uv` commands exclusively — bare pip usage will cause drift from the lockfile.
