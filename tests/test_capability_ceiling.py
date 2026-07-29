"""Capability ceiling enforcement tests - TDD approach for review finding #1."""

import pytest

from agentic_fieldbook.governance import CapabilityMismatchError
from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
)


def test_capability_ceiling_blocks_missing_capabilities():
    """Execution must be blocked when executor lacks required capabilities."""
    contract = TaskContract(
        contract_id="FB-CAP-001",
        objective="Task requiring multiple capabilities",
        scope=("test",),
        exclusions=(),
        risk_class="medium",
        capabilities=("db-write", "secret-read", "prod-access"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-cap-missing")

    # Progress through lifecycle
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Try to execute with missing capabilities (missing "secret-read" and "prod-access")
    executor_capabilities = ("db-write", "local-read")  # Missing 2 required capabilities
    with pytest.raises(CapabilityMismatchError, match="lacks required capabilities"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=executor_capabilities,
        )


def test_capability_ceiling_allows_sufficient_capabilities():
    """Execution succeeds when executor has all required capabilities."""
    contract = TaskContract(
        contract_id="FB-CAP-002",
        objective="Task with multiple capabilities",
        scope=("test",),
        exclusions=(),
        risk_class="medium",
        capabilities=("db-write", "secret-read", "prod-access"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-cap-sufficient")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Execute with all required capabilities
    executor_capabilities = ("db-write", "secret-read", "prod-access", "local-read")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=executor_capabilities,
    )
    assert record.state is LifecycleState.EXECUTING


def test_capability_ceiling_requires_executor_capabilities_parameter():
    """Execution must fail when executor_capabilities parameter is not provided."""
    contract = TaskContract(
        contract_id="FB-CAP-003",
        objective="Task requiring capabilities",
        scope=("test",),
        exclusions=(),
        risk_class="low",
        capabilities=("read", "write"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-cap-no-param")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Try to execute without providing executor_capabilities parameter
    with pytest.raises(InvalidTransitionError, match="executor_capabilities required"):
        record.transition(LifecycleState.EXECUTING, actor="executor")


def test_capability_ceiling_not_required_for_empty_capabilities():
    """Tasks with empty capability tuple can execute without capability check."""
    contract = TaskContract(
        contract_id="FB-CAP-004",
        objective="Task with no capabilities",
        scope=("test",),
        exclusions=(),
        risk_class="low",
        capabilities=(),  # No capabilities declared
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-cap-empty")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Should be able to execute without capability check
    record.transition(LifecycleState.EXECUTING, actor="executor")
    assert record.state is LifecycleState.EXECUTING


def test_capability_ceiling_case_insensitive():
    """Capability checks should be case-insensitive."""
    contract = TaskContract(
        contract_id="FB-CAP-005",
        objective="Case insensitive capability check",
        scope=("test",),
        exclusions=(),
        risk_class="medium",
        capabilities=("DB-Write", "Secret-READ"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-cap-case")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Executor capabilities in different case should still match
    executor_capabilities = ("db-write", "secret-read")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=executor_capabilities,
    )
    assert record.state is LifecycleState.EXECUTING