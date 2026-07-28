# Kanban adapter prototype evidence

This prototype is intentionally experimental and delegates to the installed Hermes
Kanban CLI. It does not introduce a second board backend or a stable adapter
contract.

## Isolation

Tests construct a temporary `HERMES_HOME` and a `shadow` board. The adapter also
removes ambient `HERMES_KANBAN_DB` and `HERMES_KANBAN_HOME` overrides before
invoking Hermes, preventing accidental writes to the live board. No production
board was written by the test suite.

## Lifecycle evidence

`tests/test_kanban_adapter.py::test_full_lifecycle_create_claim_poll_read`
exercises create, atomic claim, completion, poll, and result read against a real
SQLite board. The test passed.

## Edge evidence

- Concurrent claims: two threads race on the same ready task; exactly one
  reaches `running`, and the loser receives a named adapter error. Hermes uses
  SQLite WAL plus compare-and-swap claim semantics.
- Stale claim: a one-second claim expires and a real dispatcher dry-run reports
  a reclaim. The CLI reports this as a count, not a task-id list.
- Dispatcher anomaly: unassigned and non-spawnable tasks are surfaced in an
  explicit `anomalies` list in the adapter report; they are not silently treated
  as dispatched.
- Failure: `handle_failure` records a transient block with the supplied reason,
  leaving the task auditable and in `blocked` state for recovery.
- Worktree requirement: invalid worktree branch input is rejected before board
  mutation. Valid worktree creation remains dependent on the configured Hermes
  board/default workdir and git repository shape; no production worktree was
  created by this prototype.

## Known rough edges

1. Dispatch currently exposes Hermes' aggregate `reclaimed` count rather than
   the reclaimed task IDs. A later contract should preserve the underlying event
   stream if callers need per-task correlation.
2. Dispatcher spawning is only exercised in dry-run/isolation tests here;
   actually launching a profile worker requires a configured Hermes profile and
   is intentionally not faked by this prototype.
3. Failure handling intentionally blocks with `transient`; retry policy remains
   Hermes dispatcher configuration (`failure_limit` / task retry fields), not a
   second policy in this adapter.
4. The adapter shells out to the installed Hermes CLI, so its behavior is tied
   to the Hermes version on PATH. This is useful contrast evidence, not a stable
   compatibility promise.
