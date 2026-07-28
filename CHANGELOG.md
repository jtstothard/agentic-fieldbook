# Changelog

All notable changes to Agentic Fieldbook are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-07-28

### Added

- `aos preflight --profile <name>` validates Fieldbook skills are installed on a target profile before dispatching kanban cards with forced skills (#31)
- `aos contract --workspace <path>` discovers the correct test-runner command for a workspace, detecting venv-in-worktree, venv-in-parent (git worktree common dir), uv, tox, and pyproject (#33)
- Profile scoping and worktree environment guidance in SETUP.md

### Changed

- `aos setup` is now profile-aware: gateway restart guidance only appears when the target profile actually has a gateway configured, preventing env-var bleed false positives on non-gateway profiles (#32)

### Testing

- 152 tests (35 new across preflight, profile-aware gateway detection, and contract runner discovery)
- CI on Python 3.11 and 3.13

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
