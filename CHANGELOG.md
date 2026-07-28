# Changelog

All notable changes to Agentic Fieldbook are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-07-28

### Added

- Profile-mapping wizard (`hermes aos map-lanes`) for binding Hermes profiles to AOS roles
- Lane-binding config schema and persistence via `~/.hermes/aos-lanes.yaml`
- Wizard file ownership semantics with atomic writes and structural drift detection
- Profile template system for canonical AOS roles (planner, executor, reviewer, verifier)
- Guided first-pilot flow for initial calibration data capture (`hermes aos first-pilot`)
- Install-time choice between `--minimal` (v0.1-equivalent) and `--starter` (full starter-kit) modes
- Doctor extensions for lane-binding validation and starter-kit asset verification
- Install mode persistence and detection for upgrade path support

### Changed

- `hermes aos setup` now supports `--minimal` and `--starter` flags
- `hermes aos setup` prints pointer to `map-lanes` command on completion
- Doctor command validates lane-binding file existence and schema
- Doctor reports active AOS role bindings and unbound roles
- Doctor verifies starter-kit asset resolution when in starter mode
- Doctor reports active install mode (minimal vs starter)

### Deprecated

- None

### Removed

- None

### Fixed

- None

### Security

- None

### Deferred to v0.3.0

- **Dispatch adapters**: The adapter interface for canonical method delegation is deferred to v0.3.0. The v0.2.0 release focuses on the profile-mapping wizard and starter-kit foundation. Evidence from the v0.3.0 adapter prototype will inform the final adapter interface design.

### Upgrade Path (v0.1 → v0.2.0)

Upgrading from v0.1.0 to v0.2.0 is straightforward:

1. **Update the bundle**:
   ```bash
   hermes plugins update
   ```
   This uses v0.1's existing version-gap detection and update mechanism.

2. **Run setup**:
   ```bash
   hermes aos setup
   ```
   v0.1 installations default to `--minimal` mode (v0.1-equivalent). The setup command detects v0.1 installations and prompts:
   - Installs in minimal mode by default (no starter-kit artifacts)
   - Offers to upgrade to starter mode: `hermes aos setup --starter`

3. **Optional: Add starter-kit**:
   ```bash
   hermes aos setup --starter
   ```
   This installs profile templates and the first-pilot flow.

4. **Bind profiles to AOS roles**:
   ```bash
   hermes aos map-lanes
   ```
   The interactive wizard guides you through mapping existing profiles or creating new ones from templates.

5. **Verify installation**:
   ```bash
   hermes aos doctor
   ```
   Doctor now validates lane-binding file, reports active bindings, and checks starter-kit assets.

**Compatibility notes**:
- All v0.1 commands remain functional
- v0.1 skills are preserved unchanged (additive-superset constraint)
- No breaking changes to existing v0.1 behavior
- Starter-kit is opt-in via `--starter` flag

### Split Release Rationale

The v0.2.0 release is split into two layers:

1. **Foundation layer (this release)**: Profile-mapping wizard, lane-binding persistence, and starter-kit templates. This provides the infrastructure for role-based lane configuration and guided onboarding.

2. **Adapter layer (v0.3.0)**: Dispatch adapters for canonical method delegation between lanes. This is deferred because:
   - The adapter interface design requires evidence from a working prototype
   - The prototype runs in parallel during v0.2.0 development
   - The final adapter contract will be informed by real-world usage patterns discovered through the prototype
   - Keeping the adapter layer separate allows v0.2.0 to ship faster while the adapter work matures

This split release strategy ensures that:
- Users get value immediately from the wizard and starter-kit
- The adapter interface is well-designed based on evidence, not speculation
- The additive-superset constraint is maintained across releases
- Each release has a clear, focused scope

### Testing

- 351 tests passing (all existing v0.1 and v0.2 tests)
- CI on Python 3.11 and 3.13
- Regression harness validates v0.1 behavior preservation

## [0.1.1] - 2026-07-27

### Added

- Cross-repo investigation methodology in planning-routing skill (#21)
- Domain-extension selection guidance in contract-schema skill (#22)
- Evidence-via-CI escape hatch for polyglot estates in contract-schema skill (#24)
- First-pilot onboarding guidance in lane-calibration skill (#23)
- Solo-maintainer review pattern (admin-merge checklist) in review-calibration skill (#25)

### Changed

- Setup now detects gateway presence before showing the restart instruction (#20)

## [0.1.0] - 2026-07-27

### Added

- Initial versioned Agentic Fieldbook Hermes plugin bundle.
- `hermes aos setup`, `doctor`, `version`, and clean no-op `migrate` commands.
- Seven generic workflow skills and supporting calibration/schema documentation.