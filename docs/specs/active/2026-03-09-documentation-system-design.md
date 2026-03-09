---
title: "Corvus Documentation System"
type: spec
status: approved
date: 2026-03-09
review_by: 2026-04-09
supersedes: null
superseded_by: null
ground_truths_extracted: false
---

# Corvus Documentation System

## Problem

Design docs and specs accumulate, overlap, and drift. No single source of truth per subsystem. AI agents read stale docs and build the wrong thing. 48 plan files in 12 days with no lifecycle metadata.

## Goals

- Single source of truth per subsystem (ground truths)
- Clear lifecycle for specs and plans (creation → implementation → extraction → archive)
- Prevent drift through structural constraints, not discipline
- Keep docs terse — verbose docs over-constrain agents into stale details
- No code examples in ground truths (configs/schemas OK)

## Non-Goals

- Web-rendered documentation site
- Automated doc generation from code (future consideration)
- CI validation of frontmatter (future consideration)

## Document Types

| Type | Location | Lifecycle | Content Rules |
|------|----------|-----------|---------------|
| Ground Truth | `docs/ground-truth/` | Evergreen — updated when reality changes | Short, declarative facts. No code. ~50 line max. |
| ADR | `docs/adr/` | Frozen once accepted — never edited, only superseded | Captures why a decision was made + what was rejected |
| Spec | `docs/specs/active/` → `archive/` | Temporary — archived after implementation + extraction | Feature requirements, acceptance criteria |
| Plan | `docs/plans/active/` → `archive/` | Temporary — archived after implementation | Tasks, phases, execution order. Disposable scaffolding. |
| ARCHITECTURE.md | repo root | Evergreen — minimal topology map | ~30 lines. One diagram + subsystem table with links. |
| CLAUDE.md | repo root | Lean — points to ground truths | Under 200 lines. Universal rules only. |

## Directory Structure

```
docs/
├── ground-truth/
│   ├── index.md                 ← Registry: all subsystems, status, summary
│   ├── gateway/
│   │   ├── overview.md
│   │   ├── routing.md
│   │   └── session-management.md
│   ├── security/
│   │   ├── overview.md
│   │   ├── policy-engine.md
│   │   ├── audit.md
│   │   └── rate-limiting.md
│   ├── tui/
│   │   ├── overview.md
│   │   └── commands.md
│   ├── memory/
│   │   ├── overview.md
│   │   ├── fts5.md
│   │   └── cognee.md
│   ├── agents/
│   │   ├── overview.md
│   │   ├── prompt-composition.md
│   │   └── domain-isolation.md
│   └── model-routing/
│       └── overview.md
├── adr/
│   ├── 0001-no-mocks-testing.md
│   ├── 0002-deny-wins-over-allow.md
│   └── ...
├── specs/
│   ├── active/
│   └── archive/
├── plans/
│   ├── active/
│   └── archive/
└── templates/
    ├── ground-truth.md
    ├── adr.md
    ├── spec.md
    └── plan.md
```

## Templates

### Ground Truth

```yaml
---
subsystem: <subsystem/component>
last_verified: YYYY-MM-DD
---
```

- 3-5 sentence summary
- Bullet-point ground truths (declarative, factual)
- Boundaries section (depends on, consumed by, does NOT)
- Optional mermaid diagram (structural only, max 10-15 lines)

### ADR

```yaml
---
number: <sequential>
title: "<decision title>"
status: accepted  # proposed | accepted | deprecated | superseded
date: YYYY-MM-DD
superseded_by: null
---
```

- Context (why the decision was needed)
- Decision (what we chose)
- Alternatives Considered (what we rejected and why)
- Consequences (known tradeoffs)

### Spec / Plan Frontmatter

```yaml
---
title: "<feature name>"
type: spec  # spec | plan
status: draft  # draft | proposed | approved | implementing | implemented | superseded
date: YYYY-MM-DD
review_by: YYYY-MM-DD
supersedes: null
superseded_by: null
ground_truths_extracted: false  # gate for archiving (specs only)
---
```

## ARCHITECTURE.md

Minimal topology map. Contains:
- One mermaid diagram showing all subsystems and connections
- Subsystem table: name, one-line purpose, link to ground truth
- Updated only when subsystems are added or removed

## Spec/Plan Lifecycle

```
Draft → Proposed → Approved → Implementing → Implemented → Extract Ground Truths → Archive
```

- Brainstorming skill outputs specs to `docs/specs/active/`
- Writing-plans skill outputs plans to `docs/plans/active/`
- Ground truth extraction is a gate — specs cannot be archived without `ground_truths_extracted: true`
- Plans archive directly after completion (no extraction needed)

## Workflow Integration

- CLAUDE.md adds `## Documentation System` section pointing to `docs/ground-truth/index.md`
- CLAUDE.md rule: "Before working on a subsystem, read its ground truth file"
- CLAUDE.md rule: "After completing a spec, extract ground truths before archiving"
- Potential future skill: extract-ground-truths

## Drift Prevention

1. **Structural** — YAML frontmatter with review_by dates, supersedes/superseded_by links
2. **Process** — Extraction gate before archiving, ground truths read before implementation
3. **Automated (future)** — CI checks for frontmatter validity, expired review_by dates, broken references

## Consolidation Plan (Existing Docs)

1. Cluster existing 48 docs by feature (frontend, TUI, security, memory, gateway, agents, model-routing)
2. Per cluster: read chronologically, extract ground truths, draft ADRs for key decisions
3. Human reviews each cluster's output
4. Approved ground truths committed, specs/plans archived with frontmatter
5. ARCHITECTURE.md decomposed into ground truths + ADRs last
6. Agent-assisted, human-verified throughout

## Success Criteria

- Every subsystem has a ground truth file reachable from `index.md`
- No active spec older than its `review_by` date without explicit renewal
- CLAUDE.md under 200 lines, no subsystem-specific content
- ARCHITECTURE.md under 40 lines
- All 48 existing docs triaged, extracted, and archived
