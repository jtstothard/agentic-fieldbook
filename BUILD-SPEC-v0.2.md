# Agentic Fieldbook v0.2 — Build Specification

**Parent spec:** `BUILD-SPEC.md` (v0.1). This document is additive on top of v0.1; it assumes v0.1 is shipped, released (tag `v0.1.0`), and every v0.1 user story and implementation decision carries forward unchanged unless explicitly superseded here.

## Problem Statement

v0.1 shipped a method bundle with inline-default dispatch only, no lane-mapping wizard, and no opinionated starter layer. An installer who completes v0.1 `setup` is left at a "now what": they have an uncalibrated method bundle with no concrete binding from AOS roles to their own Hermes profiles, no durable dispatch backend beyond ephemeral inline delegation, and no guided path to their first real calibration data point.

v0.2 addresses the profile-mapping and starter-kit gaps in v0.2.0. Dispatch adapters are deferred to v0.3.0 to allow evidence-driven interface derivation from a functional prototype that produces contrast against the inline-default adapter.

## Solution

Ship Agentic Fieldbook v0.2.0 as a single tagged release adding two features as a coherent additive superset on top of the v0.1 method bundle:

1. **First-run profile-mapping wizard:** a separate, re-runnable command that walks the user through binding their Hermes profiles to AOS roles (map-existing / build-from-template / skip per role), persisting the result in a generated, human-readable config file.

2. **Starter-kit layer:** an install-time choice (`--minimal` vs `--starter`) adding profile templates and a guided first-pilot flow as an opinionated bootstrapping layer — strictly additive, never forking the method body.

Dispatch adapters are explicitly **deferred to v0.3.0**. v0.2.0 runs a parallel adapter prototype that reads live home-ops data but writes to a seeded shadow board, producing evidence for interface derivation without exposing experimental features to production.

The release preserves every v0.1 constraint: single coupled version, synthetic identifiers in examples, schema-enforced `uncalibrated` defaults, additive-superset boundary, and the plugin command surface as the primary test seam.

## User Stories

### First-run profile-mapping wizard

1. As a new installer, I want a separate command to bind my profiles to AOS roles, so that I can re-map lanes over time without re-running setup.
2. As a user running setup, I want setup to point me to the lane-mapping command as the next step, so that the first-run flow is discoverable without being forced.
3. As a user, I want the wizard to offer map-existing, build-from-template, or skip per role, so that I can adapt the method to profiles I already have or create new ones.
4. As a user, I want one profile to be bindable to multiple AOS roles, so that I am not forced to create redundant profiles for small estates.
5. As a user, I want a skipped role to degrade gracefully, so that the method continues to function with unbound roles rather than failing.
6. As a user, I want my role bindings persisted to a generated, human-readable config file, so that I can inspect the current binding without re-running the wizard.
7. As a user, I want the wizard to read the existing binding file on load and preserve unchanged roles when I re-map one, so that re-running for a single role does not clobber my other bindings.
8. As a user, I want the binding file validated by doctor, so that a malformed or stale binding surfaces in verification.
9. As a maintainer, I want the binding file wizard-owned and explicitly not hand-maintained, so that the wizard remains the canonical editor and direct edits are a documented "you own it now" boundary.

### Starter-kit layer

10. As a new installer, I want an install-time choice between `--minimal` and `--starter`, so that I can opt into the opinionated layer only if I want it.
11. As a user choosing `--starter`, I want profile templates provided for the canonical AOS roles, so that I can bootstrap new profiles without authoring them from scratch.
12. As a user choosing `--starter`, I want a guided first-pilot flow, so that I can reach my first real calibration data point from the operating method rather than improvising.
13. As a user choosing `--minimal`, I want the starter-kit layer to not affect my install in any way, so that the minimal install is unchanged from v0.1 behaviour.
14. As a maintainer, I want the starter-kit to remain a strict additive superset, so that it never forks or modifies the method body.
15. As a maintainer, I want the additive-superset constraint enforced across versions, so that a future starter-kit change that requires modifying the method becomes a major-version break, not a starter option.
16. As a user, I want the guided first-pilot flow to use real low-risk tasks (not synthetic pilots), so that my first calibration data point comes from genuine work.

### Upgrade and versioning

17. As a v0.1 user, I want a documented upgrade path from v0.1 to v0.2, so that upgrading does not surprise me with undocumented migrations.
18. As a v0.1 user who installed `--minimal`-equivalent (the v0.1-only shape), I want a v0.2 upgrade to prompt me about the starter layer per the v0.1 ticket-03 deferred behaviour, so that the install-time choice becomes real on upgrade.
19. As a maintainer, I want a single coupled version bump (v0.1.0 → v0.2.0) covering plugin, skills, wizard, starter-kit, and docs, so that the bundle remains one unit.
20. As a maintainer, I want the adapter deferral to v0.3.0 recorded in the CHANGELOG and docs, so that the absence of dispatch adapters in v0.2 is a deliberate decision, not an oversight.

### Doctor and verification

21. As a user, I want doctor to validate the lane-binding config file, so that a broken or missing binding is reported alongside other checks.
22. As a user, I want doctor to verify starter-kit assets (templates, seeds) resolve when `--starter` is installed, so that a broken starter install is caught by verification.

### Dispatch adapter prototype (v0.3.0 pre-work)

23. As a maintainer, I want a parallel adapter prototype running during v0.2.0 development, so that evidence for interface derivation is ready when v0.3.0 work begins.
24. As a maintainer, I want the adapter prototype to read live home-ops data but write to a seeded shadow board, so that real traffic patterns inform the interface without risking production disruption.
25. As a maintainer, I want the adapter prototype to pass a high evidence bar including stale-blocker recovery and synthetic concurrent-claim tests, so that the interface derived from it is robust against edge cases.
26. As a maintainer, I want the adapter interface derived only from two functional adapters (inline-default + kanban), so that the contract reflects real behavior rather than premature speculation.

## Implementation Decisions

### First-run profile-mapping wizard

- The wizard is a separate command (`hermes aos map-lanes`), not a phase folded into `setup`. `setup` remains idempotent and activation-focused; on completion it prints a pointer to `map-lanes` as the next step.
- The wizard offers three paths per AOS role (planner, executor, reviewer, verifier): (a) map an existing Hermes profile, (b) build a new profile from a starter-kit template, (c) skip (role unbound).
- Crossover is allowed: one profile may serve multiple AOS roles.
- A skipped role degrades gracefully. The method functions with unbound roles; doctor reports unbound roles as a state, not a failure.
- Persistence is a generated, human-readable config file (canonical path: `~/.hermes/aos-lanes.yaml`). The wizard owns the file: it reads on load, regenerates on save, and preserves unchanged roles when re-running for a single role.
- Direct user edits to the binding file are a documented "you own it now" boundary — the wizard does not clobber, but a hand edit is the user's responsibility and is not protected against.
- `doctor` validates the binding file: schema validity, role coverage, referenced-profile existence.

### Starter-kit layer

- The install-time choice is `--minimal` (v0.1-equivalent) vs `--starter` (additive superset). v0.1 installs upgrade to `--minimal`-equivalent by default; the starter layer is offered via the v0.1 ticket-03 upgrade-prompt behaviour.
- The starter-kit has two legs in v0.2.0, both strictly additive on top of the method bundle:
  1. **Profile templates** — opinionated scaffolding for the canonical AOS roles, consumable by the `map-lanes` wizard's "build from template" path.
  2. **Guided first-pilot flow** — a calibration bootstrapper that walks the user to their first real calibration data point using a real low-risk task, not a synthetic pilot (honouring ticket 04's rejection of synthetic pilots as calibration evidence).
- The third leg — kanban board seeds — is deferred to v0.3.0 with the dispatch adapter feature, since kanban seeds are only useful when kanban dispatch is available.
- The additive-superset constraint is version-invariant: if a future starter-kit change requires modifying the method body, that is a major-version break, not a starter option. This is documented and enforced by review.
- The starter-kit is bypassed cleanly by `--minimal`: no templates, no guided flow, no behavioural difference from v0.1.

### Upgrade and versioning

- Single coupled version bump: `0.1.0` → `0.2.0` via git tag + VERSION file, consistent with v0.1's co-versioning decision.
- The wizard and starter-kit legs carry no independent version — they are components of the coupled bundle, consistent with v0.1 skill versioning.
- The adapter deferral to v0.3.0 is recorded explicitly in CHANGELOG.md and docs/ as a deliberate v0.2 boundary, not an omission.
- The v0.1 → v0.2 upgrade path is documented: `hermes plugins update`, version-gap detection (v0.1's existing mechanism), and the starter-layer prompt for minimal-equivalent upgraders.

### Plugin command surface

- v0.1's `hermes aos setup` and `hermes aos doctor` carry forward. `setup` gains a pointer to the new `map-lanes` command.
- v0.2 adds `hermes aos map-lanes` (the wizard).
- `doctor` is extended: it validates the lane-binding file and verifies starter-kit asset resolution when `--starter` is installed.

### Dispatch adapter prototype (v0.3.0 pre-work)

- **Scope:** A parallel prototype running during v0.2.0 development, producing evidence for v0.3.0 interface derivation. Not shipped in v0.2.0.
- **Isolation:** Reads live home-ops data (real traffic patterns, claim behavior, failure modes) but writes to a seeded shadow board, not production. This captures real-world behavior without risking production disruption.
- **Implementation:** A functional Hermes kanban adapter covering every operation the AOS routing lifecycle requires (create task, claim, dispatch, poll completion, read result, handle failure).
- **High evidence bar:** Must pass (a) stale-blocker recovery tests, (b) synthetic concurrent-claim tests, (c) end-to-end lifecycle operations before the interface can be derived from it. If any evidence gap remains, the prototype continues until satisfied.
- **Interface derivation:** The adapter interface contract is derived only from contrast evidence between the extracted inline-default adapter and the functional kanban adapter. No forward-spec is permitted. The interface is specified in v0.3.0, not v0.2.0.

### TDD and regression

- **Ticket zero (v0.1 regression harness):** The first ticket builds an automated regression harness proving additive-superset behavior before any feature work begins. This runs against v0.1.0 to establish a baseline, then is used to verify every subsequent commit preserves v0.1 behavior.
- **TDD from commit one:** All feature work uses red-green TDD. No feature code is written without a failing test first. The regression harness runs on every commit.
- **Additive-superset proof:** The regression harness, not inspection, proves that v0.2.0 is a strict additive superset of v0.1.0. If any regression is detected, the change fails and is revised.

## Testing Decisions

Two seams, each testing external behaviour, not implementation details:

1. **Plugin command seam (existing, extended).** v0.1 tests plugin behaviour through `setup` and `doctor` using Hermes-like fixtures. v0.2 extends this to `map-lanes` (wizard flow, persistence, doctor integration). This remains the highest seam for plugin-facing behaviour. No new seam is created for plugin behaviour.

2. **v0.1 regression harness (new, runs first).** An automated harness that captures v0.1.0's external behaviour and proves that every subsequent v0.2.0 commit preserves it as a strict additive superset. The harness runs on every commit; any regression blocks the change. This implements the TDD requirement and the "prove additive-superset by automation, not inspection" decision.

**Dispatch adapter testing (v0.3.0 scope):** The kanban adapter prototype is tested against a shadow board with the high evidence bar tests (stale-blocker recovery, synthetic concurrent-claim, full lifecycle). These tests inform v0.3.0 interface derivation but are not part of v0.2.0's test suite.

## Out of Scope

- **Dispatch adapters (deferred to v0.3.0).** Inline-default extraction and kanban adapter are built as part of the v0.3.0 interface derivation effort. v0.2.0 ships only the prototype evidence; no dispatch backend switching is exposed to users.
- A stable dispatch adapter interface contract (wayfinder holdout, derived in v0.3.0 from inline + kanban contrast evidence).
- A production-hardened kanban adapter (v0.3.0 ships the stable contract; hardening is a follow-up cycle driven by real usage evidence).
- A third dispatch adapter beyond inline-default and kanban (two real, categorically distinct shapes are sufficient contrast for interface derivation).
- Kanban board seeds (deferred to v0.3.0, only useful when kanban dispatch is available).
- Forcing the starter-kit on `--minimal` installs.
- Modifying the v0.1 method body to accommodate the starter-kit (additive-superset constraint is inviolable; any such need is a future major-version break).
- Medium- or high-risk calibration expansion (carries forward from v0.1).
- Upstreaming into Hermes core (carries forward).
- Non-Hermes agent framework support (carries forward).
- A GUI/dashboard (carries forward).
- Independent versioning of wizard or starter-kit legs.

## Further Notes

- **Split release rationale:** Deferring dispatch adapters to v0.3.0 allows v0.2.0 to ship the profile-mapping and starter-kit features while the adapter prototype produces evidence for interface derivation. This avoids shipping an experimental contract or a rushed interface.
- **Prototype isolation:** Reading live home-ops but writing to a shadow board captures real-world behavior patterns (claim races, dispatcher anomalies, worktree requirements) without production risk. The high evidence bar (stale-blocker recovery, concurrent-claim tests) ensures the interface derived from this prototype is robust.
- **TDD and regression:** Ticket zero establishes the baseline; every subsequent commit proves it doesn't break v0.1.0. This implements the "automated regression, not inspection" requirement.
- **Interface derivation discipline:** The adapter interface is derived from two functional adapters, not specified forward. This prevents the premature-spec anti-pattern identified in the v0.1 wayfinder.
- **Build sequencing:** Ticket zero (regression harness) → profile-mapping wizard → starter-kit layer → upgrade/version work → release. The adapter prototype runs in parallel and unblocks v0.3.0 work after v0.2.0 ships.