# Recalibration Triggers

When trust in a calibrated lane is no longer valid, downgrade the lane and re-run pilots before assigning a new risk class.

## Core rule

Trust is configuration-specific. Never extend trust across changes that affect the lane's behavior.

## Mandatory recalibration triggers

Downgrade to `calibrated_status: uncalibrated` and rerun pilots when any of these occur:

### 1. Model version changes

- Example: `claude-sonnet-3.5` → `claude-sonnet-4`
- Why: New models have different failure modes, token efficiency, and reasoning patterns.
- Action: Create a new lane record for the new model; calibrate from scratch.

### 2. Provider changes

- Example: OpenRouter → Anthropic direct API
- Why: Latency, reliability, and tokenization behavior differ across providers.
- Action: New lane record; recalibrate even if model name is identical.

### 3. Quantization changes

- Example: `FP16` → `INT4`
- Why: Quantization affects accuracy, especially on complex reasoning tasks.
- Action: New lane record; recalibrate.

### 4. Tool permission changes

- Example: Adding write access to production databases, new API scopes
- Why: Higher blast radius changes the risk profile of failures.
- Action: Recalibrate with the new permission set; the previous evidence does not apply.

### 5. Prompt system changes

- Example: New system prompt structure, new .hermes.md rules, SOUL.md edits
- Why: Agent behavior is sensitive to prompt context; structural changes invalidate past evidence.
- Action: Rerun a representative pilot set to confirm behavior.

### 6. Staleness

- Trigger: `staleness_months > 6` (configurable; 6 months is a reasonable default)
- Why: Model behavior drifts over time (provider-side updates), and patterns in your codebase evolve.
- Action: Run 2–3 fresh pilots to confirm the lane still behaves as calibrated. If pilots pass, update `last_verified_at` and keep the risk class. If they fail, downgrade.

## Optional recalibration triggers

Consider recalibrating when:

### Environment changes

- Example: Moving from local → Docker → SSH terminal backend
- Why: Filesystem and process isolation differences can affect tool behavior.
- Action: Rerun pilots if the new backend is materially different.

### Toolset changes

- Example: Adding `image_gen`, removing `web_search`, enabling new MCP servers
- Why: Different tools expose different failure modes and capabilities.
- Action: Run pilots that exercise the changed toolset boundaries.

### Large codebase changes

- Example: Major refactors, framework upgrades, architecture shifts
- Why: The codebase patterns the lane was calibrated against no longer apply.
- Action: Calibrate against the new codebase structure.

## Downgrade procedure

When a recalibration trigger fires:

1. Update the lane record:
   ```yaml
   calibration_status: uncalibrated
   trusted_risk_class: null
   recalibrated_at: "2026-07-01T10:00:00Z"
   recalibration_reason: "Model upgrade: claude-sonnet-3.5 → claude-sonnet-4"
   ```

2. Run a fresh pilot set (3–5 tasks covering your target patterns).

3. Record new evidence in `pilot_tasks`.

4. Promote through the lifecycle:
   - `uncalibrated` → `in_progress` → `calibrated` → `trusted` (with new risk class)

5. Update `last_verified_at` to the current timestamp.

## Fallback lanes

If you switch to a fallback lane during an outage or degradation:

- The fallback lane must have its **own** calibration record.
- Do not trust the primary lane's risk class for the fallback.
- Example:
  ```yaml
  lane_id: "primary-claude-sonnet-4"
  trusted_risk_class: "high"

  ---

  lane_id: "fallback-gpt-4o-mini"
  calibration_status: uncalibrated  # Separate evidence needed
  fallback_for: "primary-claude-sonnet-4"
  ```

## Staleness monitoring

Track staleness per lane:

```yaml
staleness_months: 8  # >6 triggers recalibration
```

Compute staleness as:
```
staleness_months = (current_date - last_verified_at) / 30.44
```

Automate detection:
- Hermes cron job can scan lane records monthly
- Flag lanes where `staleness_months > 6`
- Notify operator to rerun pilots

## Documentation

Record recalibration events in the lane's `notes` field:
```
Recalibrated on 2026-07-01 due to model upgrade. 4/4 fresh pilots passed,
restored to trusted with high risk class.
```

This maintains an audit trail of trust decisions.