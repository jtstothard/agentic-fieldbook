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