"""Approval defense-in-depth tests - TDD approach for review finding #2."""

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
)


def test_high_risk_same_approver_and_executor_blocked():
    """High-risk tasks cannot have the same actor approve and execute."""
    contract = TaskContract(
        contract_id="FB-DEF-001",
        objective="High-risk task",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-evidence"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-def-high")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Same actor who approved tries to execute - should be blocked
    with pytest.raises(InvalidTransitionError, match="executor must differ from approver"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="approver",
            executor_capabilities=("prod-write",),
        )


def test_always_ask_same_approver_and_executor_blocked():
    """Always-ask tasks cannot have the same actor approve and execute."""
    contract = TaskContract(
        contract_id="FB-DEF-002",
        objective="Destructive task (always-ask)",
        scope=("production",),
        exclusions=(),
        risk_class="low",  # Low risk but always-ask due to destructive capability
        capabilities=("delete",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-def-ask")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Same actor who approved tries to execute - should be blocked
    with pytest.raises(InvalidTransitionError, match="executor must differ from approver"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="approver",
            executor_capabilities=("delete",),
        )


def test_medium_risk_allows_same_approver_and_executor():
    """Medium-risk tasks without always-ask capabilities can have same actor approve and execute."""
    contract = TaskContract(
        contract_id="FB-DEF-003",
        objective="Medium-risk task",
        scope=("database",),
        exclusions=(),
        risk_class="medium",
        capabilities=("db-write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-def-medium")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Same actor who approved can execute for medium risk without always-ask
    record.transition(
        LifecycleState.EXECUTING,
        actor="approver",
        executor_capabilities=("db-write",),
    )
    assert record.state is LifecycleState.EXECUTING


def test_low_risk_allows_same_approver_and_executor():
    """Low-risk tasks can have same actor approve and execute."""
    contract = TaskContract(
        contract_id="FB-DEF-004",
        objective="Low-risk task",
        scope=("local",),
        exclusions=(),
        risk_class="low",
        capabilities=("read",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-def-low")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Same actor who approved can execute for low risk
    record.transition(
        LifecycleState.EXECUTING,
        actor="approver",
        executor_capabilities=("read",),
    )
    assert record.state is LifecycleState.EXECUTING


def test_defense_in_depth_checks_who_approved():
    """Defense-in-depth check verifies who actually approved the task."""
    contract = TaskContract(
        contract_id="FB-DEF-005",
        objective="High-risk task",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-evidence"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-def-check")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")

    # Different actor approved, so execution should be allowed
    record.transition(
        LifecycleState.EXECUTING,
        actor="approver-2",
        executor_capabilities=("prod-write",),
    )
    assert record.state is LifecycleState.EXECUTING