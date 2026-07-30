"""Negative bypass test - TDD approach for review finding #4."""

import pytest

from agentic_fieldbook.governance import CapabilityMismatchError
from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
)


def test_single_actor_cannot_bypass_all_controls():
    """A single actor cannot plan, approve, and execute a high-risk task entirely alone."""
    contract = TaskContract(
        contract_id="FB-BYPASS-001",
        objective="High-risk task requiring multiple controls",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write", "delete"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-evidence"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-bypass-1")

    # Same actor tries to plan
    record.transition(LifecycleState.PLANNED, actor="same-actor")

    # Same actor tries to approve - should fail at approval gate for high-risk
    with pytest.raises(InvalidTransitionError, match="independent"):
        record.transition(LifecycleState.APPROVED, actor="same-actor")


def test_two_actor_bypass_still_blocked_at_executing():
    """Even with two actors, bypass attempts should fail at EXECUTING gate."""
    contract = TaskContract(
        contract_id="FB-BYPASS-002",
        objective="High-risk task with destructive capability",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write", "delete"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-evidence"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-bypass-2")

    # First actor plans
    record.transition(LifecycleState.PLANNED, actor="planner")

    # Second actor approves (this is allowed)
    record.transition(LifecycleState.APPROVED, actor="approver")
    record.bind_approval_receipt(
        receipt_id="receipt-test", contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch, recovery_attempt=record.recovery_attempt,
    )

    # Second actor tries to execute with missing capabilities - should fail at capability check
    with pytest.raises(CapabilityMismatchError, match="lacks required capabilities"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="approver",
            executor_capabilities=("prod-write",),  # Missing "delete"
        )


def test_bypass_attempt_defense_in_depth_blocks_same_approver_executor():
    """Attempt to have approver also execute should be blocked by defense-in-depth."""
    contract = TaskContract(
        contract_id="FB-BYPASS-003",
        objective="High-risk destructive task",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("delete", "prod-write"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-evidence"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-bypass-3")

    # First actor plans
    record.transition(LifecycleState.PLANNED, actor="planner")

    # Second actor approves
    record.transition(LifecycleState.APPROVED, actor="approver")
    record.bind_approval_receipt(
        receipt_id="receipt-test", contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch, recovery_attempt=record.recovery_attempt,
    )

    # Approver tries to execute - should fail at defense-in-depth check
    with pytest.raises(InvalidTransitionError, match="executor must differ from approver"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="approver",
            executor_capabilities=("delete", "prod-write"),
        )


def test_full_bypass_fails_at_executing_gate():
    """Complete bypass attempt (plan+approve+execute) must fail at EXECUTING transition."""
    contract = TaskContract(
        contract_id="FB-BYPASS-004",
        objective="Always-ask task",
        scope=("production",),
        exclusions=(),
        risk_class="low",  # Low risk but always-ask due to secret-read
        capabilities=("secret-read", "write"),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-bypass-4")

    # Same actor plans
    record.transition(LifecycleState.PLANNED, actor="same-actor")

    # Different actor approves (allowed for always-ask)
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Approver tries to execute - should fail at defense-in-depth for always-ask
    with pytest.raises(InvalidTransitionError, match="executor must differ from approver"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="approver",
            executor_capabilities=("secret-read", "write"),
        )


def test_low_risk_without_capabilities_can_be_single_actor():
    """Low-risk tasks without capabilities can be executed by same actor."""
    contract = TaskContract(
        contract_id="FB-BYPASS-005",
        objective="Low-risk task no special capabilities",
        scope=("local",),
        exclusions=(),
        risk_class="low",
        capabilities=(),  # No capabilities declared
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-bypass-5")

    # Same actor can plan, approve, and execute
    record.transition(LifecycleState.PLANNED, actor="same-actor")
    record.transition(LifecycleState.APPROVED, actor="same-actor")
    record.transition(LifecycleState.EXECUTING, actor="same-actor")

    assert record.state is LifecycleState.EXECUTING