---
name: lane-calibration
description: "Lane calibration for autonomous agents — track empirical performance per model, toolset, and task risk. New lanes start uncalibrated and are restricted to discovery and low-risk pilots until evidence exists."
author: "Jay Stothard <jtstothard@gmail.com>"
license: MIT
metadata:
  hermes:
    tags: [calibration, reliability, risk-management, methodology]
    homepage: https://github.com/jtstothard/agentic-fieldbook
    related_skills: []
---

# Lane Calibration

Calibration is the empirical process of building trust in a lane (model + toolset + provider + quantization configuration). New lanes are structurally marked **uncalibrated** and must be validated through controlled pilots before being assigned trusted risk classes.

## Core principles

- **Empirical evidence over assumptions** — trust comes from observed performance, not provider claims.
- **Start uncalibrated** — every new lane begins with `calibration_status: uncalibrated` and no trusted risk class.
- **Discovery and low-risk pilots only** — uncalibrated lanes are limited to tasks with clear rollback paths.
- **Model/provider/quantization changes require recalibration** — never extend trust across configuration changes.
- **Evidence decays** — staleness triggers trust downgrade and recalibration.

## Quick reference

Load the calibration schema:
```
skill_view(name="lane-calibration", file_path="references/calibration-schema.yaml")
```

Blank template for your first real calibration:
```
skill_view(name="lane-calibration", file_path="references/calibration-template.yaml")
```

Synthetic worked example (fabricated IDs — NOT your data):
```
skill_view(name="lane-calibration", file_path="references/calibration-example.yaml")
```

Recalibration triggers:
```
skill_view(name="lane-calibration", file_path="references/recalibration-triggers.md")
```

## Calibration lifecycle

```
uncalibrated → in_progress → calibrated → trusted (risk class assigned)
                 ↓                                          ↓
            (pilot data)                           (staleness / config change)
                                                          ↓
                                          downgrade → recalibrate
```

### Step 1: Start uncalibrated

Every new lane record begins with:
```yaml
lane_id: "your-lane-identifier"
calibration_status: uncalibrated
trusted_risk_class: null
pilot_tasks: []
```

### Step 2: Run discovery and low-risk pilots

Execute 3–5 controlled tasks that:
- Have clear success/failure criteria
- Can be rolled back without impact
- Cover representative patterns for this lane
- Are timeboxed and logged

Record outcomes in `pilot_tasks` with task IDs and results.

### Step 3: Promote to calibrated

When you have sufficient pilot evidence:
```yaml
calibration_status: calibrated
calibrated_at: "2026-01-15T10:30:00Z"
evidence_summary: "5/5 pilots passed, 0 failures, mean_duration: 12m"
```

### Step 4: Assign trusted risk class

Based on pilot quality and patterns, assign:
```yaml
trusted_risk_class: "low"  # | "medium" | "high"
trusted_at: "2026-01-20T14:00:00Z"
```

### Step 5: Monitor and recalibrate

Watch for recalibration triggers (model changes, staleness, tool permissions). Downgrade and re-run pilots when needed.

## Risk classes

| Class | When appropriate | Example tasks |
|-------|-----------------|---------------|
| `low` | Newly calibrated lanes, limited evidence | File edits, simple refactors, documentation |
| `medium` | Strong evidence, stable config | Medium-complexity features, schema changes |
| `high` | Extensive evidence, proven reliability | Critical path changes, production deployments |

Never assign a risk class without pilot evidence.

## Fallbacks

If you switch to a fallback model (e.g., outage), create a **separate lane record** with its own calibration. Do not treat an inline model swap as a calibrated fallback.

Example:
```yaml
lane_id: "primary-claude-sonnet-4-opus"
trusted_risk_class: "high"

---

lane_id: "fallback-gpt-4o-mini"
calibration_status: uncalibrated  # New lane, new evidence needed
fallback_for: "primary-claude-sonnet-4-opus"
```

## Recalibration triggers

Downgrade trust and re-run pilots when:
- Model version changes (e.g., Sonnet 3.5 → Sonnet 4)
- Provider changes (e.g., OpenRouter → Anthropic direct)
- Quantization changes (e.g., FP16 → INT4)
- Tool permission changes (e.g., new API scopes)
- Prompt system changes (e.g., new system prompt structure)
- Evidence stale (>6 months since last trusted calibration)

See `references/recalibration-triggers.md` for detailed guidance.

## Artifact checklist

When you work with lane calibration in this skill, you have access to:

1. **Schema** (`references/calibration-schema.yaml`) — data contract
2. **Template** (`references/calibration-template.yaml`) — blank starting point
3. **Example** (`references/calibration-example.yaml`) — synthetic worked example (fabricated IDs)
4. **Triggers** (`references/recalibration-triggers.md`) — when to recalibrate

All example data is synthetic and illustrative. Do not copy IDs, task references, or hostnames into your real records.

## Using this skill

When calibrating a new lane:

1. Load the schema and template
2. Create your lane record with `calibration_status: uncalibrated`
3. Run controlled pilot tasks
4. Record evidence and promote to calibrated
5. Assign a risk class based on outcomes
6. Monitor for recalibration triggers

The skill provides structure; you provide the empirical evidence.

## Further notes

- Calibration is per-model, per-configuration. Do not generalize across quantization or provider.
- Staleness is intentional: trust decays over time. Six months is a reasonable recalibration horizon.
- Evidence quality matters more than quantity. Three well-designed pilots are better than ten noisy ones.
- Worked examples use fabricated IDs. Never treat them as your data.