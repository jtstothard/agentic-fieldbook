---
name: knowledge-lifecycle
description: Use when creating, promoting, or managing durable knowledge artifacts in the agentic operating system — skills, context docs, operating policies, or any reusable patterns. Covers scope classification, promotion rules, freshness tracking, conflict resolution, and retirement.
---

This skill defines the lifecycle policy for durable knowledge in the agentic operating system. It is a reference document — agents consult it when creating, updating, or encountering knowledge artifacts.

## Knowledge scope classification

When a task succeeds or fails, classify the lesson's scope:

| Scope | Definition | Where it lives |
|---|---|---|
| **Local** | One-off fix or observation, specific to a single task. | Stays in the task record (handoff, session summary, kanban card notes). |
| **Repository/Profile** | Recurring workflow within a bounded domain (repo, profile, or project). | Promoted to a skill or context doc under that repository/profile's `skills/` or documentation. |
| **Global** | Cross-domain workflow truth — principles that apply everywhere. | Promoted to universal operating policy under the agentic OS spec or root Hermes policy docs. |

Use the **narrowest appropriate scope**. If the lesson applies only to one repo, do not promote it to a universal policy.

## Promotion requirements

Before promoting knowledge to a durable artifact, ensure all requirements are met:

1. **Reproducible evidence**: The lesson is backed by documented evidence — tool output, test results, verified outcomes, or structured failure records. No claims without proof.
2. **No conflict with existing knowledge**: Search for existing artifacts that cover the same domain. If conflicts exist, follow the conflict resolution protocol before promotion.
3. **Provenance marker**: The artifact must include a freshness marker (see schema below) documenting source, author/lane, evidence type, dates, confidence, dependencies, and scope.
4. **Review proportional to scope**:
   - **Local**: Self-attestation by the executing lane is sufficient.
   - **Repository/Profile**: Independent review by another lane familiar with the domain.
   - **Global**: Adversarial review from at least two independent lanes, plus human approval for operating policy changes.

Promote only **validated reusable lessons**. Observations that are not yet reproducible stay local until evidence confirms them.

## Freshness marker schema

Every knowledge artifact must include a freshness marker in its header or metadata section. Required fields:

```yaml
knowledge_freshness:
  source: <origin of knowledge — task ID, session ID, ticket number>
  author_lane: <Hermes profile/role that created or validated this artifact>
  evidence_type: <execution_result | test_passage | verified_outcome | observed_failure>
  created_date: <ISO 8601 timestamp when first created>
  last_validated_date: <ISO 8601 timestamp of last validation check>
  confidence_level: <high | medium | low>
  dependencies:
    - <tool name and version, if applicable>
    - <API endpoint or service, if applicable>
    - <host or environment, if applicable>
    - <other knowledge artifacts this depends on>
  applicable_scope: <local | repository:<path> | profile:<name> | global>
```

Use the `references/knowledge-artifact-template.yaml` template in this skill directory as a starting point.

## Stale knowledge detection triggers

Stale knowledge is knowledge whose validity is in doubt. Flag knowledge as potentially stale when any trigger fires:

- **Dependency changes**: A tool, API, library, host, or service referenced in `dependencies` changes version or behavior.
- **Tool/host/API changes**: The environment a knowledge artifact assumes changes — new OS, different Python version, endpoint moved or deprecated.
- **Contradicting evidence**: New task evidence contradicts what the artifact states.
- **Expired review window**: `last_validated_date` exceeds the review window for its scope (see below).
- **Unexpected task failure**: A task that should succeed based on this knowledge fails, with no other explanation.

## Review windows by scope

| Scope | Review window |
|---|---|
| Local | No formal review — lives only in task record. |
| Repository/Profile | 3 months after `last_validated_date`. |
| Global | 6 months after `last_validated_date`. |

Review windows reset when an artifact is re-validated with fresh evidence.

## Quarantine rules

When knowledge is flagged as stale or contradicted:

1. **Do not delete**: Add a `status: quarantined` field to the freshness marker with the reason and date.
2. **Preserve visibility**: Keep the artifact readable so reviewers can see what it said and why it was quarantined.
3. **Request review**: Flag for review proportional to scope — the same review level required for promotion.
4. **Stop using**: Agents must not act on quarantined knowledge unless explicitly re-validated.

Example quarantine marker:

```yaml
knowledge_freshness:
  # ... existing fields ...
  status: quarantined
  quarantine_reason: <reason — e.g., "API endpoint deprecated", "Contradicted by task 1234">
  quarantine_date: <ISO 8601 timestamp>
```

## Conflict resolution protocol

When two or more knowledge artifacts conflict (say different things about the same domain):

1. **Flag both artifacts**: Add a `conflict_status: pending_resolution` marker to each with references to the conflicting artifacts.
2. **Determine current**: Evaluate by:
   - **Provenance**: Which artifact has stronger evidence backing? (test results, verified outcomes vs. unverified claims)
   - **Evidence quality**: Which artifact's evidence is more recent, reproducible, and comprehensive?
   - **Recency**: Which was validated more recently?
3. **Quarantine the superseded artifact**: Mark the older or weaker artifact as quarantined with the conflict reason.
4. **Preserve the stronger artifact**: Keep the current artifact active with updated `last_validated_date`.
5. **Record a decision if both appear valid**: If both artifacts seem correct under different conditions, clarify the conditions in each artifact's `applicable_scope` and document the decision in a conflict-resolution note. Never merge contradictory statements.

**Agents must STOP and request resolution** when encountering conflicting knowledge. Do not silently pick one. Use a human gate for medium/high-risk conflicts.

## Retirement procedure

When knowledge is no longer needed or is superseded by better knowledge:

1. **Mark retired with reason and date**:
   ```yaml
   knowledge_freshness:
     # ... existing fields ...
     status: retired
     retirement_reason: <reason — e.g., "Superseded by artifact X", "Domain no longer in use">
     retirement_date: <ISO 8601 timestamp>
   ```
2. **Preserve provenance trail**: Keep the retired artifact intact. Do not delete or rewrite history.
3. **Sweep downstream references**: Search for other knowledge artifacts that reference this one and update them to point to the superseding artifact or remove the reference.
4. **Feed retirement reasons back into calibration**: If retirements reveal systematic blind spots (e.g., a class of knowledge that becomes stale quickly), update calibration records to catch this earlier.

## Failure-to-process learning loop

When a task fails, turn the failure into learning:

1. **Classify the failure**:
   - **Execution**: The agent executed the plan but failed (tool errors, wrong commands, resource issues).
   - **Planning**: The plan itself was defective (wrong approach, missing steps, invalid assumptions).
   - **Review**: A reviewer missed a defect that should have been caught.
   - **Verification**: The verification step failed to detect a real problem.
   - **Context**: Missing or incorrect context caused the failure.
   - **Resource**: Insufficient or misconfigured resources (time, cost, capacity, permissions).
   - **Knowledge**: Outdated or incorrect knowledge caused the failure.

2. **Repair the immediate task**: Fix the failure, complete the work, and verify it.

3. **Determine lesson scope**:
   - If the failure is a one-off edge case → **local** only.
   - If the failure reveals a recurring pattern in a domain → **repository/profile**.
   - If the failure reveals a systemic gap in how agents work → **global** operating policy.

4. **Promote only validated reusable lessons** at the narrowest correct scope. Not every failure becomes a durable artifact.

5. **Add regression coverage** where appropriate: If the failure should have been caught by tests or review, add a check or example to prevent recurrence.

## Reference template

See `references/knowledge-artifact-template.yaml` for a complete, filled-in knowledge artifact template with all freshness markers. Use this as a starting point when creating new knowledge artifacts.