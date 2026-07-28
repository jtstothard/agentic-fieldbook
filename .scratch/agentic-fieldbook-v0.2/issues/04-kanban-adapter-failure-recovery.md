# 04 — Kanban adapter: failure/recovery handling + documented rough edges

**What to build:** Harden the experimental kanban adapter's failure surface: exercise the documented failure modes (claim races, dispatcher anomalies, worktree requirements) and recovery paths, and make every known rough edge explicit and reported — never hidden behind silent behaviour. This does not make the adapter production-complete; it makes its experimental boundary honest.

**Blocked by:** 03 (Kanban adapter: happy-path tracer bullet) — failure handling builds on the working happy-path adapter.

**Status:** ready-for-agent

- [ ] Claim race condition handled (detected and reported, not silently lost)
- [ ] Dispatcher anomaly (spawn-zero, timeout) reported explicitly with the recovery action taken
- [ ] Worktree requirement surfaced when a board lacks a default worktree (v0.1 AOS skill documents this exact failure)
- [ ] Every known rough edge documented in a "Known rough edges" section alongside the adapter, not buried in code comments
- [ ] `doctor` output points at the known-rough-edges reference when kanban is enabled
- [ ] No silent failure paths — every failure produces a named report
