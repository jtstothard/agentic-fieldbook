---
name: risk-taxonomy
description: Classify task risk and apply capability ceiling rules for agentic operating system — use when classifying task risk, calculating effective risk across dimensions, determining capability ceilings, or applying human-gate approval rules.
---

Use this skill when classifying task risk, calculating effective risk across dimensions, determining capability ceilings, or applying human-gate approval rules under the agentic operating system.

## Three risk classes

| Class | Definition |
|---|---|
| **Low** | Reversible, local, read-only or easily validated; no external side effects. |
| **Medium** | Bounded mutation or meaningful user impact, but reversible with a tested rollback. |
| **High** | Broad blast radius, production impact, security/privacy implications, or difficult recovery. |

## Always-ask overlay

Regardless of class, these actions **always** require explicit human approval:

- Destructive or irreversible operations
- Secret or credential access or rotation
- Billing-affecting changes
- Access or permission grants
- Downtime-affecting changes
- Release decisions

These cannot be downgraded. Even if classified Low, if an always-ask action applies, human approval is required.

**Capability-approval tasks** are **High-risk and always-ask** — the approval step itself is a human gate required before any capability can be leased or used. See the contract-schema skill for the capability-approval domain extension and independent verification rules.

## Effective risk calculation

Effective risk is the **maximum** across these dimensions:

- **Impact**: Scope of consequence (local vs broad, few users vs many, transient vs permanent)
- **Reversibility**: How easily changes can be undone (no-op revert vs tested rollback vs difficult recovery)
- **Permission sensitivity**: Access level required (read-only vs write vs admin vs secrets)
- **Operational exposure**: Production exposure (none vs staging vs production vs critical infrastructure)
- **Evidence quality**: How well the plan and outcome can be verified (direct tests vs inference vs guess)
- **Uncertainty**: How much is unknown or untested (well-understood vs experimental vs speculative)

**Rule**: Missing information defaults **upward**. If uncertain, assume the higher risk classification.

## Default capability ceilings per class

| Class | Default ceiling |
|---|---|
| **Low** | Read access plus writes inside a task-scoped workspace; bounded local execution. |
| **Medium** | Low-risk capabilities plus controlled branch/draft-PR and staging mutations with rollback. |
| **High** | Read-only inspection, dry-runs, planning, backup/rollback preparation, and evidence gathering until approval. |

**Critical rule**: A risk class never grants access by itself. The task contract must explicitly list permitted tools, paths, hosts, accounts, and side effects.

## Risk assignment process

1. **Agent proposes initial class** with factors used for each dimension
2. **Any worker, reviewer, or verifier may escalate** risk class if they identify unconsidered factors
3. **Humans may override**: lowering risk requires a recorded reason; raising risk needs no justification
4. **Always-ask actions cannot be downgraded** — human approval is required regardless of override

## Dynamic reassessment triggers

Reassess risk when any of these change **materially**:

- Scope (what's being changed)
- Target (what's being affected)
- Permissions (what access is required)
- Dependencies (what's needed to succeed)
- Evidence (what verification exists)
- Recovery plan (how to roll back)

**Stage transitions** always trigger reassessment:

- local → remote → production
- draft → published → merged → deployed

**Risk increase rule**: A risk increase pauses only the newly risky branch — other unaffected branches continue.

## Approval binding rules

Approval binds to an **exact action package**:

- Target (what's being changed)
- Scope (what's in scope and what's excluded)
- Commands (what will be executed)
- Risk class and rationale
- Rollback plan
- Monitoring approach
- Abort conditions
- Time window (how long approval is valid)

**Material changes invalidate approval** — re-approval required. Minor mechanical changes within the approved envelope remain covered.

## Emergency path

**Human-declared only**. A human must explicitly declare emergency status before execution.

Emergency requirements:

- **Minimum containment action**: Apply the smallest action that contains the issue
- **Explicit constraints**: Scope, permissions, time limit, and abort conditions
- **Logging**: All commands and evidence must be logged
- **Post-action mandatory**: Verification, rollback assessment, and incident review

**Still require authorization**: Secrets, access grants, billing, and destructive actions still require human authorization even under emergency path.

## Pitfalls

- **Assuming class grants access**: A risk class alone does not grant any capability. The contract must explicitly list permitted tools, paths, hosts, accounts, and side effects.
- **Downgrading always-ask actions**: Destructive, secret, billing, access, downtime, and release decisions always require human approval regardless of risk class.
- **Missing dimension factors**: When proposing risk, explicitly list factors for each dimension (impact, reversibility, permission sensitivity, operational exposure, evidence quality, uncertainty). Omissions default upward.
- **Ignoring stage transitions**: Local → remote → production and draft → published → merged → deployed always trigger reassessment.
- **Vague rollback plans**: Rollback plans must be specific and tested, not aspirational. Untested rollbacks increase effective risk.
- **Material changes without re-approval**: Changes to target, scope, commands, or risk invalidate existing approval.
- **Emergency without human declaration**: Only a human can declare emergency status. Agents cannot self-declare emergency.