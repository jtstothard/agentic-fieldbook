"""Inline adapter implementing the v0.3.0 adapter contract.

This module contains the contract-compliant InlineAdapter implementation.
The legacy InlineAdapter remains in dispatch.py for backward compatibility.

Evidence trace for all behaviors:
- docs/adapter-contrast-matrix.md (inline adapter observations)
"""

from __future__ import annotations

from typing import Any

from agentic_fieldbook.adapter_contract import (
    AdapterCapability,
    ClaimResult,
    CreateResult,
    DispatchAdapter,
    DispatchResult,
    ResultResult,
    StatusResult,
    TaskStatus,
    UnsupportedOperationError,
)


class InlineAdapterContract(DispatchAdapter):
    """Inline adapter implementing the v0.3.0 adapter contract.

    This adapter models the observed inline behavior:
    - Synchronous execution
    - Session-scoped results
    - No persistent task ID across sessions
    - No dry-run enforcement (parameter recorded but informational)
    - No idempotency enforcement
    - No claim lifecycle
    - No failure state management

    Evidence trace:
    - Synchronous execution (docs/adapter-contrast-matrix.md:17-18)
    - No task ID persistence (docs/adapter-contrast-matrix.md:19)
    - No dry-run enforcement (docs/adapter-contrast-matrix.md:159-162)
    - No idempotency enforcement (docs/adapter-contrast-matrix.md:175-177)
    """

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
        """Create a task (inline: session-scoped, no persistent ID).

        Evidence: Inline path has no persistent task ID (docs/adapter-contrast-matrix.md:19)
        """
        metadata = {
            "backend": "inline",
            "title": title,
            "assignee": assignee,
            "context": context,
            "dry_run": dry_run,  # Recorded but not enforced (line 160)
            "idempotency_key": idempotency_key,  # Recorded but not enforced (line 91)
        }

        return CreateResult(
            success=True,
            task_id=None,  # Session-scoped, no persistent ID
            status=TaskStatus.SYNCHRONOUS,  # Executes immediately
            metadata=metadata,
        )

    def claim_task(self, task_id: str, *, ttl: int | None = None) -> ClaimResult:
        """Claim not supported by inline adapter (no claim lifecycle).

        Evidence: No concurrent claim mechanism (docs/adapter-contrast-matrix.md:188)

        Raises:
            UnsupportedOperationError: Inline adapter doesn't support claims.
        """
        raise UnsupportedOperationError("claim_task")

    def get_status(self, task_id: str) -> StatusResult:
        """Get status of an inline task (always SYNCHRONOUS).

        Since inline tasks are session-scoped and execute synchronously,
        status is always reported as synchronous completion.

        Evidence: Status is always 'synchronous' (docs/adapter-contrast-matrix.md:28-30)

        Args:
            task_id: Not used for inline adapter (session-scoped).

        Returns:
            StatusResult indicating synchronous completion.
        """
        return StatusResult(
            success=True,
            status=TaskStatus.SYNCHRONOUS,
            metadata={
                "backend": "inline",
                "note": "task_id ignored - session-scoped execution",
            },
            message="Inline task completed synchronously - session-scoped",
        )

    def read_result(self, task_id: str) -> ResultResult:
        """Read result (inline: no persistence, returns None).

        Evidence: No durable result storage (docs/adapter-contrast-matrix.md:145-147)

        Args:
            task_id: Task identifier (ignored).

        Returns:
            ResultResult with no persistent result.
        """
        return ResultResult(
            success=True,
            result=None,
            metadata={
                "backend": "inline",
                "note": "Results are session-scoped and not persisted",
            },
        )

    def dispatch(self, *, dry_run: bool = False) -> DispatchResult:
        """Dispatch tasks (inline: synchronous execution).

        Evidence: Synchronous execution, no async task backend (docs/adapter-contrast-matrix.md:29)

        Args:
            dry_run: Ignored by inline adapter (parameter recorded but not enforced).

        Returns:
            DispatchResult with execution statistics.
        """
        return DispatchResult(
            success=True,
            dispatched_count=1,  # Would execute synchronously
            reclaimed_count=0,
            anomalies=[],
            metadata={
                "backend": "inline",
                "dry_run": dry_run,
                "note": "Inline path executes synchronously",
            },
        )

    def handle_failure(self, task_id: str, reason: str) -> dict[str, Any]:
        """Handle failure not supported by inline adapter (no explicit failure state).

        Evidence: No explicit failure handling (docs/adapter-contrast-matrix.md:218)

        Raises:
            UnsupportedOperationError: Inline adapter doesn't support failure handling.
        """
        raise UnsupportedOperationError("handle_failure")

    def get_capabilities(self) -> set[AdapterCapability]:
        """Inline adapter has no optional capabilities.

        Evidence: Inline adapter only supports synchronous dispatch.
        All other capabilities are absent (docs/adapter-contrast-matrix.md:17-73).
        """
        return {AdapterCapability.SYNC_DISPATCH}  # Inline's observed synchronous capability