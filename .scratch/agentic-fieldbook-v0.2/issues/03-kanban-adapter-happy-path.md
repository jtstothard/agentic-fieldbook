# 03 — Kanban adapter: happy-path tracer bullet

**What to build:** Build the Hermes kanban dispatch adapter behind the boundary established in ticket 01, covering the happy path: one real task completes end-to-end through kanban dispatch (create → claim → dispatch → poll completion → read result). Labelled `experimental`. This is the adapter that produces the contrast evidence the deferred interface contract is gated on — it must work against a real kanban board, not a mock.

**Blocked by:** 01 (Extract inline-default dispatch behind a swappable boundary) — kanban builds against the boundary this ticket establishes.

**Status:** ready-for-agent

- [ ] Kanban adapter exists behind the swappable dispatch boundary from ticket 01
- [ ] One real task completes the full lifecycle through kanban dispatch: create → claim → dispatch → poll → read result
- [ ] Adapter labelled `experimental` in its metadata and in `doctor` output
- [ ] `doctor` reports "kanban (experimental)" as the active dispatch backend when kanban is enabled
- [ ] `doctor` flags the kanban adapter as experimental, distinct from inline
- [ ] Contract/review/verification lifecycle applies identically through kanban dispatch (the method is backend-independent)
