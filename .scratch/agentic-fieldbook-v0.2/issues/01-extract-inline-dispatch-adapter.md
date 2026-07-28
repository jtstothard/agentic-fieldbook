# 01 — Extract inline-default dispatch behind a swappable boundary

**What to build:** Refactor v0.1's existing inline delegation (delegate_task / terminal spawn) into a named adapter behind a swappable boundary, so dispatch mechanism is a component rather than an inline assumption. This is a mechanical extraction — it does not change dispatch behaviour, it makes it addressable. Establishes the boundary the kanban adapter (ticket 03) builds against.

**Blocked by:** None — can start immediately.

**Status:** complete — commit `9c1bb10`

- [x] Inline dispatch logic refactored behind a named adapter module/boundary (not inlined in routing logic)
- [x] Dispatch parity with v0.1: same inputs produce same dispatch path and same outcomes (parity test passes against v0.1 behaviour)
- [x] `doctor` reports "inline" as the active dispatch backend
- [x] No change to existing v0.1 user-facing dispatch behaviour — a v0.1 user who upgrades experiences identical dispatch
