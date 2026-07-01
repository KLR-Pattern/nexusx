# Phase [N]: [Phase Title]

**Feature**: [link to spec.md]
**Phase**: [0 / 1 / 2 / 3 / 4]
**Status**: [V降 — defining acceptance / 实现 — in progress / V升 — verifying / 完成]

<!--
  ============================================================================
  nexusx-4phase preset — phase-template (NEW)
  ============================================================================
  One file per phase: specs/<feature>/phaseN.md. Three sections following the
  V-model:

    V降 (left side of V) — define acceptance criteria BEFORE implementation
    实现 (bottom of V)  — record what was built (files, decisions, deviations)
    V升 (right side of V) — verify each criterion with the user, tick by tick

  A phase is NOT done until every V升 box is ticked.
  ============================================================================
-->

## 需求说明 (Requirements from conversation)

Record the user-stated requirements and constraints discussed for this phase.
Quote the user where useful. This section is append-only — do not rewrite
history when the user changes their mind, append a dated note instead.

## V降 — Acceptance Criteria

> Define BEFORE implementation. Each row must be observable and verifiable.
> No vague phrases like "code is robust" — write "GraphiQL query X returns Y".

| # | Criterion | Verification Method |
|---|-----------|---------------------|
| 1 | [observable outcome] | [curl / GraphiQL / pytest / browser / etc.] |
| 2 | ... | ... |

## 实现 — Implementation Log

### Files produced

| File | Purpose |
|------|---------|
| `src/...` | [one sentence] |

### Key decisions

- [Decision 1]: [why]
- [Decision 2]: [why]

### Deviations from plan.md

- [If something diverged from the plan, record it here with rationale.]

## V升 — Verification

Go through each V降 row in order. Tick only after the user confirms.

- [ ] 1. [criterion] — verified via [method]
- [ ] 2. [criterion] — verified via [method]

## Pitfalls encountered

1. [Pitfall + mitigation] — recorded for future phases / projects

## Phase completion

**Status when done**: every V升 box ticked, user has confirmed the phase can
close. Move on to the next phase via `/speckit-nexusx-phase <N+1>` or
`/speckit-implement`.
