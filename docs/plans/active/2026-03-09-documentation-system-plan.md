---
title: "Documentation System Consolidation"
type: plan
status: implementing
date: 2026-03-09
review_by: 2026-04-09
spec: docs/specs/active/2026-03-09-documentation-system-design.md
supersedes: null
superseded_by: null
---

# Documentation System Consolidation — Implementation Plan

**Goal:** Consolidate all Corvus documentation into a structured system with YAML frontmatter, typed categories (spec/plan), lifecycle status tracking, and a directory layout that separates active from archived documents.

## Phases

1. **Add YAML frontmatter** to all existing docs in `docs/plans/` and `docs/design/`
2. **Migrate files** to new directory structure (`docs/specs/{active,archive}`, `docs/plans/{active,archive}`)
3. **Verify** old locations are empty and all supersession chains are correctly linked
4. **Extract ground truths** from implemented specs into `docs/ground-truth/` (future phase)

## Status

Phase 1-3 complete. Ground truth extraction pending.
