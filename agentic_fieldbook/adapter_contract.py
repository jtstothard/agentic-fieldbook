"""Stable v0.3.0 adapter contract derived from empirical evidence.

This contract defines the minimal stable interface for dispatch adapters,
derived from inline/Kanban contrast matrix observations (commit 16268bb).
Every operation, parameter, and behavior trace back to either:
1. Directly observed evidence from at least one adapter
2. Explicit exclusion when an adapter cannot support the operation

The contract is versioned to support evolution while maintaining backward
compatibility for v0.3.0 implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Standardized task status values across adapters.

    Evidence trace:
    - Inline: Only reports 'synchronous' (docs/adapter-contrast-matrix.md:28-30)
    - Kanban: Tracks ready, running, done, blocked (docs/adapter-contrast-matrix.md:47-48)
    """
    SYNCHRONOUS = "synchronous"  # Inline-only: task completed immediately
    READY = "ready"  # Kanban: task ready to be claimed
    RUNNING = "running"  # Kanban: task is currently executing
    DONE = "done"  # Kanban: task completed successfully
    BLOCKED = "blocked"  # Kanban: task blocked due to failure


class AdapterCapability(str, Enum):
    """Declared adapter capabilities.

    Evidence trace:
    All capabilities derived from observed behavior in contrast matrix.
    """
    SYNC_DISPATCH = "sync_dispatch"  # Synchronous execution (inline)
    ASYNC_DISPATCH = "async_dispatch"  # Asynchronous execution (kanban)
    TASK_ID_PERSISTENCE = "task_id_persistence"  # Persistent task IDs (kanban)
    RESULT_PERSISTENCE = "result_persistence"  # Durable result storage (kanban)
    STATUS_TRACKING = "status_tracking"  # Lifecycle state tracking (kanban)
    CLAIM_LIFECYCLE = "claim_lifecycle"  # Claim/ownership management (kanban)
    DRY_RUN_ENFORCEMENT = "dry_run_enforcement"  # Real dry-run enforcement (kanban)
    IDEMPOTENCY_ENFORCEMENT = "idempotency_enforcement"  # Idempotency keys (kanban)
    CONCURRENT_CLAIM_DETECTION = "concurrent_claim_detection"  # Race detection (kanban)
    STALE_CLAIM_RECOVERY = "stale_claim_recovery"  # TTL-based recovery (kanban)
    FAILURE_STATE_MANAGEMENT = "failure_state_management"  # Block state (kanban)


# Result types for adapter operations

@dataclass
class CreateResult:
    """Result from creating a task."""
    success: bool
    task_id: str | None
    status: TaskStatus
    metadata: dict[str, Any]


@dataclass
class ClaimResult:
    """Result from claiming a task."""
    success: bool
    task_id: str
    status: TaskStatus
    metadata: dict[str, Any]


@dataclass
class StatusResult:
    """Result from getting task status."""
    success: bool
    status: TaskStatus
    metadata: dict[str, Any]
    message: str = ""


@dataclass
class ResultResult:
    """Result from reading task result."""
    success: bool
    result: str | None
    metadata: dict[str, Any]


@dataclass
class DispatchResult:
    """Result from dispatch operation (claims and executes)."""
    success: bool
    dispatched_count: int
    reclaimed_count: int
    anomalies: list[dict[str, Any]]
    metadata: dict[str, Any]


# Exception types

class TaskNotFoundError(RuntimeError):
    """Raised when a task ID is not found."""
    pass


class ClaimLostError(RuntimeError):
    """Raised when a claim is lost to another process."""
    pass


class UnsupportedOperationError(RuntimeError):
    """Raised when an adapter does not support an operation."""
    pass


class DispatchAdapter(ABC):
    """Stable v0.3.0 adapter contract for task dispatch.

    This abstract base class defines the minimal stable interface that adapters
    must implement. All methods have clear semantics derived from empirical evidence.

    Contract stability guarantees:
    1. Method signatures will not change within v0.3.x
    2. Return type structures will not break backward compatibility
    3. New optional methods may be added (with default implementations)
    4. Capabilities are declared upfront so callers can detect missing features
    """

    @abstractmethod
    def create_task(
        self,
        title: str,
        *,
        assignee: str | None = None,
        context: str = "",
        dry_run: bool = False,
        idempotency_key: str = "",
        **kwargs: Any,
    ) -> CreateResult:
        """Create a task.

        Evidence trace:
        - Inline: Returns task_id=None, status=SYNCHRONOUS (dispatch.py:146-132)
        - Kanban: Returns unique task_id, status=READY (kanban_adapter.py:70-85)

        Args:
            title: Task title or description.
            assignee: Profile to assign task to.
            context: Additional context.
            dry_run: Preview without execution.
            idempotency_key: Idempotency key.

        Returns:
            CreateResult with task_id and status.
        """
        ...

    @abstractmethod
    def claim_task(self, task_id: str, *, ttl: int | None = None) -> ClaimResult:
        """Claim ownership of a task for execution.

        Evidence trace:
        - Inline: Not supported, raises UnsupportedOperationError (dispatch.py:134-136)
        - Kanban: Supports claim with TTL (kanban_adapter.py:87-116)

        Args:
            task_id: Task identifier.
            ttl: Time-to-live for claim.

        Returns:
            ClaimResult with status after claiming.

        Raises:
            ClaimLostError: Lost concurrent claim race.
            UnsupportedOperationError: Adapter doesn't support claims.
        """
        ...

    @abstractmethod
    def get_status(self, task_id: str) -> StatusResult:
        """Get the current status of a task.

        Evidence trace:
        - Inline: Always returns SYNCHRONOUS (dispatch.py:138-153)
        - Kanban: Returns actual task state (kanban_adapter.py:118-119)

        Args:
            task_id: Task identifier (ignored by inline adapter).

        Returns:
            StatusResult with current status.

        Raises:
            TaskNotFoundError: Task ID not found (Kanban-only).
        """
        ...

    @abstractmethod
    def read_result(self, task_id: str) -> ResultResult:
        """Read the result of a completed task.

        Evidence trace:
        - Inline: No persistence, returns None (dispatch.py:155-164)
        - Kanban: Returns persisted result (kanban_adapter.py:121-122)

        Args:
            task_id: Task identifier.

        Returns:
            ResultResult with task outcome.

        Raises:
            TaskNotFoundError: Task ID not found (Kanban-only).
        """
        ...

    @abstractmethod
    def dispatch(self, *, dry_run: bool = False) -> DispatchResult:
        """Dispatch tasks (claims and executes).

        Evidence trace:
        - Inline: Synchronous execution (dispatch.py:166-178)
        - Kanban: Dispatches with optional dry-run (kanban_adapter.py:124-135)

        Args:
            dry_run: If True, preview without execution.

        Returns:
            DispatchResult with execution statistics.
        """
        ...

    @abstractmethod
    def handle_failure(self, task_id: str, reason: str) -> dict[str, Any]:
        """Handle a task failure, potentially transitioning to blocked state.

        Evidence trace:
        - Inline: Not supported (dispatch.py:180-182)
        - Kanban: Transitions to blocked state (kanban_adapter.py:137-145)

        Args:
            task_id: Task identifier.
            reason: Failure reason.

        Returns:
            Dict with operation details.

        Raises:
            UnsupportedOperationError: Adapter doesn't support failure handling.
        """
        ...

    @abstractmethod
    def get_capabilities(self) -> set[AdapterCapability]:
        """Get the set of capabilities supported by this adapter.

        Evidence trace:
        - Inline: Empty set (no optional capabilities) (dispatch.py:184-186)
        - Kanban: Multiple capabilities from contrast matrix (docs/adapter-contrast-matrix.md:33-52)

        Returns:
            Set of AdapterCapability values supported.
        """
        ...