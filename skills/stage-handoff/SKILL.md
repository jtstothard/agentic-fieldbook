---
name: stage-handoff
description: "Stage handoff artifact format for passing work between lifecycle roles (planner → executor → reviewer → verifier) without sharing transcript history. Distinct from session-compaction handoff and wayfinder planning map."
---

# Agentic Operating System — Stage Handoff Format

## When to load

- Passing work from planner to executor.
- Passing work from executor to reviewer.
- Passing review findings to fixer.
- Passing completed work to verifier.
- Any role-to-role transition within a task lifecycle.

## Three handoff layers — do not confuse them

| Layer | Purpose | Mechanism | This skill? |
|---|---|---|---|
| **Stage handoff** | Role-to-role within a task lifecycle | This artifact (structured YAML) | ✅ Yes |
| **Session handoff** | Context compaction at session edges | Native `/handoff` skill → `~/.hermes/handoffs/` | No |
| **Planning map** | Cross-session continuity for multi-session efforts | Wayfinder local-markdown map | No |

The stage handoff is **contract-state**, not **conversation-state**. It carries what the next role needs to do its job — not the reasoning history of the previous role.

## Core rule

**The receiving stage must not depend on hidden reasoning or transcript inheritance.** Everything the next role needs must be in the artifact or explicitly referenced. If it's not in the handoff, the next role doesn't know it.

## Reference files

| File | Purpose |
|---|---|
| `references/stage-handoff-schema.yaml` | Full YAML schema with all required fields |
| `references/example-planner-to-executor.yaml` | Worked example: planner → executor transition |
| `references/example-executor-to-reviewer.yaml` | Worked example: executor → reviewer transition |

## How to use

```
1. The outgoing role fills the stage handoff artifact.
2. All required fields must be populated — empty lists, not omitted fields.
3. The incoming role receives ONLY the artifact (plus the contract), not the session.
4. The incoming role works in a fresh bounded session.
5. On completion, the incoming role produces its own stage output envelope
   and (if passing to another role) a new stage handoff.
```

## Relationship to the contract

The stage handoff references the contract by ID and revision. The contract defines *what* the task is; the stage handoff defines *where the work is right now* and *what the next role must do*.

## Budget-exhaustion handoff

When a worker exhausts its iteration budget during delivery or near completion, the final handoff must include explicit workspace state so the router can recover without manual inspection:

**Required fields for budget-exhaustion handoff:**

- `work_state.snapshot`: Git status (staged, unstaged, untracked files)
- `work_state.commits_pending`: List of commits made but not pushed, if any
- `work_state.artifacts_partial`: List of partially-created artifacts (PR drafts, test results, logs)
- `work_state.delivery_blocked`: Why delivery could not complete (budget exhausted, auth failure, etc.)

**Recovery pattern:**

The router reads the snapshot, recovers the staged worktree if needed, and completes the delivery mechanics on behalf of the exhausted worker. The worker does not declare `blocked` — it declares `completion_attempted` with the snapshot attached.