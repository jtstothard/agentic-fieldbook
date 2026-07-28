# 05 — Profile templates (starter-kit leg 1)

**What to build:** Opinionated profile templates for the four canonical AOS roles (planner, executor, reviewer, verifier), shipped as part of the `--starter` layer. Templates are model-agnostic and contain no estate identifiers. Consumable by the `map-lanes` wizard's "build-from-template" path (ticket 02).

**Blocked by:** 02 (map-lanes wizard) — templates are consumed by the wizard's build-from-template path; the consumption contract must exist before templates are shaped against it.

**Status:** ready-for-agent

- [ ] Four profile templates exist: planner, executor, reviewer, verifier
- [ ] Each template is model-agnostic (no hardcoded model/provider assumptions)
- [ ] Each template contains zero estate identifiers (synthetic only, per v0.1 anonymization rule)
- [ ] Templates consumable by `map-lanes` wizard's build-from-template path (the wizard can apply a template to create a real profile)
- [ ] `doctor` verifies template assets resolve when `--starter` is installed
