# Agentic Fieldbook v0.2.0 Release Readiness Report

Date: 2026-07-28
Ticket: T10
Scope: release preparation and verification

## Executive result

RELEASE READY WITH MANUAL-CLI LIMITATION

- Automated suite: PASS — 351 passed, 4 skipped, 16 warnings.
- Regression harness: PASS — 16/16 regression tests passed.
- Command structure: PASS by registration and handler tests.
- Minimal/starter implementation checks: PASS by source, asset, and test evidence.
- Fresh live `hermes aos` invocation: NOT EXECUTED — this checkout's Hermes runtime does not expose the plugin as an installed `hermes aos` command. The repository-level command seam and all related tests pass.
- v0.1 upgrade behavior: PASS by implementation and dedicated tests; not exercised against a separate live v0.1 installation.
- Git tag: NOT CREATED. The separate human-approved tagging step remains outstanding. A pre-existing local `v0.2.0` tag was observed; T10 did not create or modify tags.

## Required final test command

Command:

```text
python3 -m pytest tests/ -q --tb=short
```

Full result:

```text
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/hermes/agentic-fieldbook
configfile: pyproject.toml
plugins: anyio-4.14.1, asyncio-1.4.0, respx-0.23.1, returns-0.28.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=function
collected 355 items

tests/test_contract.py .......                                           [  1%]
tests/test_doctor.py ..................                                  [  7%]
tests/test_plugin_v01.py ...........................................     [ 19%]
tests/test_preflight.py ........                                         [ 21%]
tests/test_profile_aware_gateway.py ............................         [ 29%]
tests/test_root_entrypoint_parity.py ......                              [ 30%]
tests/test_root_gateway_detection.py ................                    [ 35%]
tests/test_root_loader_regression.py ..                                  [ 36%]
tests/test_root_plugin_layout.py .........                               [ 38%]
tests/test_setup_integration.py ...............                          [ 42%]
tests/test_t01_map_lanes_command.py ...............                      [ 47%]
tests/test_t02_lane_binding_config.py s.......................s....      [ 55%]
tests/test_t03_wizard_flow.py ......................ss..                 [ 62%]
tests/test_t04_wizard_persistence.py ....                                [ 63%]
tests/test_t05_profile_templates.py ..........................           [ 70%]
tests/test_t06_first_pilot.py ......................................     [ 81%]
tests/test_t07_install_modes.py .................                        [ 86%]
tests/test_t08_doctor_extension.py ................                      [ 90%]
tests/test_v01_regression_harness.py ................                    [ 95%]
tests/test_version_gap.py ................                               [100%]

=============================== warnings summary ===============================
tests/test_t06_first_pilot.py: 15 warnings
  <string>:5: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC.

tests/test_t06_first_pilot.py::TestFlowLogic::test_flow_handles_task_completion
  /home/hermes/agentic-fieldbook/agentic_fieldbook/first_pilot.py:312: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC.
    self.current_task.completed_at = datetime.utcnow()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 351 passed, 4 skipped, 16 warnings in 0.95s ==================
```

## Manual verification checklist

### 1. `setup --starter`

Status: PASS (repository seam); live CLI: BLOCKED

Evidence:
- `agentic_fieldbook/plugin.py` registers `setup` and mutually exclusive `--starter`/`--minimal` flags at lines 97-115.
- Starter execution persists `starter` mode and prints `Starter mode: v0.2.0 starter-kit installation.` plus `Includes profile templates and first-pilot flow.` at lines 263-273.
- `tests/test_t07_install_modes.py` covers flag registration, mode persistence, starter behavior, and upgrade behavior.
- Starter assets exist under `starter-kit/profile-templates/` for planner, executor, reviewer, and verifier.

Live limitation: `python3 -m hermes_cli ...` failed because `hermes_cli` is not importable in this environment. `hermes plugins install .` also rejected `.` because the installed plugin manager requires a Git URL or owner/repo identifier. No repository code was changed to fake this result.

### 2. `map-lanes`

Status: PASS (repository seam); live CLI: BLOCKED

Evidence:
- `agentic_fieldbook/plugin.py` registers `map-lanes` with `--interactive` and routes it through `_handle_aos_command`.
- Non-interactive output is a successful, non-destructive command response.
- Interactive mode calls `agentic_fieldbook.wizard.run_wizard`.
- `tests/test_t01_map_lanes_command.py` covers registration, parsing, routing, and output.
- `tests/test_t03_wizard_flow.py` covers all four roles, map-existing/build-from-template/skip, multi-role binding, and rerun behavior.

### 3. `doctor`

Status: PASS (repository seam); live CLI: BLOCKED

Evidence:
- Root doctor implementation reports install mode, lane-binding status, bound/unbound roles, and named verification failures.
- `tests/test_t08_doctor_extension.py` covers missing/malformed/valid lane-binding files, role reporting, starter asset checks, install mode, and integration.
- `tests/test_doctor.py` covers the original v0.1 doctor checks.

### 4. Minimal mode

Status: PASS

Evidence:
- `setup --minimal` is registered and mutually exclusive with `--starter`.
- Minimal mode persists `minimal` in `~/.hermes/plugins/agentic-fieldbook/install-mode.txt`.
- `agentic_fieldbook/templates.py` returns a deliberately nonexistent template path when `HERMES_AOS_MODE=minimal`.
- Wizard template creation refuses minimal mode and reports that template instantiation is unavailable.
- `agentic_fieldbook/first_pilot.py` documents and enforces minimal-mode bypass behavior.
- `tests/test_t05_profile_templates.py`, `tests/test_t06_first_pilot.py`, and `tests/test_t07_install_modes.py` pass.

### 5. Starter mode

Status: PASS

Evidence:
- Templates exist for all four canonical roles, each with `metadata.yaml` and `profile.yaml`.
- Template metadata contains role, required skills, and profile settings.
- `agentic_fieldbook/templates.py` implements instantiation and variable substitution.
- `agentic_fieldbook/first_pilot.py` implements low-risk task guidance and calibration capture.
- `tests/test_t05_profile_templates.py` and `tests/test_t06_first_pilot.py` pass.
- `CHANGELOG.md` and `docs/INSTALL_MODES.md` document starter mode and the first-pilot flow.

## User-story checklist from BUILD-SPEC-v0.2.md

Stories 1-22 are implemented and covered by T01-T09 as follows:

| Story | Result | Evidence |
|---:|:---:|---|
| 1 | PASS | T01/T03: separate `map-lanes` command and rerunnable wizard |
| 2 | PASS | T01: setup completion pointer; `test_t01_map_lanes_command.py` |
| 3 | PASS | T03: map-existing, build-from-template, skip options |
| 4 | PASS | T03: one profile may bind multiple roles |
| 5 | PASS | T03/T08: skipped roles remain unbound and doctor reports state |
| 6 | PASS | T02/T04: generated human-readable `~/.hermes/aos-lanes.yaml` |
| 7 | PASS | T03/T04: existing bindings preserved; atomic regeneration |
| 8 | PASS | T02/T08: doctor validates binding file |
| 9 | PASS | T04: wizard ownership and structural-drift warning |
| 10 | PASS | T07: mutually exclusive `--minimal` and `--starter` |
| 11 | PASS | T05: four role templates with metadata |
| 12 | PASS | T06: guided first-pilot command and calibration capture |
| 13 | PASS | T05-T07: minimal mode omits starter references/assets at runtime |
| 14 | PASS | T00 regression harness demonstrates additive preservation |
| 15 | PASS | T00 harness is integrated into pytest and CI; additive boundary documented |
| 16 | PASS | T06: real low-risk task guidance; synthetic pilot is not used as calibration evidence |
| 17 | PASS | T09: v0.1-to-v0.2 upgrade path documented |
| 18 | PASS | T07: v0.1 detection defaults to minimal and prints starter upgrade command |
| 19 | PASS | T09: coupled version is `0.2.0` in VERSION/plugin metadata |
| 20 | PASS | T09: adapter deferral to v0.3.0 documented in CHANGELOG/docs |
| 21 | PASS | T08: doctor validates lane-binding configuration |
| 22 | PASS | T08: doctor verifies starter-kit asset resolution |

Stories 23-26 are explicitly v0.3.0 adapter-prototype pre-work, not v0.2.0 shipped functionality. They are therefore NOT RELEASE CRITERIA for T00-T09 and are not marked as v0.2 failures. BUILD-SPEC-v0.2.md explicitly places them outside the v0.2 critical path.

## T00-T09 acceptance criteria

### T00 — v0.1 compatibility/regression harness

- PASS — Harness baseline captured under `tests/.v01_baseline/`.
- PASS — Integrated into pytest (`tests/test_v01_regression_harness.py`).
- PASS — Regression checks cover v0.1 skill structure/content and plugin metadata/commands.
- PASS — Clean v0.2 checkout passes the harness: 16/16.
- PASS — Usage documented in `tests/README_V01_REGRESSION.md`.
- PASS — CI runs `python -m pytest tests/ -v` on pushes and pull requests for Python 3.11 and 3.13.

### T01 — Profile-mapping wizard command structure

- PASS — `map-lanes` registered and routed.
- PASS — Setup prints the `map-lanes` next-step pointer.
- PASS — Basic `--interactive` parsing exists.
- PASS — Registration, routing, and output tests pass.
- PASS — v0.1 regression harness passes.

### T02 — Lane-binding config schema and persistence

- PASS — Schema defines planner, executor, reviewer, verifier.
- PASS — Read/write handles missing and malformed files.
- PASS — Doctor validates binding-file existence/schema.
- PASS — Schema, persistence, and doctor tests pass.
- PASS — Regression harness passes.

### T03 — Wizard interactive flow

- PASS — Four roles and three choices are implemented.
- PASS — Existing profile discovery works.
- PASS — Template path is integrated and guarded by mode.
- PASS — Skip and unbound-role degradation work.
- PASS — Multi-role binding works.
- PASS — Rerun preserves unchanged roles.
- PASS — Wizard tests pass.
- PASS — Regression harness passes.

### T04 — Wizard persistence and file ownership

- PASS — Atomic temp-file/rename writes.
- PASS — Structural-drift/hand-edit warning.
- PASS — Full regeneration from internal state.
- PASS — Human-readable YAML comments.
- PASS — Persistence/ownership tests pass.
- PASS — Regression harness passes.

### T05 — Profile template system

- PASS — Four canonical role templates exist.
- PASS — Metadata includes role, skills, and settings.
- PASS — Instantiation and variable substitution work.
- PASS — Wizard build-from-template path is integrated.
- PASS — Minimal mode does not resolve templates.
- PASS — Template tests pass.
- PASS — Regression harness passes.

### T06 — Guided first-pilot flow

- PASS — `hermes aos first-pilot` is registered and routed.
- PASS — Low-risk task guidance exists.
- PASS — Calibration outcome/reviewer/risk data is captured.
- PASS — Existing calibration skills are referenced/integrated.
- PASS — Minimal mode bypass is implemented.
- PASS — First-pilot tests pass.
- PASS — Regression harness passes.

### T07 — Install-time minimal vs starter choice

- PASS — Setup accepts mutually exclusive mode flags.
- PASS — Minimal mode is v0.1-equivalent and excludes starter runtime references.
- PASS — Starter mode exposes templates and first-pilot flow.
- PASS — Install mode persists and is detectable.
- PASS — v0.1 upgrade detection defaults to minimal and offers starter command.
- PASS — Install-mode, persistence, and upgrade tests pass.
- PASS — Regression harness passes.

### T08 — Doctor extension

- PASS — Doctor validates lane-binding existence/schema.
- PASS — Doctor reports bound and unbound roles.
- PASS — Doctor checks starter assets in starter mode.
- PASS — Doctor reports install mode.
- PASS — Doctor flags missing/malformed starter assets.
- PASS — Doctor integration tests pass.
- PASS — Regression harness passes.

### T09 — Version bump and CHANGELOG

- PASS — `VERSION` contains `0.2.0`.
- PASS — CHANGELOG documents v0.2.0 features and adapter deferral.
- PASS — Upgrade path is documented.
- PASS — Split release rationale is documented.
- PASS — Version references and plugin metadata are consistent under tests.
- PASS — Regression harness passes.

## Release blockers / human actions

1. Human approval is still required before creating or validating the release tag. T10 explicitly requested no tag creation; none was performed.
2. A live CLI smoke test should be run from the target Hermes installation after the plugin is installed through its supported Git/plugin-install path. The repository-level equivalent is green, but this environment could not execute `hermes aos` because the runtime/plugin was unavailable.
3. The 16 warnings are deprecation warnings from `datetime.utcnow()` in first-pilot code; they do not fail the suite but should be cleaned up in a follow-up.

No commit or push was performed.
