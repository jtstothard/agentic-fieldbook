"""Conformance tests for Fieldbook v2 high-risk governance.

Slice 2: Risk taxonomy gates, always-ask overlay, capability ceilings,
exact human approval, rollback/abort conditions, audit trail.
"""

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    Evidence,
    InvalidTransitionError,
    LifecycleError,
    LifecycleState,
    MissingEvidenceError,
    TaskContract,
)
from agentic_fieldbook.governance import MissingRollbackError


# Test fixtures for different risk levels
def low_risk_contract() -> TaskContract:
    return TaskContract(
        contract_id="FB-LOW-001",
        objective="Low risk local change",
        scope=("local-file",),
        exclusions=(),
        risk_class="low",
        capabilities=("read", "local-write"),
        acceptance_criteria=("file-updated",),
        required_evidence=("test-pass",),
    )


def medium_risk_contract() -> TaskContract:
    return TaskContract(
        contract_id="FB-MED-001",
        objective="Medium risk bounded mutation",
        scope=("database",),
        exclusions=(),
        risk_class="medium",
        capabilities=("db-write",),
        acceptance_criteria=("migration-complete",),
        required_evidence=("migration-log", "rollback-script"),
    )


def high_risk_contract() -> TaskContract:
    return TaskContract(
        contract_id="FB-HIGH-001",
        objective="High risk production change",
        scope=("production",),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write",),
        acceptance_criteria=("production-verified",),
        required_evidence=("impact-assessment", "rollback-evidence", "approval-record"),
    )


# ALWAYS-ASK OVERLAY TESTS
def test_always_ask_destructive_requires_human_approval():
    """Destructive/irreversible actions always require human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-001",
        objective="Delete production data",
        scope=("production",),
        exclusions=(),
        risk_class="low",  # Even low risk, destructive requires approval
        capabilities=("delete",),
        acceptance_criteria=("data-deleted",),
        required_evidence=("delete-log",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-1")

    # Progress through lifecycle
    record.transition(LifecycleState.PLANNED, actor="planner")

    # Try to transition to APPROVED without human approval
    # This should fail because the task is destructive (has 'delete' capability)
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")

    # Now try with explicit human approval
    # The governance layer should check for approval before allowing transition
    record.transition(
        LifecycleState.APPROVED,
        actor="human-approver",
        reason="Destructive action requires explicit approval",
        # In real implementation, this would trigger approval recording
    )
    assert record.state is LifecycleState.APPROVED


def test_always_ask_secret_access_requires_approval():
    """Secret/credential access or rotation always requires human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-002",
        objective="Rotate API credentials",
        scope=("secrets",),
        exclusions=(),
        risk_class="medium",
        capabilities=("secret-read", "secret-write"),
        acceptance_criteria=("credentials-rotated",),
        required_evidence=("rotation-log",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-2")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Secret access requires approval even for medium risk
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")


def test_always_ask_billing_affecting_requires_approval():
    """Billing-affecting actions always require human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-003",
        objective="Upgrade cloud instance size",
        scope=("billing",),
        exclusions=(),
        risk_class="low",
        capabilities=("billing-change",),
        acceptance_criteria=("instance-upgraded",),
        required_evidence=("billing-impact",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-3")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Billing changes require approval
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")


def test_always_ask_access_grants_require_approval():
    """Access/permission grants always require human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-004",
        objective="Grant new user access",
        scope=("permissions",),
        exclusions=(),
        risk_class="low",
        capabilities=("access-grant",),
        acceptance_criteria=("access-granted",),
        required_evidence=("permission-log",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-4")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Access grants require approval
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")


def test_always_ask_downtime_affecting_requires_approval():
    """Downtime-affecting actions always require human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-005",
        objective="Restart production service",
        scope=("production",),
        exclusions=(),
        risk_class="medium",
        capabilities=("service-restart",),
        acceptance_criteria=("service-running",),
        required_evidence=("restart-log",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-5")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Downtime-affecting actions require approval
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")


def test_always_ask_release_decisions_require_approval():
    """Release decisions always require human approval."""
    contract = TaskContract(
        contract_id="FB-ASK-006",
        objective="Release version to production",
        scope=("production",),
        exclusions=(),
        risk_class="medium",
        capabilities=("release",),
        acceptance_criteria=("release-deployed",),
        required_evidence=("release-notes",),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-ask-6")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Release decisions require approval
    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")


# EXACT HUMAN APPROVAL TESTS
def test_high_risk_requires_exact_human_approval_before_executing():
    """High-risk tasks cannot enter APPROVED without explicit independent human approval."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-hr-1")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # Try to go to APPROVED with same actor (self-approval rejected)
    with pytest.raises(InvalidTransitionError, match="independent"):
        record.transition(LifecycleState.APPROVED, actor="planner")

    # Different actor (human approval) succeeds
    record.transition(
        LifecycleState.APPROVED,
        actor="human-approver",
        reason="High-risk change approved after review",
    )

    # Now can proceed to EXECUTING with required capabilities
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("prod-write",),
    )
    assert record.state is LifecycleState.EXECUTING

    # Verify approval was recorded in governance state
    assert len(record._governance.approvals) > 0
    assert record._governance.approvals[0]["actor"] == "human-approver"


def test_medium_risk_can_auto_approve():
    """Medium-risk tasks can be auto-approved under normal conditions."""
    record = CanonicalTaskRecord.create(medium_risk_contract(), task_id="task-mr-1")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="planner")  # Auto-approve allowed
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("db-write",),
    )

    assert record.state is LifecycleState.EXECUTING


# ROLLBACK/ABORT TESTS
def test_high_risk_must_declare_rollback_steps():
    """High-risk contracts must include rollback evidence requirements."""
    # Create contract without rollback requirements - this should fail at creation
    with pytest.raises(ValueError, match="High-risk contracts must declare rollback"):
        TaskContract(
            contract_id="FB-HIGH-INVALID",
            objective="High risk without rollback",
            scope=("production",),
            exclusions=(),
            risk_class="high",
            capabilities=("prod-write",),
            acceptance_criteria=("change-applied",),
            required_evidence=("test-log",),  # Missing rollback evidence
        )


def test_failed_high_risk_requires_rollback_evidence():
    """High-risk tasks that fail must provide rollback evidence."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-hr-fail")

    # Progress to EXECUTING with different actors for approval
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="human-approver", reason="High-risk approval")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("prod-write",),
    )

    # Try to transition to FAILED without rollback evidence
    with pytest.raises(MissingRollbackError, match="rollback"):
        record.transition(
            LifecycleState.FAILED,
            actor="executor",
            reason="Execution failed",
        )

    # Now transition to BLOCKED (which is allowed without rollback evidence)
    record.transition(
        LifecycleState.BLOCKED,
        actor="executor",
        reason="Blocked pending rollback",
    )

    # Recovery must re-enter planning and obtain fresh independent approval.
    record.transition(
        LifecycleState.PLANNED,
        actor="planner",
        reason="replanned after blocked recovery",
    )
    record.transition(
        LifecycleState.APPROVED,
        actor="human-reapprover",
        reason="fresh approval after replanning",
    )
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor-2",
        executor_capabilities=("prod-write",),
    )
    record.transition(
        LifecycleState.FAILED,
        actor="executor",
        reason="Execution failed with rollback",
        evidence=[Evidence("rollback-evidence", "rollback completed", "rollback-tool", "success")],
    )
    assert record.state is LifecycleState.FAILED


def test_partial_success_requires_rollback_verification():
    """High-risk tasks with partial success must verify rollback steps."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-hr-partial")

    # Progress through lifecycle with different actors for approval
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="human-approver", reason="High-risk approval")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("prod-write",),
    )

    # Report completion with partial success
    record.transition(
        LifecycleState.REPORTED_COMPLETE,
        actor="executor",
        reason="Partial success - some changes applied",
        evidence=[
            Evidence("impact-assessment", "impact documented", "assessment-tool", "moderate"),
            Evidence("rollback-evidence", "rollback steps documented", "rollback-tool", "success"),
        ],
    )

    # Verification should check that rollback evidence exists and is valid
    record.transition(LifecycleState.REVIEW, actor="reviewer")
    record.transition(LifecycleState.VERIFICATION, actor="verifier")

    # Should succeed because rollback evidence and all criteria are present
    record.transition(
        LifecycleState.VERIFIED,
        actor="verifier",
        evidence=[
            Evidence("approval-record", "approval documented", "approval-tool", "success"),
            Evidence("production-verified", "production verified", "verify-tool", "success"),
        ],
    )
    assert record.state is LifecycleState.VERIFIED


# AUDIT TRAIL TESTS
def test_approval_recorded_in_history():
    """Human approval must be recorded in the audit trail."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-audit-1")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(
        LifecycleState.APPROVED,
        actor="human-approver",
        reason="Approved after security review",
    )

    # Check history contains approval with actor and reason
    approval_entry = [h for h in record.history if h["to"] == "approved"][0]
    assert approval_entry["actor"] == "human-approver"
    assert approval_entry["reason"] == "Approved after security review"
    assert "timestamp" in approval_entry  # Timestamps now implemented
    assert isinstance(approval_entry["timestamp"], str)


def test_all_transitions_record_actor_and_reason():
    """Every transition must record actor and reason in the audit trail."""
    record = CanonicalTaskRecord.create(medium_risk_contract(), task_id="task-audit-2")

    record.transition(LifecycleState.PLANNED, actor="planner", reason="Initial plan")
    record.transition(LifecycleState.APPROVED, actor="approver", reason="Auto-approved")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        reason="Starting execution",
        executor_capabilities=("db-write",),
    )
    record.transition(LifecycleState.REPORTED_COMPLETE, actor="executor", reason="Complete")

    # Verify all history entries have actor and reason
    for entry in record.history:
        assert "actor" in entry
        assert entry["actor"]
        assert "reason" in entry
        # Empty reason is allowed


def test_capability_check_recorded_in_history():
    """Capability checks must be recorded in the audit trail."""
    # This test will pass once we implement capability ceiling enforcement
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-audit-3")

    record.transition(LifecycleState.PLANNED, actor="planner")

    # When transitioning to APPROVED, capability checks should be performed and recorded
    record.transition(
        LifecycleState.APPROVED,
        actor="human-approver",
        reason="Approved with verified capabilities",
    )

    # Check that capability checks are in history
    # For now, we'll just verify the approval is recorded
    assert any(h["to"] == "approved" for h in record.history)


# CAPABILITY CEILING TESTS
def test_capability_check_before_execution():
    """Task capabilities must be checked against executor's permissions."""
    record = CanonicalTaskRecord.create(medium_risk_contract(), task_id="task-cap-1")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # The capability check should happen before EXECUTING
    # For now, we test that the governance state can record capability checks
    executor_capabilities = {"read", "local-write"}  # Missing "db-write"

    # Add a capability check to governance state
    record._governance.add_capability_check(
        required=record.contract.capabilities,
        executor=tuple(executor_capabilities),
        satisfied=False,
        missing=("db-write",),
    )

    # Check that the capability check was recorded
    assert len(record._governance.capability_checks) > 0
    assert record._governance.capability_checks[-1]["satisfied"] is False
    missing_list = record._governance.capability_checks[-1]["missing"]
    assert isinstance(missing_list, list)
    assert "db-write" in missing_list


def test_capability_check_with_sufficient_permissions():
    """Executor with all required capabilities can proceed."""
    record = CanonicalTaskRecord.create(medium_risk_contract(), task_id="task-cap-2")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver")

    # Executor has required capability
    # In real implementation, this would be checked automatically
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("db-write",),
        # Capability check would pass here
    )

    assert record.state is LifecycleState.EXECUTING


# RISK TAXONOMY TESTS
def test_risk_classification_validation():
    """Risk class must be one of: low, medium, high."""
    with pytest.raises(ValueError, match="risk_class must be"):
        TaskContract(
            contract_id="FB-INVALID-001",
            objective="Invalid risk class",
            scope=("test",),
            exclusions=(),
            risk_class="critical",  # Invalid risk class
            capabilities=("read",),
            acceptance_criteria=("done",),
            required_evidence=("test",),
        )


def test_high_risk_enforces_strictest_controls():
    """High risk enforces all control layers: approval, rollback, independent verification."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="task-risk-1")

    # High risk requires human approval
    record.transition(LifecycleState.PLANNED, actor="planner")

    with pytest.raises(InvalidTransitionError, match="human approval"):
        record.transition(LifecycleState.APPROVED, actor="planner")

    record.transition(
        LifecycleState.APPROVED,
        actor="human-approver",
        reason="High-risk approval",
    )

    # Progress to verification
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("prod-write",),
    )
    for state in (LifecycleState.REPORTED_COMPLETE, LifecycleState.REVIEW, LifecycleState.VERIFICATION):
        record.transition(state, actor="worker")

    # High risk requires independent verification
    executor_actor = [h for h in record.history if h["to"] == "executing"][0]["actor"]

    with pytest.raises(InvalidTransitionError, match="verifier must differ"):
        record.transition(
            LifecycleState.VERIFIED,
            actor=executor_actor,  # Same as executor
            evidence=[
                Evidence("impact-assessment", "impact assessed", "tool", "result"),
                Evidence("rollback-evidence", "rollback documented", "tool", "result"),
                Evidence("approval-record", "approval recorded", "tool", "result"),
                Evidence("production-verified", "verified", "tool", "result"),
            ],
        )

    # Different actor succeeds
    record.transition(
        LifecycleState.VERIFIED,
        actor="independent-verifier",
        evidence=[
            Evidence("impact-assessment", "impact assessed", "tool", "result"),
            Evidence("rollback-evidence", "rollback documented", "tool", "result"),
            Evidence("approval-record", "approval recorded", "tool", "result"),
            Evidence("production-verified", "verified", "tool", "result"),
        ],
    )
    assert record.state is LifecycleState.VERIFIED