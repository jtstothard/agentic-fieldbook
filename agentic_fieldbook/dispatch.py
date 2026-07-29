"""Hermes dispatch adapters for Agentic Fieldbook.

This module provides adapter implementations for dispatching tasks to agent workers.
The inline-default adapter wraps the existing Hermes delegate_task behavior without
introducing a stable contract interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DispatchResult:
    """Result from a dispatch operation."""

    success: bool
    task_id: str | None
    metadata: dict[str, Any]
    message: str = ""


@dataclass
class DispatchStatus:
    """Status of a dispatched task."""

    success: bool
    metadata: dict[str, Any]
    message: str = ""


class InlineAdapter:
    """Inline-default dispatch adapter using Hermes delegate_task.

    This is a thin experimental seam around the existing inline-default dispatch
    behavior. It preserves the observed semantics: synchronous execution,
    session-scoped results, and no persistent task ID across sessions.

    The adapter does NOT call delegate_task directly in the test context - it
    models the externally observable behavior of the inline path. The actual
    delegate_task call would happen in the real execution flow through the
    planning-routing skill's dispatch mechanics.
    """

    def dispatch(
        self,
        goal: str,
        *,
        assignee: str | None,
    ) -> DispatchResult:
        """
        Dispatch a task via the inline-default path.

        The inline path is synchronous and session-scoped. Results are returned
        immediately, and there is no persistent task ID across sessions.

        Args:
            goal: The task description or goal string.
            assignee: The Hermes profile to assign the task to.

        Returns:
            DispatchResult with success=True, task_id=None (session-scoped), and metadata.
        """
        metadata: dict[str, Any] = {
            "backend": "inline",
            "assignee": assignee,
        }

        return DispatchResult(
            success=True,
            task_id=None,  # Inline path has no persistent task ID
            metadata=metadata,
            message="Task dispatched inline - synchronous execution",
        )

    def get_status(self, task_id: str) -> DispatchStatus:
        """
        Get status of an inline task.

        Since inline tasks are session-scoped and execute synchronously, status
        is always reported as synchronous completion. The task_id parameter is
        accepted for interface compatibility but not used.

        Args:
            task_id: Not used for inline adapter (session-scoped).

        Returns:
            DispatchStatus indicating synchronous completion.
        """
        return DispatchStatus(
            success=True,
            metadata={"backend": "inline", "status": "synchronous"},
            message="Inline task completed synchronously - session-scoped",
        )


def get_default_adapter() -> InlineAdapter:
    """Return the default inline dispatch adapter.

    This is the inline-default path that v0.1 uses. No adapter selection
    or stable contract is exposed to users - this is an experimental seam
    for interface derivation in v0.3.0.
    """
    return InlineAdapter()