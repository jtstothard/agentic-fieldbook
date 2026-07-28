# 07 — Guided first-pilot flow (starter-kit leg 3)

**What to build:** A calibration bootstrapper that walks a new user to their first real calibration data point using a real low-risk task — not a synthetic pilot (honouring v0.1 ticket 04's rejection of synthetic pilots as calibration evidence). Shipped as part of the `--starter` layer. This is the deferred "guided first-pilot flow" v0.1 ticket 04 explicitly punted to "v0.2 starter-kit."

**Blocked by:** 02 (map-lanes wizard) — the guided flow needs at least one bound executor lane to dispatch the first pilot through, so role binding must exist first.

**Status:** ready-for-agent

- [ ] Guided flow walks the user through selecting a real low-risk task (read-only probe, reversible local coding fixture)
- [ ] Flow dispatches the task through a bound lane (requires at least one role bound via ticket 02)
- [ ] On completion, flow produces a populated calibration record entry (the user's first real data point)
- [ ] The calibration record starts at `calibration_status: uncalibrated` and this flow is the path to promoting it with real evidence
- [ ] Flow excludes production mutation, secrets, access, billing, downtime, release, and GitHub writes (consistent with v0.1 low-risk-only boundary)
- [ ] `doctor` verifies guided-pilot flow assets resolve when `--starter` is installed
