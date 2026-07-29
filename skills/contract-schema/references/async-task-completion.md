# Async Task-Completion Pattern

## Overview

Async task-completion is a pattern where APIs queue work and return a task ID immediately, rather than blocking until completion. The caller must poll a status endpoint until the task reaches a terminal state.

## Generic Pattern

```
1. Caller submits work to target API
2. Target API returns { task_id: "...", status: "queued" }
3. Caller polls status endpoint every N seconds
4. When status == "stopped" and exitstatus == "OK", task is complete
5. On timeout, treat as failure
```

## Anti-Pattern

**Do not treat task ID receipt as success.**

The pilot evidence demonstrated this failure mode: a wrapper assumed success when the target returned a task ID, but the queued operation could still fail. The wrapper proceeded without verifying completion.

## Recommended Parameters

- **Poll interval:** 2 seconds
- **Timeout:** 90 seconds
- **Timeout handling:** Return `success: false`, `error: "task_timeout"`

## Success Conditions

Task completion is confirmed when:

1. Status endpoint returns `status: "stopped"`
2. AND `exitstatus == "OK"`

## Example Pseudocode

```python
def wait_for_async_task(task_id):
    start = time.time()
    while time.time() - start < 90:
        status = get_task_status(task_id)
        if status["status"] == "stopped":
            if status["exitstatus"] == "OK":
                return { "success": true }
            else:
                return { "success": false, "error": "task_failed" }
        time.sleep(2)
    return { "success": false, "error": "task_timeout" }
```

## Key Terms

- **Target API:** The remote service accepting async work
- **Task ID:** Identifier returned when work is queued
- **Status endpoint:** API endpoint to poll for task status
- **Exitstatus:** Task result code; `OK` indicates successful completion
- **Poll interval:** Delay between status checks
- **Timeout:** Maximum time to wait before abandoning the task

## Applicability

Use this pattern when:

- API documentation indicates async task handling
- Queue response includes a task identifier
- Separate status endpoint exists for polling
- Task execution time exceeds typical request timeouts

Do not use this pattern for synchronous APIs that return results directly.