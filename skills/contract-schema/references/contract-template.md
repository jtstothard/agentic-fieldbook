# Markdown Presentation Template for Human-Readable Contracts

This template shows how to render the structured contract (YAML/JSON) as human-readable Markdown. The structured format is canonical; Markdown is presentation.

---

# Contract: {{contract_id}} (Revision {{revision}})

## Objective

{{objective.summary}}

{{objective.detail}}

**Success definition:** {{objective.success_definition}}

## Scope

### In scope
{{#each in_scope}}
- {{this}}
{{/each}}

### Exclusions
{{#each exclusions}}
- {{this}}
{{/each}}

## Constraints

| Constraint | Value |
|---|---|
| Tools | {{constraints.tools}} |
| Models | {{constraints.models}} |
| Time limit | {{constraints.time_limit}} |
| Cost limit | {{constraints.cost_limit}} |
| Permissions | {{constraints.permissions}} |
| Safety | {{constraints.safety}} |

## Risk Assessment

**Class:** {{risk.class}}

**Rationale:** {{risk.rationale}}

**Effective risk factors:**
| Dimension | Level | Factors |
|---|---|---|
| Impact | {{risk.factors.impact}} | (see detailed assessment) |
| Reversibility | {{risk.factors.reversibility}} | (see detailed assessment) |
| Permissions | {{risk.factors.permissions}} | (see detailed assessment) |
| Exposure | {{risk.factors.exposure}} | (see detailed assessment) |
| Evidence quality | {{risk.factors.evidence_quality}} | (see detailed assessment) |
| Uncertainty | {{risk.factors.uncertainty}} | (see detailed assessment) |

**Always-ask actions:** {{#each risk.always_ask_actions}}- {{this}}{{/each}}

## Capabilities (least-privilege)

**Permitted tools:** {{#each capabilities.permitted_tools}}- {{this}}{{/each}}
**Permitted paths:** {{#each capabilities.permitted_paths}}- {{this}}{{/each}}
**Permitted hosts:** {{#each capabilities.permitted_hosts}}- {{this}}{{/each}}
**Permitted accounts:** {{#each capabilities.permitted_accounts}}- {{this}}{{/each}}
**Side effects:** {{#each capabilities.side_effects}}- {{this}}{{/each}}

## Acceptance Criteria

### Required
{{#each acceptance_criteria.required}}
- **{{id}}:** {{description}} (evidence: {{evidence_required}}, verify via: {{verification_method}})
{{/each}}

### Optional
{{#each acceptance_criteria.optional}}
- **{{id}}:** {{description}}
{{/each}}

## Evidence Requirements

{{#each evidence_requirements.required}}
- {{this}}
{{/each}}

## Output

**Format:** {{output.format}}
**Location:** {{output.location}}
**Artifacts:** {{#each output.artifacts}}- {{this}}{{/each}}

## Escalation

**Rules:** {{#each escalation.rules}}- {{this}}{{/each}}
**Contacts:** {{#each escalation.contacts}}- {{this}}{{/each}}

## Limits

- Time: {{limits.time}}
- Cost: {{limits.cost}}
- Stages: {{limits.stages}}

## Roles

| Role | Assigned |
|---|---|
| Requester | {{roles.requester}} |
| Planner | {{roles.planner}} |
| Executor | {{roles.executor}} |
| Reviewers | {{roles.reviewers}} |
| Fixer | {{roles.fixer}} |
| Verifier | {{roles.verifier}} |
| Approver | {{roles.approver}} |

## Lifecycle Status

**Current state:** {{lifecycle.state}}

**History:**
{{#each lifecycle.history}}
- {{timestamp}}: {{from}} → {{to}} (actor: {{actor}}, reason: {{reason}})
{{/each}}

---

*This is a presentation template. The canonical contract is in structured YAML/JSON format.*