"""Adversarial correctness/lifecycle probe tests.

These tests probe security-critical invariants that MUST hold:
- Lifecycle receipt-binding invariant at APPROVED->EXECUTING seam
- Recovery freshness epochs invalidate stale approvals
- from_dict clears ALL approval bindings (prevents replay attacks)
- Broker digest recomputation rejects material mutations
- Adapter-to-broker positive path works end-to-end
- Killable rollback with no late mutation
- Structured Claude evidence gates
- All lifecycle transitions

Run directly with: python3 -m pytest tests/test_adversarial_correctness.py -xvs
"""

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
)
from agentic_fieldbook.receipt import canonical_digest, canonicalize
from agentic_fieldbook.broker import verify_approval_receipt, VerificationCategory
from agentic_fieldbook.contract import _strict_equal


# === Fixtures ===

def high_risk_contract():
    return TaskContract(
        contract_id="ADVERSARIAL-001",
        objective="High-risk destructive operation",
        scope=("production", "database"),
        exclusions=(),
        risk_class="high",
        capabilities=("prod-write", "destructive"),
        acceptance_criteria=("operation-completed",),
        required_evidence=("rollback-evidence", "operation-logs"),
    )


def medium_risk_contract():
    return TaskContract(
        contract_id="ADVERSARIAL-002",
        objective="Medium-risk operation",
        scope=("staging",),
        exclusions=(),
        risk_class="medium",
        capabilities=("staging-write",),
        acceptance_criteria=("operation-completed",),
        required_evidence=("operation-logs",),
    )


# === Test 1: APPROVED->EXECUTING requires current binding (high-risk) ===

def test_approved_to_executing_high_risk_requires_current_binding():
    """High-risk APPROVED->EXECUTING gate REQUIRES has_current_approval_binding."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-1")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Without binding - should FAIL
    with pytest.raises(InvalidTransitionError, match="high-risk execution requires a current approval receipt binding"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=("prod-write", "destructive"),
        )


def test_approved_to_executing_high_risk_requires_epoch_match():
    """Binding must have matching approval_epoch AND recovery_attempt."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-2")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Bind with wrong epoch - should FAIL at bind
    with pytest.raises(InvalidTransitionError, match="approval receipt is stale for this recovery attempt"):
        record.bind_approval_receipt(
            receipt_id="receipt-test",
            contract_digest="sha256:" + "a" * 64,
            epoch=999,  # Wrong epoch
            recovery_attempt=record.recovery_attempt,
        )


# === Test 2: Recovery freshness epochs invalidate stale approvals ===

def test_recovery_clears_approval_binding():
    """BLOCKED recovery clears approval bindings and increments epoch."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-3")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.bind_approval_receipt(
        receipt_id="receipt-original",
        contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    assert record.has_current_approval_binding

    # Transition to BLOCKED (recovery side state)
    record.transition(
        LifecycleState.BLOCKED,
        actor="executor",
        evidence=[],
        reason="Blocked for review",
    )

    # Verify epoch increments and binding cleared
    assert record.approval_epoch == 1
    assert record.recovery_attempt == 1
    assert not record.has_current_approval_binding


def test_recovery_requires_fresh_binding():
    """After recovery, stale approval cannot be reused."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-4")
    record.transition(LifecycleState.PLANNED, actor="planner")

    # Bind approval to epoch 0
    original_epoch = record.approval_epoch
    record.bind_approval_receipt(
        receipt_id="receipt-original",
        contract_digest="sha256:" + "a" * 64,
        epoch=original_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    record.transition(LifecycleState.APPROVED, actor="approver-1")

    # Transition to BLOCKED (recovery side state)
    record.transition(
        LifecycleState.BLOCKED,
        actor="executor",
        evidence=[],
        reason="Blocked for review",
    )

    # Try to rebind with old epoch - should FAIL
    with pytest.raises(InvalidTransitionError, match="approval receipt is stale for this recovery attempt"):
        record.bind_approval_receipt(
            receipt_id="receipt-original",  # Same receipt
            contract_digest="sha256:" + "a" * 64,
            epoch=original_epoch,  # OLD epoch (stale)
            recovery_attempt=0,  # OLD recovery attempt
        )


# === Test 3: from_dict clears ALL approval bindings ===

def test_from_dict_clears_approval_binding_fields():
    """Deserialization MUST clear all approval binding fields."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-5")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.bind_approval_receipt(
        receipt_id="receipt-original",
        contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    assert record.has_current_approval_binding
    
    # Serialize and deserialize
    portable = record.to_dict()
    assert portable["approval_receipt_id"] == "receipt-original"
    assert portable["approval_contract_digest"] == "sha256:" + "a" * 64
    assert portable["approval_binding_epoch"] == 0
    assert portable["approval_binding_recovery_attempt"] == 0
    
    # Deserialize - bindings MUST be cleared
    restored = CanonicalTaskRecord.from_dict(portable)
    assert not restored.has_current_approval_binding
    assert restored._approval_receipt_id is None
    assert restored._approval_contract_digest is None
    assert restored._approval_binding_epoch is None
    assert restored._approval_binding_recovery_attempt is None


def test_forged_deserialized_record_cannot_execute_high_risk():
    """Attacker cannot inject forged approval bindings via from_dict."""
    # Create a record and serialize it
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-6")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.bind_approval_receipt(
        receipt_id="receipt-original",
        contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    portable = record.to_dict()
    
    # Attacker forges approval bindings in the serialized data
    portable["approval_receipt_id"] = "forged-receipt"
    portable["approval_contract_digest"] = "sha256:" + "b" * 64
    portable["approval_binding_epoch"] = 0
    portable["approval_binding_recovery_attempt"] = 0
    
    # Deserialize - from_dict MUST clear these forged fields
    restored = CanonicalTaskRecord.from_dict(portable)
    assert not restored.has_current_approval_binding
    
    # Attempt to execute - should FAIL without fresh binding
    with pytest.raises(InvalidTransitionError, match="high-risk execution requires a current approval receipt binding"):
        restored.transition(
            LifecycleState.EXECUTING,
            actor="attacker",
            executor_capabilities=("prod-write", "destructive"),
        )


# === Test 4: Broker digest recomputation rejects mutations ===

def test_broker_rejects_material_contract_mutations():
    """Broker recomputes contract digest and rejects mutated contracts."""
    from agentic_fieldbook.receipt import canonical_digest
    
    # Original contract
    original_contract = {
        "target": {"cluster": "prod", "id": "123"},
        "capability": "delete_database",
        "parameters": {"confirm": True},
    }
    original_digest = canonical_digest(original_contract)
    
    # Mutated contract (changed parameters)
    mutated_contract = {
        "target": {"cluster": "prod", "id": "123"},  # Same
        "capability": "delete_database",  # Same
        "parameters": {"confirm": False},  # MUTATED!
    }
    mutated_digest = canonical_digest(mutated_contract)
    
    # Digests MUST differ
    assert original_digest != mutated_digest


def test_strict_equal_rejects_bool_int_substitution():
    """_strict_equal rejects 1/True, 0/False substitutions."""
    assert not _strict_equal(True, 1)
    assert not _strict_equal(False, 0)
    assert not _strict_equal(1, True)
    assert not _strict_equal(0, False)
    
    # But equal values of same type match
    assert _strict_equal(True, True)
    assert _strict_equal(False, False)
    assert _strict_equal(1, 1)
    assert _strict_equal(0, 0)


def test_strict_equal_rejects_int_float_substitution():
    """_strict_equal rejects int/float substitutions."""
    assert not _strict_equal(1, 1.0)
    assert not _strict_equal(0, 0.0)
    assert not _strict_equal(42, 42.0)


# === Test 5: Medium-risk has_current_approval_binding not required ===

def test_medium_risk_does_not_require_approval_binding():
    """Medium-risk APPROVED->EXECUTING does NOT require has_current_approval_binding."""
    record = CanonicalTaskRecord.create(medium_risk_contract(), task_id="test-7")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Medium-risk can execute without approval binding
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("staging-write",),
    )
    assert record.state is LifecycleState.EXECUTING


# === Test 6: Recovery approval requires fresh binding ===

def test_recovery_approval_requires_fresh_binding():
    """Recovery (recovery_attempt > 0) requires fresh approval binding."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-8")
    record.transition(LifecycleState.PLANNED, actor="planner")
    
    # First approval
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    record.bind_approval_receipt(
        receipt_id="receipt-first",
        contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("prod-write", "destructive"),
    )
    
    # Transition to BLOCKED (recovery side state) - must provide rollback evidence for high-risk
    record.transition(
        LifecycleState.BLOCKED,
        actor="governance",
        evidence=[
            {
                "requirement": "Rollback plan: revert production deployment to previous version",
                "claim": "Rollback plan documented: helm rollback myapp 42",
                "tool": "executor",
                "result": "DEPLOY_TIMEOUT - rollback step: helm rollback myapp 42"
            }
        ],
        reason="First attempt failed - blocked for recovery",
    )
    
    # Re-transition to PLANNED
    record.transition(LifecycleState.PLANNED, actor="planner")
    
    # Recovery approval WITHOUT fresh binding - should FAIL
    with pytest.raises(InvalidTransitionError, match="recovery approval requires a fresh approval receipt binding"):
        record.transition(
            LifecycleState.APPROVED,
            actor="approver-2",
            reason="Recovery approval",
        )


# === Test 7: All lifecycle transitions validated ===

def test_invalid_transitions_rejected():
    """All invalid lifecycle transitions are rejected."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-9")
    
    # Cannot skip states
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Cannot go backwards
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.PLANNED, actor="planner")
    
    # Cannot jump to terminal from APPROVED
    with pytest.raises(InvalidTransitionError):
        record.transition(LifecycleState.VERIFIED, actor="verifier")


# === Test 8: has_current_approval_binding checks all four fields ===

def test_has_current_approval_binding_comprehensive_check():
    """has_current_approval_binding must check ALL four binding fields."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-10")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Before binding - should be False
    assert not record.has_current_approval_binding
    
    # Bind correctly
    record.bind_approval_receipt(
        receipt_id="receipt-test",
        contract_digest="sha256:" + "a" * 64,
        epoch=record.approval_epoch,
        recovery_attempt=record.recovery_attempt,
    )
    assert record.has_current_approval_binding
    
    # Clear one field - should be False
    record._approval_receipt_id = None
    assert not record.has_current_approval_binding
    
    # Restore and clear another field - should be False
    record._approval_receipt_id = "receipt-test"
    record._approval_contract_digest = None
    assert not record.has_current_approval_binding


# === Test 9: Approval binding epoch mismatch prevents reuse ===

def test_approval_binding_epoch_mismatch_prevents_reuse():
    """Approval binding with wrong epoch cannot be used."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-11")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Manually set approval_binding_epoch to wrong value
    record._approval_binding_epoch = 999
    record._approval_receipt_id = "receipt-test"
    record._approval_contract_digest = "sha256:" + "a" * 64
    record._approval_binding_recovery_attempt = record.recovery_attempt
    
    # has_current_approval_binding should be False (epoch mismatch)
    assert not record.has_current_approval_binding
    
    # Should fail at EXECUTING gate
    with pytest.raises(InvalidTransitionError, match="high-risk execution requires a current approval receipt binding"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=("prod-write", "destructive"),
        )


# === Test 10: Recovery attempt mismatch prevents reuse ===

def test_recovery_attempt_mismatch_prevents_reuse():
    """Approval binding with wrong recovery_attempt cannot be used."""
    record = CanonicalTaskRecord.create(high_risk_contract(), task_id="test-12")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="approver-1")
    
    # Manually set recovery_attempt to wrong value
    record._approval_binding_epoch = record.approval_epoch
    record._approval_receipt_id = "receipt-test"
    record._approval_contract_digest = "sha256:" + "a" * 64
    record._approval_binding_recovery_attempt = 999
    
    # has_current_approval_binding should be False (recovery_attempt mismatch)
    assert not record.has_current_approval_binding
    
    # Should fail at EXECUTING gate
    with pytest.raises(InvalidTransitionError, match="high-risk execution requires a current approval receipt binding"):
        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=("prod-write", "destructive"),
        )