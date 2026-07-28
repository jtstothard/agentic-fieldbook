# Agentic Fieldbook v0.2 Implementation Tickets

**Parent spec:** `BUILD-SPEC-v0.2.md`
**Wayfinder:** `/home/hermes/agentic-fieldbook-v0.2-wayfinder.md`
**Status:** Ticket breakdown ready for implementation
**Date:** 2026-07-27

## Ticket T00: v0.1 compatibility/regression harness

**User stories covered:** None (enabler for all subsequent tickets)

**What to build:**
An automated regression harness that captures v0.1.0's external behavior and proves that every subsequent v0.2.0 commit preserves it as a strict additive superset. The harness must:
1. Run against the tagged v0.1.0 release to establish a baseline
2. Capture all plugin command behavior (`hermes aos setup`, `hermes aos doctor`, `hermes aos version`, `hermes aos preflight`)
3. Capture skill content and structure (all 7 v0.1 skills, their SKILL.md files, references/templates)
4. Capture plugin metadata (VERSION file, plugin.yaml, setup.py entry points)
5. Run on every commit and fail if any regression is detected
6. Be invoked by the test suite (pytest) and run automatically on CI

This implements the TDD requirement (red-green from commit one) and the "prove additive-superset by automation, not inspection" user-approved decision.

**Acceptance criteria:**
- [ ] Harness runs successfully against v0.1.0 tag and captures baseline
- [ ] Harness is integrated into pytest test suite
- [ ] Harness fails if any v0.1.0 behavior changes (plugin commands, skill content, metadata)
- [ ] Harness passes on a clean v0.2.0 checkout with no changes
- [ ] Harness is documented in tests/ with usage instructions
- [ ] CI configuration runs harness on every commit

**Blocked by:** None — can start immediately

---

## Ticket T01: Profile-mapping wizard command structure

**User stories covered:** 1, 2

**What to build:**
The basic command structure for `hermes aos map-lanes`, the separate profile-mapping wizard command. This includes:
1. Command registration in plugin.py entry points
2. Basic CLI argument parsing (no subcommands yet, just stub `map-lanes`)
3. Stub handler that prints "Profile mapping wizard coming in T02"
4. Integration with `setup` command to print "Next step: run `hermes aos map-lanes` to bind profiles to AOS roles"
5. Test coverage for command registration and setup pointer

This is a tracer-bullet slice: it cuts through plugin CLI, entry points, and command routing, but doesn't implement wizard behavior yet.

**Acceptance criteria:**
- [ ] `hermes aos map-lanes` command is registered and runs
- [ ] `hermes aos setup` prints pointer to `map-lanes` on completion
- [ ] Command has basic argument parsing structure in place
- [ ] Tests verify command registration and setup pointer
- [ ] All existing plugin commands remain functional (regression harness passes)

**Blocked by:** T00 (regression harness)

---

## Ticket T02: Lane-binding config file schema and persistence

**User stories covered:** 6, 8, 9

**What to build:**
The lane-binding config file structure and persistence layer. This includes:
1. YAML schema for `~/.hermes/aos-lanes.yaml` defining AOS roles (planner, executor, reviewer, verifier) and their profile bindings
2. Schema validation logic (using pydantic or similar)
3. File read/write functions that preserve YAML comments and formatting
4. Logic to handle missing file (treat as all roles unbound) and malformed file (report via doctor)
5. Integration with `doctor` command to validate binding file existence and schema
6. Tests for schema validation, read/write persistence, and doctor integration

This slice cuts through schema definition, persistence, and verification but doesn't implement wizard UI yet.

**Acceptance criteria:**
- [ ] `aos-lanes.yaml` schema is defined and validated
- [ ] File read/write preserves YAML structure and handles missing/malformed files
- [ ] `doctor` validates binding file existence and schema
- [ ] Tests cover schema validation, persistence, and doctor integration
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T01 (wizard command structure)

---

## Ticket T03: Wizard interactive flow per role

**User stories covered:** 1, 3, 4, 5, 7

**What to build:**
The interactive wizard flow that prompts the user for each AOS role. This includes:
1. Interactive CLI flow for each of the 4 AOS roles (planner, executor, reviewer, verifier)
2. Per-role prompt offering three options: (a) map existing profile, (b) build from template, (c) skip
3. Profile discovery: list available Hermes profiles for "map existing" option
4. Multi-role support: allow one profile to be bound to multiple roles
5. Skip degradation: mark role as unbound, continue gracefully
6. Re-run preservation: read existing binding file on load, preserve unchanged roles when updating one role
7. Tests for wizard flow, profile discovery, multi-role binding, and re-run preservation

This slice cuts through wizard interaction, profile discovery, and binding logic.

**Acceptance criteria:**
- [ ] Wizard prompts for all 4 AOS roles with three-option menu
- [ ] "Map existing" discovers and lists available Hermes profiles
- [ ] "Build from template" stub points to T05 (template system)
- [ ] "Skip" marks role as unbound and continues
- [ ] One profile can be bound to multiple roles
- [ ] Re-running wizard preserves unchanged roles from existing binding
- [ ] Tests cover wizard flow, profile discovery, multi-role binding, and re-run
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T02 (binding file schema and persistence)

---

## Ticket T04: Wizard persistence and file ownership

**User stories covered:** 6, 7, 9

**What to build:**
The wizard's file ownership semantics and persistence behavior. This includes:
1. Atomic write semantics: write to temp file, then rename over target (avoid corruption)
2. Ownership declaration: wizard is canonical editor; direct edits are "you own it now"
3. Wizard refuses to overwrite a hand-edited file with structural changes (warns user)
4. Regeneration on save: re-writes entire file from wizard state (not incremental patches)
5. Human-readable output: clean YAML formatting with comments
6. Tests for atomic writes, ownership warnings, regeneration, and formatting

This slice cuts through file ownership semantics and safe persistence.

**Acceptance criteria:**
- [ ] Wizard writes atomically (temp file + rename)
- [ ] Wizard warns if file appears hand-edited (structural drift)
- [ ] Wizard regenerates entire file from internal state
- [ ] Output is human-readable YAML with comments
- [ ] Tests cover atomic writes, ownership warnings, and regeneration
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T03 (wizard interactive flow)

---

## Ticket T05: Profile template system

**User stories covered:** 11, 13

**What to build:**
The profile template system for starter-kit's first leg. This includes:
1. Template directory structure under `starter-kit/profile-templates/`
2. Templates for each canonical AOS role (planner, executor, reviewer, verifier)
3. Template metadata file (YAML) defining role, required skills, profile settings
4. Template instantiation logic: copy template to new profile path, substitute variables
5. Integration with wizard's "build from template" option
6. Tests for template structure, instantiation, and wizard integration
7. Bypass by `--minimal` install: templates not installed or referenced

This slice cuts through template definition, instantiation, and wizard integration.

**Acceptance criteria:**
- [ ] Profile templates exist for all 4 canonical AOS roles
- [ ] Templates include metadata (role, skills, settings)
- [ ] Instantiation logic copies template and substitutes variables
- [ ] Wizard's "build from template" option instantiates templates
- [ ] Templates not installed or referenced in `--minimal` installs
- [ ] Tests cover template structure, instantiation, and wizard integration
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T04 (wizard persistence)

---

## Ticket T06: Guided first-pilot flow

**User stories covered:** 12, 16

**What to build:**
The guided first-pilot flow that walks users to their first real calibration data point. This includes:
1. Command `hermes aos first-pilot` or integration into `map-lanes` completion
2. Step-by-step guidance: choose low-risk task, run through AOS lifecycle, capture calibration data
3. Task guidance framework: what qualifies as low-risk, how to select, how to document
4. Calibration data capture: record task outcome, reviewer scores, risk classification
5. Integration with existing calibration skills (contract-schema, lane-calibration, review-calibration)
6. Tests for flow logic, task guidance, and calibration data capture
7. Bypass by `--minimal` install: flow not available or referenced

This slice cuts through pilot guidance, calibration capture, and skill integration.

**Acceptance criteria:**
- [ ] First-pilot flow is accessible via command or wizard completion
- [ ] Flow guides user through low-risk task selection and execution
- [ ] Calibration data is captured and stored
- [ ] Flow integrates with existing calibration skills
- [ ] Flow not available or referenced in `--minimal` installs
- [ ] Tests cover flow logic, task guidance, and calibration capture
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T05 (profile templates)

---

## Ticket T07: Install-time minimal vs starter choice

**User stories covered:** 10, 13, 18

**What to build:**
The install-time choice between `--minimal` and `--starter` modes. This includes:
1. Update `setup` command to accept `--minimal` or `--starter` flag
2. `--minimal`: installs v0.1-equivalent (no templates, no first-pilot flow)
3. `--starter`: installs v0.2.0 starter-kit (templates + first-pilot flow)
4. Install mode persistence: record choice in VERSION file or separate marker
5. Upgrade path: v0.1 installs default to `--minimal`, prompt about starter layer
6. Tests for install modes, persistence, and upgrade prompt
7. Documentation for install modes and upgrade path

This slice cuts through setup flags, install modes, and upgrade behavior.

**Acceptance criteria:**
- [ ] `setup` accepts `--minimal` or `--starter` flag
- [ ] `--minimal` installs v0.1-equivalent (no starter-kit)
- [ ] `--starter` installs templates and first-pilot flow
- [ ] Install mode is persisted and detectable
- [ ] v0.1 upgrades prompt about starter layer
- [ ] Tests cover install modes, persistence, and upgrade prompt
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T06 (first-pilot flow)

---

## Ticket T08: Doctor extension for lane-binding and starter-kit

**User stories covered:** 8, 21, 22

**What to build:**
Extensions to the `doctor` command to validate v0.2.0 features. This includes:
1. Validate lane-binding file: existence, schema validity, referenced profile existence
2. Report active AOS role bindings and unbound roles
3. Verify starter-kit asset resolution when `--starter` installed
4. Report install mode (minimal vs starter)
5. Flag missing or malformed starter-kit assets
6. Integration with existing doctor checks (version, plugin, skills)
7. Tests for new doctor checks and integration

This slice cuts through doctor extension and verification.

**Acceptance criteria:**
- [ ] Doctor validates lane-binding file existence and schema
- [ ] Doctor reports active bindings and unbound roles
- [ ] Doctor verifies starter-kit asset resolution in `--starter` mode
- [ ] Doctor reports install mode
- [ ] Doctor flags missing or malformed starter-kit assets
- [ ] Tests cover new doctor checks and integration
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T07 (install modes)

---

## Ticket T09: Version bump and CHANGELOG

**User stories covered:** 17, 19, 20

**What to build:**
Version bump, CHANGELOG update, and release preparation. This includes:
1. Update VERSION file from 0.1.0 to 0.2.0
2. Update CHANGELOG.md with v0.2.0 release notes
3. Document adapter deferral to v0.3.0 in CHANGELOG
4. Document upgrade path from v0.1 to v0.2
5. Document split release rationale
6. Update any version references in docs or code
7. Verify all version strings are consistent

This slice cuts through versioning and documentation.

**Acceptance criteria:**
- [ ] VERSION file updated to 0.2.0
- [ ] CHANGELOG documents v0.2.0 features and adapter deferral
- [ ] Upgrade path documented
- [ ] Split release rationale documented
- [ ] All version references consistent
- [ ] All existing behavior preserved (regression harness passes)

**Blocked by:** T08 (doctor extension)

---

## Ticket T10: Release preparation and verification

**User stories covered:** 17, 19, 20

**What to build:**
Final release preparation and verification. This includes:
1. Run full test suite (including regression harness) and fix failures
2. Manual verification: run `setup --starter`, `map-lanes`, `doctor` in fresh environment
3. Verify v0.1 upgrade path: upgrade v0.1 install to v0.2, check behavior
4. Verify minimal mode: run `setup --minimal`, confirm no starter-kit artifacts
5. Verify starter mode: run `setup --starter`, confirm templates and first-pilot flow work
6. Check all user stories from BUILD-SPEC-v0.2.md are satisfied
7. Tag v0.2.0 release

This slice cuts through final verification and release.

**Acceptance criteria:**
- [ ] Full test suite passes (including regression harness)
- [ ] Fresh environment manual verification passes
- [ ] v0.1 upgrade path verified
- [ ] Minimal mode verified (no starter-kit artifacts)
- [ ] Starter mode verified (templates and first-pilot flow work)
- [ ] All BUILD-SPEC-v0.2.md user stories satisfied
- [ ] v0.2.0 tag created

**Blocked by:** T09 (version bump and CHANGELOG)

---

## Dependency graph

```
T00 (regression harness)
└── T01 (wizard command structure)
    └── T02 (binding file schema)
        └── T03 (wizard interactive flow)
            └── T04 (wizard persistence)
                └── T05 (profile templates)
                    └── T06 (first-pilot flow)
                        └── T07 (install modes)
                            └── T08 (doctor extension)
                                └── T09 (version bump)
                                    └── T10 (release)
```

**Parallel work opportunity:** The adapter prototype (dispatch adapters) runs in parallel during T01-T10. It is not part of the v0.2.0 critical path but must produce evidence for v0.3.0 interface derivation.

---

## Open questions

- **Adapter prototype scheduling:** Should the adapter prototype have its own ticket numbering (P01, P02, ...) or run as a separate workstream? This is an open question and should be decided by the user before v0.3.0 planning begins.
- **Kanban seeds design:** Deferred to v0.3.0, but should the board structure be prototyped during v0.2.0 adapter work? This is an open question for v0.3.0 planning.
- **Starter-kit expansion:** Future major versions may expand the starter-kit (e.g., example calibration data, sample lanes). The additive-superset constraint requires these to be major-version breaks if they require method body changes. This is a policy decision, not a v0.2.0 question.