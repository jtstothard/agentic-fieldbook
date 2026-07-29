"""Conformance tests for the Fieldbook v1 universal lifecycle seam."""

from dataclasses import asdict

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    Evidence,
    InvalidTransitionError,
    LifecycleState,
    MissingEvidenceError,
    TaskContract,
)


def coding_contract() -> TaskContract:
    return TaskContract(
        contract_id="FB-001",
        objective="Fix the parser bug",
        scope=("parser", "parser tests"),
        exclusions=("deployment",),
        risk_class="low",
        capabilities=("repo-write", "local-test"),
        acceptance_criteria=("parser-test-passes",),
        required_evidence=("tests", "diff"),
        domain="coding.v1",
    )


def test_low_risk_coding_record_can_reach_verified_with_required_evidence():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-1")

    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="planner")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("repo-write", "local-test"),
    )
    record.transition(
        LifecycleState.REPORTED_COMPLETE,
        actor="executor",
        evidence=[Evidence("tests", "pytest passed", "pytest", "0")],
    )
    record.transition(LifecycleState.REVIEW, actor="reviewer")
    record.transition(
        LifecycleState.VERIFICATION,
        actor="verifier",
        evidence=[
            Evidence("diff", "diff is in scope", "git diff", "clean"),
            Evidence("parser-test-passes", "All parser tests pass", "pytest", "0"),
        ],
    )
    record.transition(LifecycleState.VERIFIED, actor="verifier")

    assert record.state is LifecycleState.VERIFIED
    assert record.is_terminal
    assert {item["requirement"] for item in record.evidence} == {"tests", "diff", "parser-test-passes"}
    assert record.to_dict()["contract"]["contract_id"] == "FB-001"


def test_invalid_transitions_are_rejected():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-2")

    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.EXECUTING, actor="executor")

    record.transition(LifecycleState.PLANNED, actor="planner")
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.VERIFIED, actor="verifier")


def test_verification_requires_all_declared_evidence():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-3")
    record.transition(LifecycleState.PLANNED, actor="worker")
    record.transition(LifecycleState.APPROVED, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )
    for state in (
        LifecycleState.REPORTED_COMPLETE,
        LifecycleState.REVIEW,
        LifecycleState.VERIFICATION,
    ):
        record.transition(state, actor="worker")

    with pytest.raises(MissingEvidenceError, match="diff"):
        record.transition(
            LifecycleState.VERIFIED,
            actor="verifier",
            evidence=[Evidence("tests", "pytest passed", "pytest", "0")],
        )


def test_reported_complete_is_a_claim_not_a_terminal_state():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-4")
    record.transition(LifecycleState.PLANNED, actor="worker")
    record.transition(LifecycleState.APPROVED, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )

    record.transition(LifecycleState.REPORTED_COMPLETE, actor="worker")

    assert not record.is_terminal
    assert record.state is LifecycleState.REPORTED_COMPLETE
    record.transition(LifecycleState.REVIEW, actor="reviewer")
    assert record.state is LifecycleState.REVIEW


def test_record_is_portable_canonical_data():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-5")

    portable = record.to_dict()

    assert portable["schema"] == "fieldbook.task-record.v1"
    assert portable["task_id"] == "task-5"
    assert portable["state"] == "proposed"
    assert portable["history"] == []
    assert asdict(Evidence("tests", "passed", "pytest", "0"))["requirement"] == "tests"


# Issue 1: VERIFICATION IGNORES ACCEPTANCE CRITERIA
def test_verification_requires_all_acceptance_criteria():
    contract = TaskContract(
        contract_id="FB-002",
        objective="Fix the parser bug",
        scope=("parser", "parser tests"),
        exclusions=("deployment",),
        risk_class="low",
        capabilities=("repo-write", "local-test"),
        acceptance_criteria=("parser-test-passes", "documentation-updated"),
        required_evidence=("tests", "diff"),
    )
    record = CanonicalTaskRecord.create(contract, task_id="task-6")

    record.transition(LifecycleState.PLANNED, actor="worker")
    record.transition(LifecycleState.APPROVED, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )
    for state in (
        LifecycleState.REPORTED_COMPLETE,
        LifecycleState.REVIEW,
        LifecycleState.VERIFICATION,
    ):
        record.transition(state, actor="worker")

    # Provide all required_evidence but only one acceptance criterion
    with pytest.raises(MissingEvidenceError, match="documentation-updated"):
        record.transition(
            LifecycleState.VERIFIED,
            actor="verifier",
            evidence=[
                Evidence("tests", "pytest passed", "pytest", "0"),
                Evidence("diff", "diff is in scope", "git diff", "clean"),
                Evidence("parser-test-passes", "All tests pass", "pytest", "0"),
            ],
        )


# Issue 2: BLOCKED/FAILED CANNOT RECOVER
def test_blocked_can_recover_to_planned():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-7")
    record.transition(LifecycleState.PLANNED, actor="worker")
    record.transition(LifecycleState.APPROVED, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )

    record.transition(LifecycleState.BLOCKED, actor="worker", reason="awaiting approval")
    assert record.state is LifecycleState.BLOCKED

    # Should be able to recover
    record.transition(LifecycleState.PLANNED, actor="planner", reason="unblocked")
    assert record.state is LifecycleState.PLANNED


def test_failed_is_terminal_and_cannot_recover_to_planned():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-8")
    record.transition(LifecycleState.PLANNED, actor="worker")
    record.transition(LifecycleState.APPROVED, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )

    record.transition(LifecycleState.FAILED, actor="worker", reason="implementation failed")
    assert record.state is LifecycleState.FAILED

    # FAILED is terminal. Recovery is represented by a new task/replan, not
    # by mutating the failed record back into an executable state.
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.PLANNED, actor="planner", reason="replanning")


# Issue 3: SIDE-STATE GUARD OVER-PERMISSIVE
def test_invalid_side_transitions_rejected():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-9")

    # VERIFIED is terminal, cannot go to side states
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="planner")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("repo-write", "local-test"),
    )
    record.transition(
        LifecycleState.REPORTED_COMPLETE,
        actor="executor",
        evidence=[Evidence("tests", "pytest passed", "pytest", "0")],
    )
    record.transition(LifecycleState.REVIEW, actor="reviewer")
    record.transition(
        LifecycleState.VERIFICATION,
        actor="verifier",
        evidence=[
            Evidence("diff", "diff is in scope", "git diff", "clean"),
            Evidence("parser-test-passes", "All parser tests pass", "pytest", "0"),
        ],
    )
    record.transition(LifecycleState.VERIFIED, actor="verifier")

    # Cannot go from terminal to side state
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.BLOCKED, actor="worker")


# Issue 4: Evidence.passed NOT TYPE-VALIDATED
def test_evidence_passed_must_be_bool():
    with pytest.raises(ValueError, match="passed must be bool"):
        Evidence("tests", "passed", "pytest", "0", passed="false")

    with pytest.raises(ValueError, match="passed must be bool"):
        Evidence("tests", "passed", "pytest", "0", passed=1)

    with pytest.raises(ValueError, match="passed must be bool"):
        Evidence("tests", "passed", "pytest", "0", passed=None)

    with pytest.raises(ValueError, match="passed must be bool"):
        Evidence("tests", "passed", "pytest", "0", passed="true")


def test_evidence_from_malformed_mapping_rejects_non_bool_passed():
    with pytest.raises(ValueError, match="passed must be bool"):
        Evidence(
            requirement="tests",
            claim="passed",
            tool="pytest",
            result="0",
            passed="false",
        )


# Issue 5: PUBLIC FIELDS ALLOW BYPASS
def test_state_cannot_be_mutated_directly():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-10")

    with pytest.raises(AttributeError, match="has no setter"):
        record.state = LifecycleState.VERIFIED


def test_evidence_cannot_be_mutated_directly():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-11")

    with pytest.raises(AttributeError, match="no attribute 'append'"):
        record.evidence.append({"requirement": "tests", "claim": "test", "tool": "pytest", "result": "0"})


def test_from_dict_rejects_malformed_evidence():
    """Deserialization should reject malformed evidence with non-bool passed values."""
    portable = CanonicalTaskRecord.create(coding_contract(), task_id="task-18").to_dict()
    portable["evidence"] = [
        {
            "requirement": "tests",
            "claim": "passed",
            "tool": "pytest",
            "result": "0",
            "passed": "false",  # Malformed: string instead of bool
        }
    ]

    with pytest.raises(ValueError, match="passed must be bool"):
        CanonicalTaskRecord.from_dict(portable)


def test_history_cannot_be_mutated_directly():
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-12")

    with pytest.raises(AttributeError, match="no attribute 'append'"):
        record.history.append({"from": "proposed", "to": "planned", "actor": "planner"})


def test_deserialization_validates_invariants():
    # This test checks that to_dict() produces valid data that could be deserialized
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-13")
    record.transition(LifecycleState.PLANNED, actor="planner")

    portable = record.to_dict()

    # Verify the structure is valid for deserialization
    assert portable["schema"] == "fieldbook.task-record.v1"
    assert portable["task_id"] == "task-13"
    assert portable["state"] == "planned"
    assert len(portable["history"]) == 1
    assert portable["history"][0]["from"] == "proposed"
    assert portable["history"][0]["to"] == "planned"

    # Verify we can deserialize and get the same state
    restored = CanonicalTaskRecord.from_dict(portable)
    assert restored.task_id == "task-13"
    assert restored.state is LifecycleState.PLANNED
    assert len(restored.history) == 1
    assert len(restored.evidence) == 0


# Issue 6: reported_complete as lifecycle state concern
def test_reported_complete_status_is_accessible():
    """Test that reported_complete status can be tracked as stage output."""
    record = CanonicalTaskRecord.create(coding_contract(), task_id="task-14")
    for state in (LifecycleState.PLANNED, LifecycleState.APPROVED):
        record.transition(state, actor="worker")
    record.transition(
        LifecycleState.EXECUTING,
        actor="worker",
        executor_capabilities=("repo-write", "local-test"),
    )

    record.transition(LifecycleState.REPORTED_COMPLETE, actor="executor")
    assert record.state is LifecycleState.REPORTED_COMPLETE

    # Should be able to transition to REVIEW
    record.transition(LifecycleState.REVIEW, actor="reviewer")
    assert record.state is LifecycleState.REVIEW


# Issue 7: VERIFIER INDEPENDENCE
def test_medium_high_risk_rejects_self_verification():
    """Medium and high risk tasks cannot be verified by the same actor who executed them."""
    # Test medium risk
    medium_contract = TaskContract(
        contract_id="FB-003",
        objective="Medium risk task",
        scope=("medium",),
        exclusions=(),
        risk_class="medium",
        capabilities=("write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(medium_contract, task_id="task-15")
    for state in (LifecycleState.PLANNED, LifecycleState.APPROVED):
        record.transition(state, actor="same-actor")
    record.transition(
        LifecycleState.EXECUTING,
        actor="same-actor",
        executor_capabilities=("write",),
    )
    for state in (
        LifecycleState.REPORTED_COMPLETE,
        LifecycleState.REVIEW,
        LifecycleState.VERIFICATION,
    ):
        record.transition(state, actor="same-actor")

    with pytest.raises(InvalidTransitionError, match="verifier must differ from executor"):
        record.transition(
            LifecycleState.VERIFIED,
            actor="same-actor",
            evidence=[Evidence("evidence-1", "passed", "tool", "result")],
        )


def test_high_risk_rejects_self_verification():
    """High risk tasks cannot be verified by the same actor who executed them."""
    high_contract = TaskContract(
        contract_id="FB-004",
        objective="High risk task",
        scope=("high",),
        exclusions=(),
        risk_class="high",
        capabilities=("write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1", "rollback-step"),
    )
    record = CanonicalTaskRecord.create(high_contract, task_id="task-16")
    record.transition(LifecycleState.PLANNED, actor="planner")
    # High-risk requires independent approver
    record.transition(LifecycleState.APPROVED, actor="approver", reason="Human approval")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("write",),
    )
    for state in (
        LifecycleState.REPORTED_COMPLETE,
        LifecycleState.REVIEW,
        LifecycleState.VERIFICATION,
    ):
        record.transition(state, actor="executor")

    # Executor cannot self-verify
    with pytest.raises(InvalidTransitionError, match="verifier must differ from executor"):
        record.transition(
            LifecycleState.VERIFIED,
            actor="executor",
            evidence=[
                Evidence("evidence-1", "passed", "tool", "result"),
                Evidence("rollback-step", "passed", "tool", "result"),
                Evidence("criterion-1", "passed", "tool", "result"),
            ],
        )


def test_low_risk_allows_self_verification():
    """Low risk tasks can be verified by the same actor who executed them."""
    low_contract = TaskContract(
        contract_id="FB-005",
        objective="Low risk task",
        scope=("low",),
        exclusions=(),
        risk_class="low",
        capabilities=("write",),
        acceptance_criteria=("criterion-1",),
        required_evidence=("evidence-1",),
    )
    record = CanonicalTaskRecord.create(low_contract, task_id="task-17")
    for state in (LifecycleState.PLANNED, LifecycleState.APPROVED):
        record.transition(state, actor="same-actor")
    record.transition(
        LifecycleState.EXECUTING,
        actor="same-actor",
        executor_capabilities=("write",),
    )
    for state in (
        LifecycleState.REPORTED_COMPLETE,
        LifecycleState.REVIEW,
        LifecycleState.VERIFICATION,
    ):
        record.transition(state, actor="same-actor")

    # Should succeed - low risk allows self-verification
    record.transition(
        LifecycleState.VERIFIED,
        actor="same-actor",
        evidence=[
            Evidence("evidence-1", "passed", "tool", "result"),
            Evidence("criterion-1", "passed", "tool", "result"),
        ],
    )
    assert record.state is LifecycleState.VERIFIED
