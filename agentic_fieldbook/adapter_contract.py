"""Stable v0.3 adapter contract.

The stable operation is ``dispatch(goal, *, assignee)``. Kanban lifecycle
operations are optional capabilities and are intentionally not requirements of
this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class TaskStatus(str, Enum):
    SYNCHRONOUS = "synchronous"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"


class AdapterCapability(str, Enum):
    SYNC_DISPATCH = "sync_dispatch"
    ASYNC_DISPATCH = "async_dispatch"
    TASK_ID_PERSISTENCE = "task_id_persistence"
    TASK_CREATION = "task_creation"
    RESULT_PERSISTENCE = "result_persistence"
    STATUS_TRACKING = "status_tracking"
    CLAIM_LIFECYCLE = "claim_lifecycle"
    DRY_RUN_ENFORCEMENT = "dry_run_enforcement"
    IDEMPOTENCY_ENFORCEMENT = "idempotency_enforcement"
    CONCURRENT_CLAIM_DETECTION = "concurrent_claim_detection"
    STALE_CLAIM_RECOVERY = "stale_claim_recovery"
    FAILURE_STATE_MANAGEMENT = "failure_state_management"


@dataclass
class CreateResult:
    success: bool
    task_id: str | None
    status: TaskStatus
    metadata: dict[str, Any]


@dataclass
class ClaimResult:
    success: bool
    task_id: str
    status: TaskStatus
    metadata: dict[str, Any]


@dataclass
class StatusResult:
    success: bool
    status: TaskStatus
    metadata: dict[str, Any]
    message: str = ""


@dataclass
class ResultResult:
    success: bool
    result: str | None
    metadata: dict[str, Any]


@dataclass
class DispatchResult:
    success: bool
    task_id: str | None
    metadata: dict[str, Any]
    message: str = ""


class TaskNotFoundError(RuntimeError):
    pass


class ClaimLostError(RuntimeError):
    pass


class UnsupportedOperationError(RuntimeError):
    pass


@runtime_checkable
class ClaimLifecycle(Protocol):
    def claim_task(self, task_id: str, *, ttl: int | None = None) -> ClaimResult: ...


class ResultReader(Protocol):
    def read_result(self, task_id: str) -> ResultResult: ...


class FailureHandler(Protocol):
    def handle_failure(self, task_id: str, reason: str) -> dict[str, Any]: ...


@runtime_checkable
class TaskCreator(Protocol):
    def create_task(self, title: str, *, assignee: str | None = None, **kwargs: Any) -> CreateResult: ...


class DispatchAdapter(ABC):
    """Minimal stable contract shared by dispatch adapters."""

    @abstractmethod
    def dispatch(self, goal: str, *, assignee: str | None) -> DispatchResult:
        """Dispatch a real, non-empty goal."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self, task_id: str) -> StatusResult:
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self) -> set[AdapterCapability]:
        raise NotImplementedError
