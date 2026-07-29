# Inline/Kanban Adapter Contrast Matrix

**Generated:** 2026-07-29T01:26:42.369459Z
**Repository:** `aa3806681f68984b1cc47109eab2ea20ab2c0e96`
**Python:** 3.13.5
**Platform:** Linux-6.12.96+deb13-amd64-x86_64-with-glibc2.41

## Summary

- **Total scenarios:** 9
- **Inline adapter:** 9/9 successful
- **Kanban adapter:** 9/9 successful

## Key Differences

### Inline Adapter

- Each invocation is independent - no deduplication
- Inline path returns task_id=None (session-scoped, no persistent ID)
- No claim lifecycle, so no stale claim recovery mechanism
- No concurrent claim mechanism - each dispatch executes independently
- No explicit claim operation - tasks execute synchronously on dispatch
- No explicit failure handling - failures are exceptions or error messages
- No idempotency key enforcement (the inline API does not expose this control)
- No polling required - results available immediately
- No separate result read - results returned synchronously from dispatch
- No side-effect prevention - inline path does not own execution policy
- No task requeue on failure
- No winner selection or race detection
- Status is always 'synchronous' - no task state machine
- Synchronous execution - no asynchronous task backend
- The inline API does not expose a dry_run control
- get_status() accepts task_id but ignores it (session-scoped)

### Kanban Adapter

- Claim enforces serial execution (one winner)
- Concurrent claim race resolves to one winner
- Create and dispatch are separate operations
- Dry run can reclaim stale tasks without executing
- Each creation gets unique task_id even for identical goals
- Explicit claim operation with TTL-based ownership
- Explicit failure handling with reason recording
- Failed tasks transition to 'blocked' state for review
- Loser gets explicit error (KanbanAdapterError)
- No automatic deduplication - explicit idempotency required via idempotency_key
- Results persist beyond task completion
- Rich metadata available in status
- Separate poll operation to check task status
- Separate read_result operation for durable result storage
- Stale claims auto-recovered on dispatch
- Status tracks actual task state (ready, running, done, blocked)
- TTL-based expiration with reclamation
- Task has persistent task_id and status
- dispatch() can run as dry_run without executing tasks
- dispatch() supports dry_run parameter

## Limitations

### Inline Adapter

- Cannot poll for async task completion
- Cannot prevent duplicate work
- Cannot re-read results after session ends
- Cannot record and requeue failed tasks
- Cannot recover from stale claims
- Cannot request a dry run through the inline seam
- Cannot serialize concurrent access to the same task
- Cannot track task lifecycle states (ready, running, done, blocked)
- Cannot verify no mutations occurred
- No distributed lock semantics
- No distributed task coordination
- No durable result storage
- No failure state in task lifecycle
- No persistent task ID across sessions
- No persistent task state to query
- No separate claim lifecycle
- No task-level idempotency
- No timeout-based reclamation
- Results are session-scoped and lost on session exit
- Status queries are trivial (always reports synchronous completion)

### Kanban Adapter

- Additional complexity for simple synchronous tasks
- Claim expiration and recovery complexity
- Claim race complexity requires careful TTL management
- Dry run behavior depends on Kanban dispatch implementation
- Failure handling requires explicit API calls
- Idempotency requires Kanban backend enforcement (not implemented in this adapter)
- Requires Kanban backend for result persistence
- Requires Kanban backend for state persistence
- Requires Kanban backend infrastructure
- Requires TTL configuration and dispatch polling
- Requires explicit claim lifecycle management

## Scenario Outcomes


### create_dispatch

**Inline** ✅
- Duration: 0.0s
- Difference: Inline path returns task_id=None (session-scoped, no persistent ID)
- Difference: Synchronous execution - no asynchronous task backend
- Limitation: No persistent task ID across sessions
- Limitation: No distributed task coordination
- Limitation: Results are session-scoped and lost on session exit

**Kanban** ✅
- Duration: 0.669s
- Difference: Create and dispatch are separate operations
- Difference: Task has persistent task_id and status
- Difference: dispatch() can run as dry_run without executing tasks
- Limitation: Requires Kanban backend infrastructure
- Limitation: Additional complexity for simple synchronous tasks

### claim_poll

**Inline** ✅
- Duration: 0.0s
- Difference: No explicit claim operation - tasks execute synchronously on dispatch
- Difference: No polling required - results available immediately
- Difference: get_status() accepts task_id but ignores it (session-scoped)
- Limitation: Cannot poll for async task completion
- Limitation: No separate claim lifecycle
- Limitation: Status queries are trivial (always reports synchronous completion)

**Kanban** ✅
- Duration: 1.438s
- Difference: Explicit claim operation with TTL-based ownership
- Difference: Separate poll operation to check task status
- Difference: Claim enforces serial execution (one winner)
- Limitation: Requires explicit claim lifecycle management
- Limitation: Claim expiration and recovery complexity

### status_check

**Inline** ✅
- Duration: 0.0s
- Difference: Status is always 'synchronous' - no task state machine
- Limitation: Cannot track task lifecycle states (ready, running, done, blocked)
- Limitation: No persistent task state to query

**Kanban** ✅
- Duration: 0.607s
- Difference: Status tracks actual task state (ready, running, done, blocked)
- Difference: Rich metadata available in status
- Limitation: Requires Kanban backend for state persistence

### result_read

**Inline** ✅
- Duration: 0.0s
- Difference: No separate result read - results returned synchronously from dispatch
- Limitation: Cannot re-read results after session ends
- Limitation: No durable result storage

**Kanban** ✅
- Duration: 1.807s
- Difference: Separate read_result operation for durable result storage
- Difference: Results persist beyond task completion
- Limitation: Requires Kanban backend for result persistence

### dry_run

**Inline** ✅
- Duration: 0.0s
- Difference: The inline API does not expose a dry_run control
- Difference: No side-effect prevention - inline path does not own execution policy
- Limitation: Cannot request a dry run through the inline seam
- Limitation: Cannot verify no mutations occurred

**Kanban** ✅
- Duration: 0.579s
- Difference: dispatch() supports dry_run parameter
- Difference: Dry run can reclaim stale tasks without executing
- Limitation: Dry run behavior depends on Kanban dispatch implementation

### repeated_invocation

**Inline** ✅
- Duration: 0.0s
- Difference: Each invocation is independent - no deduplication
- Difference: No idempotency key enforcement (the inline API does not expose this control)
- Limitation: Cannot prevent duplicate work
- Limitation: No task-level idempotency

**Kanban** ✅
- Duration: 0.764s
- Difference: Each creation gets unique task_id even for identical goals
- Difference: No automatic deduplication - explicit idempotency required via idempotency_key
- Limitation: Idempotency requires Kanban backend enforcement (not implemented in this adapter)

### concurrent_claim

**Inline** ✅
- Duration: 0.005s
- Difference: No concurrent claim mechanism - each dispatch executes independently
- Difference: No winner selection or race detection
- Limitation: Cannot serialize concurrent access to the same task
- Limitation: No distributed lock semantics

**Kanban** ✅
- Duration: 1.563s
- Difference: Concurrent claim race resolves to one winner
- Difference: Loser gets explicit error (KanbanAdapterError)
- Limitation: Claim race complexity requires careful TTL management

### stale_claim_recovery

**Inline** ✅
- Duration: 0.0s
- Difference: No claim lifecycle, so no stale claim recovery mechanism
- Limitation: Cannot recover from stale claims
- Limitation: No timeout-based reclamation

**Kanban** ✅
- Duration: 3.412s
- Difference: Stale claims auto-recovered on dispatch
- Difference: TTL-based expiration with reclamation
- Limitation: Requires TTL configuration and dispatch polling

### handle_failure

**Inline** ✅
- Duration: 0.0s
- Difference: No explicit failure handling - failures are exceptions or error messages
- Difference: No task requeue on failure
- Limitation: Cannot record and requeue failed tasks
- Limitation: No failure state in task lifecycle

**Kanban** ✅
- Duration: 2.119s
- Difference: Explicit failure handling with reason recording
- Difference: Failed tasks transition to 'blocked' state for review
- Limitation: Failure handling requires explicit API calls

---

*Report generated by `scripts/adapter_contrast_matrix.py`*
