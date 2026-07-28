---
name: planning-routing
description: "Tiered planning, lane selection, plan validation, replanning triggers, decomposition, and the executor boundary for the agentic operating system. Load before planning, decomposing, or dispatching any non-trivial task."
---

# Agentic Operating System — Planning and Routing

## When to load

- Planning or decomposing a non-trivial task.
- Selecting an execution or review lane.
- Validating a plan before execution.
- Deciding whether to run parallel workers.
- Checking executor boundaries (what an executor cannot self-authorize).

## Trivial-task fast path

The fast path is an explicit, condensed contract—not an unrecorded exception to the operating model. It may be used only when **all** of these are true:

- The task is one atomic action (or one tightly coupled edit) with one target.
- The risk class is low after considering impact, reversibility, permissions, exposure, evidence quality, and uncertainty.
- There is no destructive, secret, billing, access, downtime, release, or production action.
- The change is locally bounded and reversible, or the task is read-only; no external notification or durable irreversible effect is created.
- Acceptance can be checked immediately with a deterministic observation, command, or answer check.
- Required evidence is available from that check, and the action fits the stated time/cost/tool/path budgets.
- No dependency, ambiguity, parallelism, or independent human approval is required.

The condensed contract must record, at minimum: `contract_id`, `revision`, objective, target, in-scope action, explicit exclusion, risk (`low`) and rationale, permitted tool/path, acceptance check, evidence to capture, executor, and escalation contact/trigger. Record the result and evidence in a stage output envelope; do not omit the evidence gate merely because the contract is condensed.

Escalate to the normal structured-plan path before acting if any eligibility condition is unknown or becomes false, if scope/target/permissions/acceptance changes, if the result is unexpected, if evidence is missing or ambiguous, if the action is not reversible, if a risk or always-ask category appears, if a dependency or budget is exceeded, or if review finds a defect. When in doubt, treat the task as non-trivial.

## Tiered planning by risk

| Risk | Planning requirement |
|---|---|
| **Trivial low-risk** | Use the fast path above; execute inline with a condensed contract and evidence record. |
| **Non-trivial low-risk** | Lightweight structured plan, possibly same session. |
| **Medium-risk** | Explicit plan artifact before execution; fresh planner context preferred. |
| **High-risk** | Separate planning/decomposition stage, impact analysis, rollback plan, human gate before mutation. |

Trivial = a single-step, low-impact task with no irreversible or externally visible side effect (e.g. reading a file, answering a question, or a bounded local edit with an immediate check). When in doubt, treat as non-trivial.

## Complexity floor classifier (mechanical refactors)

**Complexity and risk are orthogonal axes.** A low-risk task can still be bounded or open-ended, requiring more than a trivial fast path. The complexity floor classifier (agentic_fieldbook/complexity_classifier) separates mechanical operations from tasks requiring planning/decomposition:

| Complexity class | Description | Examples | Execution path |
|---|---|---|---|
| **trivial** | Zero logic decisions. Pure mechanical refactor, import rename, format pass, find-and-replace. Must meet fast-path eligibility (single atomic action, low risk, reversible, immediate check). | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`, fix typo, add import, rename variable | Direct execution with condensed contract; bypass full AOS lifecycle |
| **bounded** | Clear scope, finite known steps. May have logic decisions but all within a single contract. | Add endpoint with specified behavior, implement specific function, fix bug with known reproduction | Contract→execute→review pipeline |
| **open-ended** | Scope unclear, multiple decisions, may need decomposition or replanning. | "Improve performance", "refactor auth system", "integrate with payment gateway" | Full AOS lifecycle including planning stage |

Use `classify_complexity(issue_title, issue_body, issue_labels)` from `agentic_fieldbook.complexity_classifier` for automated classification. The classifier checks:
- Complexity floor keywords (e.g., `deprecat`, `utcnow`) as strong signals for trivial
- Mechanical patterns (rename, replace, fix typo, add import, format)
- Bounded patterns (add feature, implement function, fix bug)
- Open-ended patterns (improve, optimize, refactor without specifics, integrate)
- Fast-path eligibility (no high-risk actions, dependencies, ambiguity)

When in doubt, route as bounded or open-ended. The fast path is an optimization for clear mechanical cases; missing it is harmless, using it for non-trivial tasks is dangerous.

## Wayfinder tier (destination unclear)

The tiers above assume the *destination* is known — the objective, scope, and acceptance criteria can be stated. When they cannot — when "what does done look like?" is itself unanswered — the task is at the **wayfinder tier**, above all planning tiers. Wayfinding resolves the destination and acceptance criteria through grilling and decision tickets *before* any plan can be written or validated.

Signals you are at the wayfinder tier, not the planning tier:
- You cannot state the acceptance criteria with confidence.
- The user challenges whether you understand what they want ("are you sure you know the ACs?").
- The deliverable shape itself is undecided (config change? skill? core code? all of them?).
- Multiple distinct decisions must be made before any one of them can be planned.

**Do not propose a plan or execution before you can state the acceptance criteria.** If the user signals you jumped to execution prematurely, drop to wayfinding — do not refine the plan. Running AOS on an under-specified destination burns budget on the wrong thing; wayfinding is cheaper than rework.

## Plan validation checklist

A plan must pass ALL of these before execution begins. Invalid plans return to planning.

- [ ] **Schema** — plan follows the contract structure (contract ID, revision, objective).
- [ ] **Scope** — every action maps to an in-scope item; no out-of-scope work.
- [ ] **Dependencies** — all dependencies declared and available (or marked as blockers).
- [ ] **Capabilities** — permitted tools/paths/hosts/accounts cover every action; nothing exceeds the capability ceiling for the risk class.
- [ ] **Acceptance criteria** — every required criterion has a verification method and evidence plan.
- [ ] **Evidence plan** — for each required evidence item, the tool/command that will produce it is identified.
- [ ] **Rollback** — for medium+ risk, rollback method is specified and tested (or marked untested = risk increase).
- [ ] **Risk** — risk class confirmed; any always-ask actions flagged for human approval.
- [ ] **Resources** — time, cost, and concurrency budgets declared and within limits.

## Lane selection

Routing selects lanes by these dimensions, in priority order:

1. **Domain/profile fit** — does the lane support this domain and task class? (Check lane calibration record.)
2. **Risk class** — is the lane trusted for this risk class? (Uncalibrated lanes → low-risk only.)
3. **Permissions** — does the lane have the required tool/path/host/account access?
4. **Evidence needs** — can the lane produce the required evidence quality?
5. **Calibration** — does the lane have a valid calibration record for this task class? (Check `calibration_status`.)
6. **Independence** — for review/verification, is the lane independent from the executor? (Fresh context, separate identity, different model family where warranted.)
7. **Capacity** — is the lane available? Is capacity reserved for verification and recovery?

**Cost and latency are optimized only after the quality and safety floor is met.** A cheaper lane is never selected over a calibrated one if the cheaper lane is uncalibrated for the task class.

## Artifact-only handoff

Executors receive a **structured plan artifact** (see `stage-handoff` skill), not the planner's conversation or private reasoning. The handoff contains:

- Contract revision, ordered actions, dependencies, permitted targets, capabilities, acceptance criteria, evidence plan, risk, gates, rollback, escalation triggers, assumptions, unresolved questions, and planner identity.

**Rule:** if it's not in the handoff, the executor doesn't know it. Executors must not depend on hidden reasoning.

## Replanning triggers

Return to planning (do not improvise) when:

- A required dependency, tool, host, or target is unavailable.
- Scope, permissions, risk, or acceptance criteria change.
- A command produces an unexpected result.
- Rollback or recovery path is untested or fails.
- Required evidence cannot be produced.
- Resource, time, or cost budgets are exceeded.
- A reviewer identifies a plan defect.

**Minor mechanical corrections** within the approved envelope (typo fixes, path corrections, equivalent command swaps) are recorded but stay in the current plan. They do not trigger a full replan.

## Budget management and delivery reservation

Workers must reserve a final completion window for delivery mechanics before exhausting the iteration budget. Delivery mechanics include:

- Checking workspace state (git status, staged changes, uncommitted work)
- Committing and pushing changes
- Creating or updating pull requests
- Emitting stage output envelopes
- Calling `kanban_complete` or structured handoff

**Planning rule:** When setting iteration budgets for worker lanes, reserve the final 5-10% of the budget for delivery. This prevents the worker from reporting blocked when the core work is complete but the handoff is not.

**Execution rule:** When 80-90% of the iteration budget is consumed and the core work is complete, stop new implementation and transition immediately to delivery mechanics. Do not start new subtasks.

**Budget-exhaustion recovery:** If a worker exhausts its budget during delivery, it must snapshot the workspace state (git status, staged files, partial artifacts) and report this explicitly in the final handoff so the router can recover without manual inspection. Do not leave the workspace in an ambiguous state.

## Decomposition and parallelism

Plans that decompose into parallel work must declare:

- **Task graph** — nodes and dependency edges.
- **Shared artifacts** — which outputs are shared and who owns each workspace.
- **Exclusive resources** — hosts, paths, ports, or accounts that cannot be shared concurrently.
- **Maximum concurrency** — cap on parallel workers.
- **Reserved capacity** — capacity held back for review, verification, and recovery (do not fan out to 100% of capacity).
- **Join points** — where parallel branches must synchronize before proceeding.
- **Serialization conditions** — when branches must run sequentially (e.g. write-after-read on the same resource).

**Parallelism optimizes verified throughput, not agent count.** More workers that produce unverifiable output is not progress.

## Executor boundary

An executor may:
- Report completion (emit a stage output envelope).
- Record evidence.
- Flag blockers and risks.
- Propose replanning when triggers fire.

An executor **cannot**:
- Self-verify their own work.
- Self-approve review findings.
- Waive missing or failed evidence.
- Declare high-risk work verified.
- Change acceptance criteria to match results.

These boundaries hold regardless of risk class. For low-risk work, roles may combine (e.g. same agent executes and verifies via automated checks) — but the executor still cannot *self-attest*; verification must run an independent check even if automated.

## Investigating foreign codebases

When a task requires understanding a codebase you have not seen before — especially in a different language or ecosystem — use this methodology:

### Source acquisition

- **Clone with shallow depth** (`git clone --depth 1`) for full history only when needed.
- **GitHub raw URLs** for single-file inspection when you have the exact path.
- **GitHub Code Search API or CLI `gh search`** for locating symbols across repos when API access is available.
- **Archive.org snapshots or cached copies** as fallback when the original is inaccessible.

Use the lightest viable method. Do not clone a multi-gigabyte repo to read one file.

### Tracing patterns across ecosystems

- **Dependency injection and service registration** patterns vary by ecosystem. Look for:
  - **Rust:** `fn new()` builders, `Arc<T>` injection, macro-generated registration (`#[inject]`, service procedural macros)
  - **Go:** explicit interface-based DI, `wire` code generation, struct embedding
  - **JavaScript/TypeScript:** dependency injection containers (Inversify, Awilix), module factories, `provider` functions
  - **Python:** `@inject` decorators, `Container` classes, `__init__` parameter injection
  - **Java:** Spring annotations (`@Component`, `@Service`, `@Autowired`), XML configs
  - **.NET:** `IServiceCollection` registration, constructor injection
- **Middleware and routing:** look for pipeline registration, handler maps, routing tables, or interceptor chains near entry points.
- **Configuration loading:** check for environment variable substitution, config file parsing, and how configuration propagates to services.

Search for these patterns by language-specific keywords rather than assuming a common structure.

### Escalation criteria

Escalate to the user for repo access when:

- The repo is **private** and you lack credentials.
- The repo is **unavailable** (deleted, moved, or access-restricted) and public snapshots are insufficient.
- The task requires **write access** (you must clone with a write-capable remote).
- You need **historical context** beyond a shallow clone (blame, timeline, commit history).
- **Ecosystem-specific tooling** is required (language build systems, package managers) that you cannot run.

Continue with public sources when:

- The code is **read-only investigation** (understanding, analysis, documentation).
- **Single-file or bounded-scope** access suffices.
- The repo is **public and accessible** via clone or raw URLs.
- Public documentation, examples, or forks provide the needed context.

If unsure, state the limitation and ask: *"I can read [specific files] via public sources; do you need [full repo access / historical context / write capability]?"*

## Relationship to other skills

- **contract-schema** — provides the contract that plans operate on.
- **risk-taxonomy** — provides the risk class that determines planning tier.
- **lane-calibration** — provides the records used for lane selection.
- **stage-handoff** — provides the artifact format for plan → executor handoff.