"""Inline adapter implementing the v0.3.0 adapter contract.

This module contains the contract-compliant InlineAdapter implementation.
The legacy InlineAdapter remains in dispatch.py for backward compatibility.

Evidence trace for all behaviors:
- docs/adapter-contrast-matrix.md (inline adapter observations)
"""

from __future__ import annotations

from agentic_fieldbook.adapter_contract import (
    AdapterCapability,

    DispatchAdapter,
    DispatchResult,

    StatusResult,
    TaskStatus,
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

    def dispatch(self, goal: str, *, assignee: str | None) -> DispatchResult:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        return DispatchResult(
            success=True,
            task_id=None,
            metadata={"backend": "inline", "assignee": assignee},
            message="Task dispatched inline - synchronous execution",
        )

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


    def get_capabilities(self) -> set[AdapterCapability]:
        """Inline adapter has no optional capabilities.

        Evidence: Inline adapter only supports synchronous dispatch.
        All other capabilities are absent (docs/adapter-contrast-matrix.md:17-73).
        """
        return {AdapterCapability.SYNC_DISPATCH}  # Inline's observed synchronous capability