# 06 — Kanban seeds (starter-kit leg 2)

**What to build:** A board template matching the AOS method's expectations, shipped as part of the `--starter` layer. Consumable when a user enables kanban dispatch — applies a board shape the method works against without manual board design.

**Blocked by:** 03 (Kanban adapter: happy-path tracer bullet) — seeds must match the board shape the kanban adapter actually operates against; the adapter defines the contract the seeds encode.

**Status:** ready-for-agent

- [ ] Board template exists and matches the kanban adapter's expected board shape
- [ ] Template applies to a real kanban board (not just a spec — it provisions columns/labels the method expects)
- [ ] `doctor` verifies kanban seed assets resolve when `--starter` is installed
- [ ] Seeds contain no estate identifiers (synthetic board/column names only)
