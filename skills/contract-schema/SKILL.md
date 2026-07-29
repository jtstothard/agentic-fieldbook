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
| `references/domain-capability-approval.v1.yaml` | Capability-approval domain extension (leases, brokers, verification) |
| `references/capability-approval-lifecycle.md` | Canonical capability-approval lease states, transitions, and failure recovery |
| `references/independent-verification.md` | Independent verification rules for capability-approval tasks |
| `references/async-task-completion.md` | Generic async task-completion pattern with anti-pattern warning |
| `references/capability-approval-limitations.md` | Capability-approval limitations and known caveats |
| `references/contract-template.md` | Markdown presentation template for human-readable contracts |
| `references/versioning-rules.md` | Immutable core, append-only stages, material-change revision rules |
| `references/example-contract-coding.yaml` | Worked example: a coding task contract |

## Domain extension selection

Use this table to choose the right domain extension for your task:

| Task type pattern | Apply extension |
|---|---|
| Code changes, bug fixes, PRs, refactors, test additions | `domain-coding.v1.yaml` |
| Research, literature review, data gathering, analysis, synthesis | `domain-research.v1.yaml` |
| Deployments, infrastructure changes, migrations, service configuration | `domain-ops.v1.yaml` |
| Pipelines, workflows, cron jobs, alerts, webhooks, automation systems | `domain-automation.v1.yaml` |
| Capability-approval tasks (leases, brokers, independent verification) | `domain-capability-approval.v1.yaml` |
| Multi-domain (e.g., code + deployment) | Combine multiple extensions; add all relevant fields |

**Note for capability-approval tasks**: Use the `domain-capability-approval.v1.yaml` extension which includes the full lease/broker/verification schema and independent verification rules. See `references/independent-verification.md`, `references/async-task-completion.md`, and `references/capability-approval-limitations.md` for detailed guidance.

The YAML extension's defaults and comments are descriptive documentation, not runtime validation. Validate actual capability-approval contracts through the Fieldbook contract seam (`hermes aos contract --capability-approval <path>`); validation requires all extension fields, `operation_limit >= 1`, and `target_immutable: true`.

If none apply, the universal core alone is sufficient for generic task tracking.

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

## Evidence via CI escape hatch

When local test execution is not available (polyglot estates, missing SDKs, or environment constraints), the contract can specify `evidence_source: ci` in `evidence_requirements.required`. The executor declares this upfront during planning; the reviewer weights CI evidence accordingly (e.g., trusts CI pass/fail status, reviews logs for gaps). The evidence gate still requires passing CI — this is a verification method, not an evidence waiver.