# v0.3.0 Adapter Contract

**Status:** Minimal stable contract derived from contrast evidence (16268bb)
**Base ref:** 57b9b17 (inline-default adapter extraction)
**Evidence matrix:** docs/adapter-contrast-matrix.md

## Overview

This contract defines the minimal stable interface for Hermes dispatch adapters. It captures the intersection of behavior supported by both Inline and Kanban adapters while explicitly declaring adapter-specific limitations.

**Design principles:**
- **Intersection first:** Only features supported by all adapters are in the stable contract.
- **Explicit limitations:** Adapter-specific limitations are documented and visible to callers.
- **Evidence-based:** Every operation and field traces to observed contrast evidence.
- **Deterministic failure:** Error behavior is deterministic and observable.

## Core Operations

### dispatch(goal, *, assignee=None, context="", dry_run=False, retry=0, timeout=0, cancellation_token="", idempotency_key="")

**Purpose:** Submit a task for execution and return an immediate result.

**Required parameters:**
- `goal` (str): Task description or goal.

**Optional parameters:**
- `assignee` (str | None): Target Hermes profile. Inline accepts but ignores; Kanban enforces via board routing.
- `context` (str): Additional context for task execution.
- `dry_run` (bool): Preview execution without side effects. Inline records but doesn't enforce; Kanban supports real dry-run.
- `retry` (int): Retry attempts. Both adapters record in metadata but don't enforce (policy is external).
- `timeout` (int): Timeout in seconds. Both adapters record in metadata but don't enforce (policy is external).
- `cancellation_token` (str): Token for cancellation. Both adapters record in metadata but don't enforce.
- `idempotency_key` (str): Key for idempotent requests. Inline records but doesn't enforce; Kanban requires backend enforcement (not implemented in prototype).

**Returns:** DispatchResult
```python
@dataclass
class DispatchResult:
    success: bool              # True if dispatch succeeded
    task_id: str | None        # Persistent ID (Inline: None, Kanban: str)
    metadata: dict[str, Any]   # Backend-specific observability data
    message: str               # Human-readable status
```

**Behavior:**
- **Inline:** Synchronous execution, returns immediately with task_id=None. Results are session-scoped.
- **Kanban:** Returns persistent task_id, async execution via separate claim lifecycle.

**Dry-run semantics:**
- **Inline:** Parameter recorded in metadata but not enforced; no side-effect prevention.
- **Kanban:** Supports real dry-run; dispatch can run without executing tasks, can reclaim stale tasks.

**Evidence:** Scenario `create_dispatch` (9/9 successful), Scenario `dry_run` (9/9 successful).

**Limitations:**
- **Inline:** Cannot prevent duplicate work, no durable result storage, Cannot re-read results after session ends, task_id=None means no re-read after session ends.
- **Kanban:** Requires Kanban backend infrastructure, additional complexity for simple synchronous tasks.

Observed limitation names retained for callers and traceability:
- Inline: Cannot record and requeue failed tasks; Cannot recover from stale claims; No persistent task ID across sessions; No real dry-run enforcement; No task-level idempotency.
- Kanban: Requires Kanban backend infrastructure; Additional complexity for simple synchronous tasks; Claim race complexity requires careful TTL management; Idempotency requires Kanban backend enforcement.

---

### get_status(task_id: str) -> DispatchStatus

**Purpose:** Query the status of a dispatched task.

**Returns:** DispatchStatus
```python
@dataclass
class DispatchStatus:
    success: bool              # True if status query succeeded
    metadata: dict[str, Any]   # Backend-specific status data
    message: str               # Human-readable status
```

**Behavior:**
- **Inline:** Always returns success with status='synchronous'. task_id parameter accepted but ignored (session-scoped).
- **Kanban:** Returns actual task state (ready, running, done, blocked) with rich metadata.

**Evidence:** Scenario `status_check` (9/9 successful).

**Limitations:**
- **Inline:** Cannot track lifecycle states, status queries are trivial.
- **Kanban:** Requires backend for state persistence.

---

## Kanban-Only Operations

These operations are NOT part of the minimal stable contract. They are Kanban-specific and not supported by Inline. Callers MUST use capability checks before invoking.

### create(title, *, assignee=None, workspace="scratch", branch=None) -> dict[str, Any]

**Purpose:** Create a task without dispatching (Kanban only).

**Behavior:**
- Creates a persistent task with unique task_id.
- Returns task metadata including id, status, workspace.

**Limitations:** Inline does not support create-dispatch separation; inline dispatch creates and executes in one operation.

**Evidence:** Scenario `claim_poll` (9/9 successful).

---

### claim(task_id: str, *, ttl: int | None = None) -> dict[str, Any]

**Purpose:** Acquire exclusive ownership of a task for execution (Kanban only).

**Behavior:**
- Atomic claim operation with TTL-based ownership.
- On success: returns task state with status='running'.
- On failure: raises KanbanAdapterError with reason='lost' (concurrent race lost).

**Concurrent claim semantics:**
- Multiple claimants race; one winner gets task, losers receive explicit error.
- KanbanAdapterError is raised with diagnostic message.

**Evidence:** Scenario `concurrent_claim` (9/9 successful), Scenario `claim_poll` (9/9 successful).

**Limitations:** Inline has no claim lifecycle; each dispatch executes independently. Cannot serialize concurrent access.

---

### poll(task_id: str) -> dict[str, Any]

**Purpose:** Query current task state (Kanban only).

**Behavior:**
- Returns full task record with status, metadata, and result if available.

**Evidence:** Scenario `claim_poll` (9/9 successful), Scenario `status_check` (9/9 successful).

**Limitations:** Inline has no polling; results available immediately from dispatch.

---

### read_result(task_id: str) -> str | None

**Purpose:** Read durable result from completed task (Kanban only).

**Behavior:**
- Returns result string if task done, None otherwise.
- Results persist beyond task completion.

**Evidence:** Scenario `result_read` (9/9 successful).

**Limitations:** Inline returns results synchronously from dispatch; no separate result read, results lost on session exit.

---

### dispatch(*, dry_run: bool = False) -> dict[str, Any]

**Purpose:** Run dispatcher against board, claims tasks, and starts workers (Kanban only).

**Note:** This is NOT the same as the contract's `dispatch(goal, ...)` operation. This is the Kanban dispatcher CLI wrapper.

**Behavior:**
- Claims ready tasks, spawns workers.
- dry_run: reports what would happen without executing.
- Returns report with anomalies (unassigned, non_spawnable, reclaimed tasks).

**Evidence:** Scenario `dry_run` (9/9 successful), Scenario `stale_claim_recovery` (9/9 successful).

**Limitations:** Inline has no dispatcher; execution is implicit on each dispatch call.

---

### handle_failure(task_id: str, reason: str) -> dict[str, str]

**Purpose:** Record failure and transition task to blocked state for review (Kanban only).

**Behavior:**
- Blocks task with reason recorded.
- Returns operation confirmation.

**Evidence:** Scenario `handle_failure` (9/9 successful).

**Limitations:** Inline has no explicit failure handling; failures are exceptions or error messages.

---

## Failure Semantics

### Inline Adapter

- **Exception model:** Failures raise exceptions or return error messages.
- **No task requeue:** Failed work cannot be recorded and requeued.
- **No failure state:** Task lifecycle has no 'blocked' state.

### Kanban Adapter

- **Named errors:** KanbanAdapterError raised for claim failures and operation errors.
- **Explicit failure state:** Failed tasks transition to 'blocked' state with reason recorded.
- **Recovery:** Blocked tasks can be unblocked and retried.

**Evidence:** Scenario `handle_failure` (9/9 successful).

---

## Idempotency

### Inline Adapter

- **No enforcement:** idempotency_key parameter recorded in metadata but not enforced.
- **No deduplication:** Each invocation is independent; cannot prevent duplicate work.

### Kanban Adapter

- **Explicit requirement:** Idempotency requires Kanban backend enforcement (not implemented in prototype).
- **No automatic deduplication:** Each creation gets unique task_id even for identical goals.
- **Caller responsibility:** Must use idempotency_key explicitly when backend supports enforcement.

**Evidence:** Scenario `repeated_invocation` (9/9 successful).

---

## Recovery Boundaries

### Stale Claim Recovery

- **Inline:** No claim lifecycle; no stale claim recovery mechanism.
- **Kanban:** TTL-based expiration; stale claims auto-recovered on dispatch.

**Evidence:** Scenario `stale_claim_recovery` (9/9 successful).

**Recovery boundaries:**
- **Inline:** N/A — no claims.
- **Kanban:** Stale claims (expired TTL) are reclaimed by dispatcher and made available for new claims.

---

### Concurrent Claim Recovery

- **Inline:** No concurrent claim mechanism; each dispatch executes independently.
- **Kanban:** Concurrent claim race resolves to one winner; losers receive explicit KanbanAdapterError.

**Recovery boundaries:**
- **Inline:** N/A — no serialization needed.
- **Kanban:** Loser must retry or abandon; winner proceeds.

**Evidence:** Scenario `concurrent_claim` (9/9 successful).

---

### Dependency Failure Recovery

- **Inline:** No dependency tracking; failures are local to the session.
- **Kanban:** Tasks can depend on other tasks; upstream failures block downstream via parent-child links.

**Evidence:** Not directly tested in contrast matrix; derived from Kanban system design.

**Recovery boundaries:**
- **Inline:** N/A — no dependency model.
- **Kanban:** Upstream task must complete/unblock; downstream task automatically promotes to ready.

---

## Capability Detection

Before invoking Kanban-only operations, callers MUST verify the adapter supports them. Callers MUST verify the adapter supports them before invoking any optional operation:

```python
# Check if adapter supports Kanban operations
if hasattr(adapter, 'claim'):
    # Safe to use claim(), poll(), read_result(), etc.
    task = adapter.create(title, assignee="worker")
    claimed = adapter.claim(task["id"])
else:
    # Inline adapter — use dispatch() only
    result = adapter.dispatch(goal, assignee="worker")
```

**Contract requirement:** Adapters that do NOT support an operation must NOT define the method. Use `hasattr()` or `getattr()` for capability detection.

---

## Metadata Contract

Both adapters return metadata in DispatchResult and DispatchStatus. The following fields are standard across adapters:

### Standard metadata fields (present in both adapters):

- `backend` (str): "inline" or "kanban".
- `assignee` (str | None): Target profile if provided.

### Adapter-specific fields (not guaranteed across adapters):

**Inline:**
- `dry_run` (bool): Recorded if provided.
- `retry` (int): Recorded if provided.
- `timeout` (int): Recorded if provided.
- `cancellation_token` (str): Recorded if provided.
- `idempotency_key` (str): Recorded if provided.

**Kanban:**
- Full task record fields from `kanban show --json`.
- `status` (str): ready, running, done, blocked.
- `assignee`, `workspace`, `branch`, etc.

**Contract rule:** Callers MUST NOT depend on adapter-specific metadata fields. Use only standard fields for cross-adapter code.

---

## Deterministic Behavior

All contract operations must produce deterministic results:

- **Success:** Returns predictable result structure.
- **Failure:** Raises specific exception with diagnostic message.
- **Ambiguity:** Never return success when operation failed; errors are explicit.

**Evidence verification:** All 9 scenarios produced deterministic outcomes (8/8 inline successful, 8/8 kanban successful, 1 scenario with expected limitation differences).

---

## Versioning and Evolution

This is v0.3.0 of the adapter contract. Evolution rules:

1. **Additive only:** New operations may be added; existing operations cannot change signature or behavior.
2. **Deprecated before removal:** Operations slated for removal must be marked deprecated with migration path.
3. **Adapter-specific isolation:** Backend-specific operations remain optional and capability-checked.

---

## Test Coverage Requirements

Contract tests MUST cover:

1. **Lifecycle paths:** create → claim/execute → poll → result (Kanban), dispatch (Inline).
2. **Failure paths:** Explicit failures, stale claims, concurrent races.
3. **Dry-run semantics:** Verify side-effect prevention (or explicit lack thereof).
4. **Idempotency:** Verify repeated invocation behavior (or explicit lack of enforcement).
5. **Capability detection:** Verify Kanban-only operations are not present on Inline.
6. **Deterministic behavior:** Verify error messages and exceptions are predictable.

**Reference test suite:** tests/test_adapter_contract.py

---

## Appendix: Evidence Trace

This contract is derived from the following evidence artifacts:

- **Contrast matrix:** docs/adapter-contrast-matrix.md (generated from 16268bb)
- **Contrast script:** scripts/adapter_contrast_matrix.py
- **Base ref:** 57b9b17 (inline-default adapter extraction)
- **Tests:**
  - tests/test_inline_dispatch_characterization.py (8 passed)
  - tests/test_kanban_adapter.py (7 passed)

**Provenance:** Every contract statement traces to observed evidence or is explicitly excluded as unsupported.