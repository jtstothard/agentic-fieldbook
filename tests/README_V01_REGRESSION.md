# v0.1.0 Regression Harness

This directory contains the v0.1.0 regression baseline for proving that v0.2.0 is a strict additive superset of v0.1.0.

## Purpose

The regression harness captures and verifies all v0.1.0 external behavior:

- Plugin command behavior (setup, doctor, version, migrate, preflight)
- Skill content and structure (all 7 v0.1 skills)
- Plugin metadata (VERSION, plugin.yaml, setup.py)

This implements Ticket T00: the v0.1 compatibility/regression harness.

## Usage

### 1. Capture the v0.1.0 baseline

First, checkout the v0.1.0 tag and capture the baseline:

```bash
git checkout v0.1.0
python3 scripts/capture_v01_baseline.py
```

This creates `tests/.v01_baseline/v01_baseline.json` with the complete baseline.

### 2. Run the regression tests

The test harness is integrated into pytest:

```bash
python3 -m pytest tests/test_v01_regression_harness.py -v
```

These tests verify that all v0.1.0 artifacts exist and have the expected structure.

### 3. Compare against the baseline

To compare the current working tree against the v0.1.0 baseline:

```bash
python3 scripts/compare_v01_baseline.py
```

This will:
- Load the v0.1.0 baseline
- Capture current state
- Report any differences (regressions)

### 4. Verify v0.2.0 commits

For each v0.2.0 commit, run:

```bash
python3 -m pytest tests/test_v01_regression_harness.py::TestV01RegressionHarness -v
python3 scripts/compare_v01_baseline.py
```

Both should pass with no regressions.

## What is checked

### Skill structure

- All 7 v0.1.0 skills exist (contract-schema, knowledge-lifecycle, lane-calibration, planning-routing, review-calibration, risk-taxonomy, stage-handoff)
- Each skill has a SKILL.md file
- Expected references and templates exist for each skill

### Plugin metadata

- VERSION file exists and is non-empty
- plugin.yaml has correct structure (name, version, kind)
- setup.py has hermes.plugins entry point

### Plugin commands

- `setup` command runs successfully with mocked Hermes
- `doctor` command produces v0.1.0-style output
- `version` command shows bundle version and Hermes compatibility
- `migrate` command is a clean no-op

## Additive superset constraint

v0.2.0 must be a strict additive superset of v0.1.0:

- **Changes to v0.1.0 artifacts are regressions** and will be detected
- **New artifacts are allowed** (e.g., new skills, new commands, new references)
- **VERSION file changes are expected** (0.1.0 → 0.2.0)
- **Version-prefixed command output changes are expected** (e.g., "Agentic Fieldbook v0.1.0" → "v0.2.0")

## Files

- `tests/test_v01_regression_harness.py` — Pytest test suite
- `scripts/capture_v01_baseline.py` — Baseline capture script
- `scripts/compare_v01_baseline.py` — Regression comparison script
- `tests/.v01_baseline/v01_baseline.json` — Captured baseline (gitignored)

## CI Integration

Add to CI configuration (e.g., `.github/workflows/test.yml`):

```yaml
- name: Run v0.1.0 regression harness
  run: |
    python3 -m pytest tests/test_v01_regression_harness.py -v
    python3 scripts/compare_v01_baseline.py
```

This ensures every CI run preserves v0.1.0 behavior.