# v0.3.0 Adapter Contract Traceability

This document traces every element of the v0.3.0 adapter contract to either:
1. Direct empirical evidence from the inline/Kanban contrast matrix (the final fix commit)
2. Explicit exclusion when an adapter cannot support an operation

**Contract files:**
- `agentic_fieldbook/adapter_contract.py` - Stable contract definition
- `agentic_fieldbook/inline_adapter_contract.py` - Inline adapter implementation
- `tests/test_adapter_contract.py` - Contract verification tests

**Evidence source:**
- `docs/adapter-contrast-matrix.md` - Contrast matrix observations

## Contract Elements Traced to Evidence

### TaskStatus Enum

| Value | Evidence | Line |
|-------|----------|------|
| SYNCHRONOUS | Inline: Status is always 'synchronous' - no task state machine | docs/adapter-contrast-matrix.md:28-30 |
| READY | Kanban: Task ready to be claimed | docs/adapter-contrast-matrix.md:52 |
| RUNNING | Kanban: Task is currently executing | docs/adapter-contrast-matrix.md:52 |
| DONE | Kanban: Task completed successfully | docs/adapter-contrast-matrix.md:52 |
| BLOCKED | Kanban: Task blocked due to failure | docs/adapter-contrast-matrix.md:52 |

**Rationale:** The contract covers all observed statuses. Inline only has SYNCHRONOUS; Kanban has the full lifecycle states.

### AdapterCapability Enum

| Value | Evidence | Line |
|-------|----------|------|
| SYNC_DISPATCH | Inline: Synchronous execution - no asynchronous task backend | docs/adapter-contrast-matrix.md:31 |
| ASYNC_DISPATCH | Kanban: Asynchronous task backend | docs/adapter-contrast-matrix.md:31 (contrast) |
| TASK_ID_PERSISTENCE | Kanban: Task has persistent task_id and status | docs/adapter-contrast-matrix.md:54 |
| TASK_CREATION | Kanban: Optional create_task operation returns a new task | docs/adapter-contrast-matrix.md:41 |
| RESULT_PERSISTENCE | Kanban: Results persist beyond task completion | docs/adapter-contrast-matrix.md:47 |
| STATUS_TRACKING | Kanban: Status tracks actual task state (ready, running, done, blocked) | docs/adapter-contrast-matrix.md:52 |
| CLAIM_LIFECYCLE | Kanban: Explicit claim operation with TTL-based ownership | docs/adapter-contrast-matrix.md:42 |
| DRY_RUN_ENFORCEMENT | Kanban: dispatch() supports dry_run parameter | docs/adapter-contrast-matrix.md:55-56 |
| IDEMPOTENCY_ENFORCEMENT | Kanban: Explicit idempotency required via idempotency_key | docs/adapter-contrast-matrix.md:46 |
| CONCURRENT_CLAIM_DETECTION | Kanban: Concurrent claim race resolves to one winner | docs/adapter-contrast-matrix.md:38 |
| STALE_CLAIM_RECOVERY | Kanban: Stale claims auto-recovered on dispatch | docs/adapter-contrast-matrix.md:51 |
| FAILURE_STATE_MANAGEMENT | Kanban: Failed tasks transition to 'blocked' state for review | docs/adapter-contrast-matrix.md:44 |

**Rationale:** Each capability maps to a specific observed behavior. Inline only supports SYNC_DISPATCH; Kanban supports all others.

### Optional operation: create_task (Kanban capability)

**Parameters:**
- `title`: Task title (observed in the Kanban create_task capability)
- `assignee`: Profile to assign (Kanban)
- `context`: Additional context (Kanban)
- `dry_run`: Preview without execution (Kanban enforces; not exposed by inline) - docs/adapter-contrast-matrix.md:55-56
- `idempotency_key`: Kanban-only backend control; not exposed by the inline dispatch seam - docs/adapter-contrast-matrix.md:46

**Inline behavior:**
- Not defined; the inline adapter exposes only the shared `dispatch(goal, assignee)` seam.

**Kanban behavior:**
- Returns unique `task_id` - docs/adapter-contrast-matrix.md:41
- Returns `status=READY` (ready to be claimed)

### Operation: claim_task

**Parameters:**
- `task_id`: Task identifier to claim
- `ttl`: Time-to-live for the claim (observed in KanbanAdapter.claim())

**Inline behavior:**
- Raises `UnsupportedOperationError` (no claim lifecycle) - docs/adapter-contrast-matrix.md:199

**Kanban behavior:**
- Returns `ClaimResult` with status after claiming
- Raises `ClaimLostError` if lost concurrent claim race - docs/adapter-contrast-matrix.md:197

### Operation: get_status

**Parameters:**
- `task_id`: Task identifier

**Inline behavior:**
- Returns `status=SYNCHRONOUS` (always completed) - docs/adapter-contrast-matrix.md:28-30
- Ignores `task_id` parameter (session-scoped) - docs/adapter-contrast-matrix.md:31

**Kanban behavior:**
- Returns actual task state (ready, running, done, blocked) - docs/adapter-contrast-matrix.md:52

### Operation: read_result

**Parameters:**
- `task_id`: Task identifier

**Inline behavior:**
- Returns `result=None` (no persistent result) - docs/adapter-contrast-matrix.md:145-147
- No separate result read, results returned from dispatch

**Kanban behavior:**
- Returns persisted result - docs/adapter-contrast-matrix.md:151

### Operation: dispatch

**Parameters:**
- `goal`: Task description or goal
- `assignee`: Target profile (keyword-only)

**Inline behavior:**
- Synchronous execution (no async task backend) - docs/adapter-contrast-matrix.md:31
- `dry_run`: Not exposed by the inline dispatch seam

**Kanban behavior:**
- Dispatches the goal through the Kanban adapter using the shared seam.
- The separate Kanban board dispatcher has a `dry_run` mode (docs/adapter-contrast-matrix.md:55-56); that control is not part of this contract operation.

### Operation: handle_failure

**Parameters:**
- `task_id`: Task identifier
- `reason`: Failure reason

**Inline behavior:**
- Raises `UnsupportedOperationError` (no explicit failure handling) - docs/adapter-contrast-matrix.md:218

**Kanban behavior:**
- Transitions failed tasks to 'blocked' state - docs/adapter-contrast-matrix.md:226
- Records reason in task

### Operation: get_capabilities

**Inline behavior:**
- Returns `{AdapterCapability.SYNC_DISPATCH}`; no optional lifecycle capabilities

**Kanban behavior:**
- Returns set with all applicable capabilities

### Result Types

All result types are derived from observed return values:

| Type | Evidence |
|------|----------|
| CreateResult | Observed in the Kanban adapter; inline evidence covers synchronous dispatch, not task creation |
| ClaimResult | Observed in KanbanAdapter.claim() |
| StatusResult | Observed in both adapters (inline: SYNCHRONOUS, kanban: actual state) |
| ResultResult | Observed in KanbanAdapter.read_result() |
| DispatchResult | Observed in KanbanAdapter.dispatch() |

### Exception Types

| Type | Evidence | Line |
|------|----------|------|
| ClaimLostError | Kanban: Loser gets explicit error (KanbanAdapterError) | docs/adapter-contrast-matrix.md:197 |
| TaskNotFoundError | Kanban: task_id not found (implicitly required for robust operations) |
| UnsupportedOperationError | Inline: Cannot support operations that require persistence/claims | docs/adapter-contrast-matrix.md:55-74 |

**Rationale:** Exceptions explicitly categorize failure modes observed in contrast matrix.

## Explicit Exclusions

The following operations are explicitly excluded for adapters that cannot support them:

### Inline Adapter Exclusions

| Operation | Reason for Exclusion | Evidence |
|-----------|---------------------|----------|
| claim_task | No claim lifecycle, no distributed lock semantics | docs/adapter-contrast-matrix.md:188-193 |
| handle_failure | No explicit failure handling, no failure state in lifecycle | docs/adapter-contrast-matrix.md:218-221 |
| result persistence | No durable result storage, results session-scoped | docs/adapter-contrast-matrix.md:145-147 |
| task_id persistence | No persistent task ID across sessions | docs/adapter-contrast-matrix.md:19 |
| status tracking | Status is always 'synchronous' - no state machine | docs/adapter-contrast-matrix.md:28-30 |
| dry_run enforcement | Not exposed by the inline dispatch seam | docs/adapter-contrast-matrix.md:55-56 |
| idempotency enforcement | Not exposed by the inline dispatch seam | docs/adapter-contrast-matrix.md:46 |
| concurrent claim detection | No concurrent claim mechanism | docs/adapter-contrast-matrix.md:188-190 |
| stale claim recovery | No claim lifecycle, so no stale claim recovery mechanism | docs/adapter-contrast-matrix.md:202-206 |

### Kanban Adapter Exclusions

| Operation | Reason for Exclusion | Evidence |
|-----------|---------------------|----------|
| idempotency enforcement | Requires Kanban backend enforcement (not implemented in adapter) | docs/adapter-contrast-matrix.md:81-83 |

## Contract Stability Guarantees

The v0.3.0 contract includes the following stability guarantees:

1. **Method signatures will not change within v0.3.x**
   - All abstract methods in `DispatchAdapter` are frozen
   - New optional methods may be added (with default implementations)

2. **Return type structures will not break backward compatibility**
   - All result types are dataclasses with clearly defined fields
   - New optional fields may be added

3. **Capabilities are declared upfront**
   - `get_capabilities()` allows callers to detect missing features before attempting operations
   - Prevents mistaking unsupported operations for successful dispatch

4. **Explicit unsupported operation handling**
   - `UnsupportedOperationError` clearly signals when an adapter cannot support an operation
   - Cannot be mistaken for successful dispatch or transient failure

## Verification

The contract is verified by:

1. **Contract compliance tests** (`tests/test_adapter_contract.py`)
   - 23 tests verifying interface, capabilities, additive superset, failure semantics

2. **Traceability documentation** (this file)
   - Every element traced to evidence or explicitly excluded

3. **Evidence preservation**
   - Contrast matrix preserved in `docs/adapter-contrast-matrix.md`
   - Generated from the final fix commit; final rerun artifact is `/tmp/adapter-contrast-v03-final.json` (9 scenarios × 2 adapters, 9/9 each)

## User-Facing Impact

Per the task requirements, the stable contract is **not exposed through user-facing backend switching in this ticket**. The contract serves as:
- A foundation for future backend selection
- Clear documentation of adapter capabilities and limitations
- A testable interface for adapter implementations

The legacy inline adapter (`agentic_fieldbook/dispatch.py`) remains the narrow
goal/assignee seam for backward compatibility. The contract-compliant
implementation is in `agentic_fieldbook/inline_adapter_contract.py`.