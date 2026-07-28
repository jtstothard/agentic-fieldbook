"""Extraction tests for the inline-default experimental adapter seam."""

from __future__ import annotations

import pytest

from agentic_fieldbook.dispatch import get_default_adapter
@pytest.fixture
def inline():
    """Return the current default inline path through its public seam."""
    return get_default_adapter()


def test_default_path_is_inline_and_has_no_durable_task_id(inline):
    result = inline.dispatch(
        "run the bounded task",
        assignee="executor",
        context="contract and acceptance evidence",
    )

    assert result.success is True
    assert result.task_id is None
    assert result.metadata == {"backend": "inline", "assignee": "executor"}


def test_completion_is_observed_as_synchronous_status(inline):
    result = inline.dispatch("record a completed task", assignee="executor")
    status = inline.get_status(result.task_id or "inline-session-task")

    assert status.success is True
    assert status.metadata == {"backend": "inline", "status": "synchronous"}
    assert "synchronous" in status.message


def test_result_capture_is_immediate_and_repeatable(inline):
    first = inline.dispatch("same bounded task", assignee="executor")
    second = inline.dispatch("same bounded task", assignee="executor")

    assert first.success is True
    assert second.success is True
    assert first.task_id is None
    assert second.task_id is None
    assert first.metadata == second.metadata


def test_dry_run_and_extra_execution_context_do_not_create_durable_state(inline):
    result = inline.dispatch(
        "inspect the bounded task",
        assignee="executor",
        context="dry-run",
        dry_run=True,
        retry=3,
        timeout=1,
        cancellation_token="cancel-me",
        idempotency_key="same-request",
    )

    assert result.success is True
    assert result.task_id is None
    assert result.metadata["backend"] == "inline"
    assert result.metadata["assignee"] == "executor"


def test_empty_goal_remains_an_immediate_inline_outcome(inline):
    result = inline.dispatch("", assignee="executor")

    assert result.success is True
    assert result.task_id is None
    assert result.metadata["backend"] == "inline"


def test_failure_retry_timeout_and_cancellation_have_no_durable_recovery_state(inline):
    # Inline dispatch does not own retry/timeout/cancellation policy.
    # The session manages these; the adapter only reports synchronous completion.
    result = inline.dispatch(
        "a task whose executor reports failure",
        assignee="executor",
    )
    # Even if the session handles failure, inline dispatch still returns success
    # because execution completed synchronously (the result content is session-owned).
    assert result.success is True
    assert result.task_id is None

    # Status queries also reflect synchronous completion, not durable recovery state.
    observed = inline.get_status("any-inline-id")
    assert observed.success is True
    assert observed.metadata["status"] == "synchronous"


def test_invalid_assignee_is_not_a_backend_failure(inline):
    result = inline.dispatch("bounded task", assignee=None)

    assert result.success is True
    assert result.task_id is None
    assert result.metadata == {"backend": "inline", "assignee": None}
