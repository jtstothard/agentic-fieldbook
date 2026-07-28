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
        context: str = "",
        dry_run: bool = False,
        retry: int = 0,
        timeout: int = 0,
        cancellation_token: str = "",
        idempotency_key: str = "",
    ) -> DispatchResult:
        """
        Dispatch a task via the inline-default path.
        
        The inline path is synchronous and session-scoped. Results are returned
        immediately, and there is no persistent task ID across sessions.
        
        Args:
            goal: The task description or goal string.
            assignee: The Hermes profile to assign the task to.
            context: Additional context for the task execution.
            dry_run: If True, preview execution without side effects.
            retry: Number of retry attempts (inline path doesn't own retry policy).
            timeout: Timeout in seconds (inline path doesn't own timeout policy).
            cancellation_token: Token for cancellation (inline path doesn't own cancellation).
            idempotency_key: Key for idempotent requests (inline path doesn't enforce this).
        
        Returns:
            DispatchResult with success=True, task_id=None (session-scoped), and metadata.
        """
        metadata: dict[str, Any] = {
            "backend": "inline",
            "assignee": assignee,
        }
        
        # Record parameters for observability, even though inline path doesn't enforce them
        if dry_run:
            metadata["dry_run"] = dry_run
        if retry:
            metadata["retry"] = retry
        if timeout:
            metadata["timeout"] = timeout
        if cancellation_token:
            metadata["cancellation_token"] = cancellation_token
        if idempotency_key:
            metadata["idempotency_key"] = idempotency_key
        
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