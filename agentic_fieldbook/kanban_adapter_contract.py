"""Kanban adapter implementing the v0.3.0 contract.

This module wraps the original KanbanAdapter to implement the DispatchAdapter
contract interface defined in adapter_contract.py.
"""

from __future__ import annotations

from typing import Any

from agentic_fieldbook.adapter_contract import (
    AdapterCapability,
    ClaimLostError,
    ClaimResult,
    CreateResult,
    DispatchAdapter,
    DispatchResult,
    ResultResult,
    StatusResult,
    TaskNotFoundError,
    TaskStatus,
)
from agentic_fieldbook.kanban_adapter import KanbanAdapter, KanbanAdapterError


class KanbanAdapterContract(DispatchAdapter):
    """Kanban adapter implementing the v0.3.0 contract.

    This adapter wraps the Kanban backend and implements the contract with
    the following semantics:
    - create_task: Returns persistent task_id, status=READY
    - claim_task: Claims task with TTL, raises ClaimLostError on race loss
    - get_status: Returns actual task status (READY/RUNNING/DONE/BLOCKED)
    - read_result: Returns persisted result or None
    - dispatch: Dispatches tasks, recovers stale claims
    - handle_failure: Transitions task to BLOCKED state
    - get_capabilities: Returns full capability set
    """

    def __init__(self, *, home: str, board: str = "shadow") -> None:
        """Initialize the Kanban adapter contract wrapper."""
        self._adapter = KanbanAdapter(home=home, board=board)

    def create_task(
        self,
        title: str,
        *,
        assignee: str | None = None,
        context: str = "",
        dry_run: bool = False,
        idempotency_key: str = "",
        workspace: str = "scratch",
        branch: str | None = None,
        **kwargs: Any,
    ) -> CreateResult:
        """Create a task with persistent ID."""
        result = self._adapter.create(
            title=title,
            assignee=assignee,
            workspace=workspace,
            branch=branch,
        )

        # Map Kanban status to contract enum
        task_status = TaskStatus.READY
        if result.get("status") == "ready":
            task_status = TaskStatus.READY
        elif result.get("status") == "running":
            task_status = TaskStatus.RUNNING
        elif result.get("status") == "done":
            task_status = TaskStatus.DONE
        elif result.get("status") == "blocked":
            task_status = TaskStatus.BLOCKED

        return CreateResult(
            success=True,
            task_id=result["id"],
            status=task_status,
            metadata={
                "backend": "kanban",
                "assignee": assignee,
                "workspace": workspace,
                "branch": branch,
                "dry_run": dry_run,
                "idempotency_key": idempotency_key,
            },
        )

    def claim_task(self, task_id: str, *, ttl: int | None = None) -> ClaimResult:
        """Claim a task for execution, with loser detection."""
        try:
            result = self._adapter.claim(task_id, ttl=ttl)

            # Map Kanban status to contract enum
            task_status = TaskStatus.READY
            if result.get("status") == "ready":
                task_status = TaskStatus.READY
            elif result.get("status") == "running":
                task_status = TaskStatus.RUNNING
            elif result.get("status") == "done":
                task_status = TaskStatus.DONE
            elif result.get("status") == "blocked":
                task_status = TaskStatus.BLOCKED

            return ClaimResult(
                success=True,
                task_id=task_id,
                status=task_status,
                metadata={
                    "backend": "kanban",
                    "ttl": ttl,
                    "note": "Task claimed successfully",
                },
            )
        except KanbanAdapterError as e:
            if "lost" in str(e).lower():
                raise ClaimLostError(f"Lost claim race for task {task_id}")
            raise

    def get_status(self, task_id: str) -> StatusResult:
        """Query task status."""
        try:
            result = self._adapter.poll(task_id)

            # Map Kanban status to contract enum
            task_status = TaskStatus.READY
            if result.get("status") == "ready":
                task_status = TaskStatus.READY
            elif result.get("status") == "running":
                task_status = TaskStatus.RUNNING
            elif result.get("status") == "done":
                task_status = TaskStatus.DONE
            elif result.get("status") == "blocked":
                task_status = TaskStatus.BLOCKED

            return StatusResult(
                success=True,
                status=task_status,
                metadata={
                    "backend": "kanban",
                    "task_data": result,
                },
            )
        except KanbanAdapterError as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                raise TaskNotFoundError(task_id)
            raise

    def read_result(self, task_id: str) -> ResultResult:
        """Read task result from persistence."""
        try:
            result = self._adapter.read_result(task_id)
            return ResultResult(
                success=True,
                result=result,
                metadata={
                    "backend": "kanban",
                    "note": "Result persisted in Kanban backend",
                },
            )
        except KanbanAdapterError as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                raise TaskNotFoundError(task_id)
            # Result may not exist yet (task not done)
            return ResultResult(
                success=False,
                result=None,
                metadata={
                    "backend": "kanban",
                    "error": str(e),
                },
            )

    def dispatch(self, *, dry_run: bool = False) -> DispatchResult:
        """Dispatch tasks, recovering stale claims."""
        report = self._adapter.dispatch(dry_run=dry_run)

        return DispatchResult(
            success=True,
            dispatched_count=report.get("dispatched_count", 0),
            reclaimed_count=report.get("reclaimed", 0),
            anomalies=report.get("anomalies", []),
            metadata={
                "backend": "kanban",
                "dry_run": dry_run,
                "report": report,
            },
        )

    def handle_failure(self, task_id: str, reason: str) -> dict[str, Any]:
        """Handle task failure by transitioning to BLOCKED state."""
        try:
            result = self._adapter.handle_failure(task_id, reason)
            return {
                "operation": "handle_failure",
                "task_id": task_id,
                "reason": reason,
                "backend": "kanban",
                **result,
            }
        except KanbanAdapterError as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                raise TaskNotFoundError(task_id)
            raise

    def get_capabilities(self) -> set[AdapterCapability]:
        """Return full Kanban adapter capabilities."""
        return {
            AdapterCapability.TASK_ID_PERSISTENCE,
            AdapterCapability.ASYNC_DISPATCH,
            AdapterCapability.CLAIM_LIFECYCLE,
            AdapterCapability.STALE_CLAIM_RECOVERY,
            AdapterCapability.RESULT_PERSISTENCE,
            AdapterCapability.FAILURE_STATE_MANAGEMENT,
            AdapterCapability.CONCURRENT_CLAIM_DETECTION,
            AdapterCapability.STATUS_TRACKING,
            AdapterCapability.DRY_RUN_ENFORCEMENT,
        }