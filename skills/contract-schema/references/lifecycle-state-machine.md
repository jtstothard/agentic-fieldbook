# Contract Lifecycle State Machine

## States

The contract lifecycle is a state machine with the following states:

**Primary states** (forward progression):
- `proposed` — Initial state. Contract created, not yet planned.
- `planned` — Decomposition complete, plan artifact exists.
- `approved` — Plan validated, risk assessed, approval recorded (for high-risk/always-ask).
- `executing` — Work in progress.
- `review` — Execution complete, ready for independent review.
- `verification` — Review complete, ready for final verification.
- `verified` — All acceptance criteria met, all required evidence present, task complete.

**Side states** (can be entered from any primary state):
- `blocked` — Cannot proceed; waiting on dependency, decision, or resource.
- `failed` — Cannot complete; unrecoverable error or blocker.
- `cancelled` — Task terminated before completion (user decision).
- `superseded` — Replaced by a new contract revision.

## Valid transitions

| From | To | Trigger |
|---|---|---|
| proposed | planned | Decomposition complete, plan artifact produced |
| planned | approved | Plan validation passed, risk assessed, approval obtained (if required) |
| approved | executing | Plan execution begins |
| executing | review | Execution reports `completed` outcome |
| executing | blocked | Execution reports `blocked` outcome with unresolved blockers |
| executing | failed | Execution reports `failed` outcome |
| review | verification | Review reports `completed` outcome |
| review | execution | Review reports `needs_replan` or finds defects requiring fixer work |
| review | blocked | Review reports `blocked` outcome |
| verification | verified | Verification reports `completed` outcome with all required evidence |
| verification | execution | Verification reports `needs_replan` or finds defects |
| verification | review | Verification requests additional review depth |

**Side state transitions:**
- Any primary state → `blocked` (on blocker)
- Any primary state → `failed` (on unrecoverable error)
- Any primary state → `cancelled` (user decision)
- Any primary state → `superseded` (material change → new revision)
- `blocked` → previous primary state (blocker resolved)

## Rules

1. **Forward progression requires append-only records.** Each transition appends to `lifecycle.history`. States are never rewritten.
2. **Material changes create superseded + new revision.** Changing objective, scope, risk class, or capabilities after approval is a material change. The current contract becomes `superseded`; a new revision is created.
3. **Minor corrections stay in revision.** Typo fixes, path corrections, equivalent command swaps within the approved envelope do not trigger a revision bump.
4. **High-risk/always-ask requires `approved` before `executing`.** No mutation work begins until human approval is recorded in the contract.
5. **`verified` is terminal.** Once verified, a contract is closed. Further work requires a new contract.
6. **Side states preserve audit trail.** When entering a side state, the reason and actor are recorded in `lifecycle.history`.