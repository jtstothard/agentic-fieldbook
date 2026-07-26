# Agentic Fieldbook v0.1 — Build Specification

## Problem Statement

People can run autonomous AI agents, but the surrounding operating discipline is usually implicit, instance-specific, or scattered across ad hoc prompts and scripts. New Hermes users need a portable way to plan, route, calibrate, review, verify, and hand off agent work without importing one operator's private models, hosts, lane names, or task history.

## Solution

Build Agentic Fieldbook v0.1: an installable, generic, versioned Hermes skill bundle containing eight skills, one userland plugin, and supporting documentation. It provides an opinionated operating methodology for autonomous agents while remaining model-agnostic and honest about trust: new lanes start uncalibrated and are restricted to discovery and low-risk pilots until empirical calibration exists.

The plugin owns installation and activation. The bundle is distributed from a standalone public repository and uses one coupled version for its plugin, skills, schemas, documentation, and migrations.

## User Stories

1. As a Hermes user, I want to install Agentic Fieldbook through one documented entry point, so that I do not have to coordinate separate skill and plugin installation steps.
2. As a Hermes user, I want setup to check prerequisites before modifying anything, so that incompatible environments fail clearly.
3. As a Hermes user, I want setup to fail fast when Hermes is unavailable or the skills toolset is disabled, so that fatal prerequisites are not hidden behind partial installation.
4. As a Hermes user, I want non-fatal prerequisite problems warned and recorded, so that I can decide whether to continue and diagnose them later.
5. As a Hermes user, I want setup to ask consent before changing my SOUL.md, so that the bundle does not silently change my operating instructions.
6. As a Hermes user, I want SOUL.md changes to be inserted between stable markers, so that setup is idempotent and updates can locate only the managed block.
7. As a Hermes user, I want setup to run doctor automatically after activation, so that I receive immediate evidence of whether installation worked.
8. As a Hermes user, I want doctor to be rerunnable, so that I can verify the installation after changes or upgrades.
9. As a Hermes user, I want doctor to load all eight skills, so that missing or malformed skills are caught before use.
10. As a Hermes user, I want doctor to verify referenced supporting files resolve, so that broken links and missing calibration assets are reported by name.
11. As a Hermes user, I want doctor to validate the bundle's YAML schemas, so that malformed calibration data is detected early.
12. As a Hermes user, I want doctor to check cross-skill names and CLI registration, so that internal contract drift becomes a named failure.
13. As a planner, I want a roles-first contract layer, so that the method maps to different Hermes profiles and model providers.
14. As an operator, I want guidance to distinguish portable roles from optional profile templates, so that I can adapt the method without copying Jay's estate.
15. As a user of a different model family, I want the guidance to avoid assuming GLM behaviour, so that the method remains honest across Claude, GPT, local, and other models.
16. As a reader, I want model-specific results labelled as worked examples, so that examples are not mistaken for universal baselines.
17. As a user, I want to classify task risk before execution, so that low-confidence or high-impact work is not treated like routine work.
18. As a user, I want uncalibrated lanes to be structurally marked uncalibrated, so that a new installation cannot accidentally present them as trusted.
19. As a user, I want uncalibrated lanes restricted to discovery and low-risk pilots, so that the trust boundary is explicit.
20. As a user, I want calibration guidance to teach an empirical method, so that I can calibrate the models and tools I actually use.
21. As a user, I want a blank calibration template, so that I can record my first real pilot without reconstructing the schema.
22. As a user, I want a synthetic worked example, so that I can understand what a populated record looks like without importing private instance data.
23. As a user, I want the worked example to use fabricated identifiers and clearly say it is not my lane data, so that the public bundle does not overclaim portability.
24. As a user, I want model, provider, quantization, tool, permission, prompt, and staleness changes to trigger recalibration guidance, so that stale evidence does not silently retain trust.
25. As a user, I want fallbacks represented as separate lane IDs with their own calibration records, so that a fallback model is not mistaken for a calibrated inline swap.
26. As a reviewer, I want a documented review protocol with explicit independence rules, so that review evidence is meaningful.
27. As a reviewer, I want severity classification grounded in a shared rubric, so that critical, major, and minor findings are classified consistently.
28. As a reviewer, I want evidence requirements for findings, so that review output can be independently verified.
29. As a user, I want stage handoffs to preserve the contract, evidence, and unresolved risks, so that work remains resumable across sessions and agents.
30. As a user, I want the bundle to use inline-default dispatch in v0.1, so that the initial release does not pretend to support adapters that have not yet been proven.
31. As a maintainer, I want a single bundle version represented by a tag and VERSION file, so that plugin, skills, schemas, and docs evolve as one unit.
32. As a maintainer, I want skills to avoid independent version claims, so that component versions cannot drift from the bundle contract.
33. As a maintainer, I want plugin metadata to declare its tested Hermes compatibility range, so that unsupported environments are rejected explicitly.
34. As a user, I want setup to hard-fail below the supported Hermes floor, so that incompatible installation does not produce a misleading partial state.
35. As a maintainer, I want a no-op migration command in v0.1, so that the migration contract is exercised before a real breaking migration is needed.
36. As a user, I want update prompts with apply, skip-this-version, and remind-later choices, so that updates are controlled without repeated nagging.
37. As a user, I want update choices persisted per bundle version, so that a skipped version does not prompt repeatedly.
38. As a maintainer, I want runtime doctor checks and repository pytest tests, so that installation failures and regressions are caught at two different seams.
39. As a maintainer, I want private instance data excluded from the public repository, so that the bundle is generic and safe to publish.
40. As a contributor, I want clear security, contribution, conduct, and licensing documents, so that the public project has a usable maintenance boundary.

## Implementation Decisions

- The project is named Agentic Fieldbook, with the descriptor: “An operating methodology for autonomous agents.”
- v0.1 is a standalone public repository containing eight genericized skills, one userland plugin, and documentation.
- The plugin is installed through the Hermes plugin mechanism and owns the coupled bootstrap lifecycle: add the skills tap, install the eight skills, and expose the Agentic Fieldbook commands.
- The plugin registers `hermes aos setup` and `hermes aos doctor` in v0.1. The command namespace remains an implementation compatibility decision to validate against Hermes plugin conventions during build; user-facing naming is Agentic Fieldbook.
- Setup is interactive, consent-gated, idempotent, and marker-based for SOUL.md changes. It runs doctor after successful setup.
- Doctor is the primary runtime verification seam. It checks skill loading, reference resolution, YAML schema validity, cross-skill names, and CLI registration.
- The portable contract layer is roles-first: planner, executor, reviewer, and verifier. Profile templates remain optional and model/provider agnostic.
- v0.1 uses inline-default dispatch. A stable dispatch adapter interface is deferred until at least two real adapters exist in a later release.
- Calibration documentation ships a portable schema, a blank uncalibrated template, a small synthetic worked example, and recalibration triggers. It does not ship a turnkey first-pilot task or guided calibration wizard.
- New lanes begin with `calibration_status: uncalibrated` and no trusted risk class. Uncalibrated lanes are limited to discovery and low-risk pilots.
- Calibration is empirical per model and configuration. Model/provider/quantization/tool/permission/prompt changes and staleness require trust downgrade and recalibration.
- Fallbacks refer to separate lane records, not an inline model swap on one calibrated record.
- All instance data is synthetic or removed: no real task IDs, hostnames, IPs, provider credentials, private lane names, or private operational history.
- Bundle versioning uses a git tag and VERSION file. The plugin metadata carries the version; component skills do not claim independent versions.
- Plugin metadata declares a tested-against Hermes compatibility range. Setup rejects versions below the supported floor.
- `CHANGELOG.md` follows Keep-a-Changelog conventions. `hermes aos migrate` exists as a no-op in v0.1.
- Update handling is custom plugin logic because Hermes has no native plugin-update lifecycle hook. It offers apply, skip-this-version, and remind-later, persisting decisions per version.
- v0.1 includes MIT licensing and the agreed public-repository baseline: funding, security, code of conduct, contributing guidance, issue templates, README, SETUP, and acknowledgements.

## Testing Decisions

- Test the highest external seam: plugin command behaviour through `setup` and `doctor` using temporary Hermes-like fixtures.
- Tests must verify externally observable outcomes, not private helper implementation details.
- Setup tests cover prerequisite failure modes, consent, idempotent marker insertion, and automatic doctor invocation.
- Doctor tests cover skill loading, reference resolution, schema validation, cross-skill consistency, CLI registration, compatibility failures, and named error reporting.
- Calibration tests cover valid blank/worked-example structures, required uncalibrated defaults, fallback lane references, and recalibration-trigger semantics.
- Migration tests verify the v0.1 no-op contract and stable command behaviour.
- Update tests verify version-gap detection and persistence of apply, skip, and remind-later choices.
- Repository CI runs the plugin's pytest suite. Doctor remains the user-facing runtime check.
- Human-judgment properties — calibration quality, risk accuracy, and review quality — are documented invariants, not falsely reduced to automated pass/fail tests in v0.1.

## Out of Scope

- Upstreaming Agentic Fieldbook into Hermes core.
- Supporting non-Hermes agent frameworks in v0.1.
- Building a new agent runtime, orchestration engine, GUI, or dashboard.
- Medium- or high-risk calibration before publication.
- A profile-mapping wizard.
- A turnkey synthetic first-pilot task.
- A dispatch adapter interface or non-inline backend implementation.
- Templates and kanban seeds beyond the calibration artifacts explicitly listed above.
- Independent skill versioning.
- Importing or relabelling Jay's real calibration records.

## Further Notes

- The full planning record is in the local wayfinder and resolved decision tickets; this issue is the build-facing synthesis.
- The public bundle must use the Agentic Fieldbook name in documentation and repository branding while preserving any Hermes command compatibility required by the plugin API.
- Naming research is preliminary and not trademark or legal clearance.
- Build work should proceed in bounded implementation tasks with review of the plugin seam and genericization quality before release.
