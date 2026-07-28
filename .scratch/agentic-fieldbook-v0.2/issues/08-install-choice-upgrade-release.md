# 08 — Install-time `--minimal`/`--starter` choice + v0.1→v0.2 upgrade + release

**What to build:** The release slice. Wire the install-time choice between `--minimal` (v0.1-equivalent) and `--starter` (additive superset with all three legs). Document the v0.1 → v0.2 upgrade path. Bump VERSION to 0.2.0, update CHANGELOG (including the deliberate adapter-interface deferral), and tag the release.

**Blocked by:** 01, 02, 03, 04, 05, 06, 07 — this is the integrate-and-release slice; all feature tickets must land first.

**Status:** ready-for-agent

- [ ] `--minimal` flag at install produces no behavioural difference from v0.1 (no templates, no seeds, no guided flow loaded)
- [ ] `--starter` flag at install loads all three starter-kit legs (profile templates, kanban seeds, guided first-pilot flow)
- [ ] v0.1 → v0.2 upgrade path documented: `hermes plugins update`, version-gap detection (existing v0.1 mechanism), starter-layer prompt for minimal-equivalent upgraders
- [ ] Starter-layer upgrade prompt offers apply / skip-this-version / remind-later (consistent with v0.1 ticket 03 update-prompt behaviour)
- [ ] CHANGELOG.md updated for v0.2.0 following Keep-a-Changelog conventions
- [ ] CHANGELOG explicitly records the adapter interface deferral as a deliberate v0.2 boundary (not an omission)
- [ ] VERSION file reads `0.2.0`
- [ ] Git tag `v0.2.0` created
- [ ] `doctor` passes on a clean v0.2.0 install (both `--minimal` and `--starter`)
