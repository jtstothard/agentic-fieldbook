---
name: contract-schema
description: "Universal task contract schema, lifecycle state machine, stage output envelope, and domain extensions for the agentic operating system. Load when starting, planning, executing, reviewing, or verifying any non-trivial task."
---

# Agentic Operating System — Contract Schema

This skill provides the canonical contract structure for the agentic operating system. Every non-trivial task begins with a contract that makes objective, scope, risk, capabilities, acceptance criteria, evidence requirements, and roles explicit.

## When to load

- Starting a non-trivial task (anything above trivial low-risk inline execution).
- Planning or decomposing work.
- Executing a stage and producing a stage output.
- Reviewing or verifying completed work.
- Creating a stage handoff artifact.

## Canonical representation

- **YAML/JSON is canonical** for machine processing (routing, state transitions, capability checks, metrics).
- **Markdown is the readable presentation layer**, generated from or linked to the structured data.
- Every artifact carries a stable contract/task ID and revision.

## Reference files

Load these with `skill_view(name='contract-schema', file_path=...)`:

| File | Purpose |
|---|---|
| `references/contract-core.v1.yaml` | Universal core contract schema — all required fields with inline documentation |
| `references/stage-output-envelope.yaml` | Standard stage output envelope (every stage returns this) |
| `references/lifecycle-state-machine.md` | Contract lifecycle states, transitions, and rules |
| `references/domain-coding.v1.yaml` | Coding domain extension (repository, paths, tests, diff) |
| `references/domain-research.v1.yaml` | Research domain extension (sources, citations, freshness) |
| `references/domain-ops.v1.yaml` | Ops domain extension (host, backup, rollback, health probes) |
| `references/domain-automation.v1.yaml` | Automation domain extension (canary, idempotency, abort) |
| `references/contract-template.md` | Markdown presentation template for human-readable contracts |
| `references/versioning-rules.md` | Immutable core, append-only stages, material-change revision rules |
| `references/example-contract-coding.yaml` | Worked example: a coding task contract |

## Core rules

1. **Immutable core.** Once work starts, the original objective, scope, constraints, risk, and approval envelope are immutable. Material changes create a new contract revision.
2. **Append-only stages.** Execution, review, and verification append records — they never rewrite history.
3. **`reported_complete` is a claim, not a terminal state.** Only `verified` requires required evidence and acceptance checks.
4. **High-risk or always-ask tasks cannot enter mutation `executing`** until exact approval is recorded.
5. **Domain extensions never weaken the universal core** on safety or evidence. They add fields; they do not remove or relax core requirements.
6. **Empty lists are preferable to omitted fields.** A stage that found no blockers returns `blockers: []`, not a missing field — so downstream stages can distinguish "not checked" from "nothing found."

## Using the contract

```
1. Create the contract from the core schema + applicable domain extension.
2. Assign risk class (see risk-taxonomy skill).
3. Route through planning (see planning-routing skill).
4. Execute stages, each returning the standard stage output envelope.
5. Pass work between roles via stage handoff artifacts (see stage-handoff skill).
6. Verify against pre-registered acceptance criteria and required evidence.
7. Only mark `verified` when all required evidence is present and valid.
```