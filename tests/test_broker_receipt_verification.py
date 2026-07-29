"""Broker-side receipt verification and replay protection tests.

Tests verify that the broker independently enforces all 10 verification rules
from the spec, including atomic replay protection and clock-skew bounds.
"""

import threading
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from unittest.mock import Mock

import pytest

from agentic_fieldbook.broker import (
    VerificationResult,
    VerificationCategory,
    KeyStore,
    ApproverPolicy,
    ApprovalStore,
    Clock,
    verify_approval_receipt,
    REPLAY_DETECTED,
    INVALID_SIGNATURE,
    UNKNOWN_ISSUER,
    AUDIENCE_MISMATCH,
    EXPIRED,
    REPLAY_DETECTED,
    ACTION_MISMATCH,
    POLICY_DENIED,
    STORE_UNAVAILABLE,
    VERIFICATION_FAILED,
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_VALIDITY_MINUTES,
    ReservationOutcome,
)
from agentic_fieldbook.contract import _strict_equal
from agentic_fieldbook.receipt import canonical_digest, signed_payload


# === Test fixtures ===

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# Valid receipt fixture (single approver)
VALID_RECEIPT = {
    "receipt_version": "1",
    "approval_request_id": "req-001",
    "decision": "approved",
    "action_digest": "sha256:" + "a" * 64,
    "contract_digest": "",
    "target": {"cluster": "example", "type": "guest", "id": "123"},
    "capability": "snapshot_guest",
    "parameters": {"snapshot": "approved"},
    "issuer": "user-001",
    "issued_at": "2025-01-01T11:55:00Z",  # 5 minutes ago (within 10 min validity)
    "valid_until": "2025-01-01T12:05:00Z",  # 5 minutes from now
    "audience": "broker-001",
    "receipt_id": "receipt-001",
    "nonce": "nonce-001",
    "signature": {
        "algorithm": "ed25519",
        "key_id": "key-001",
        "value": "valid-signature",
    },
}

# Matching contract for verification
CONTRACT = {
    "target": {"cluster": "example", "type": "guest", "id": "123"},
    "capability": "snapshot_guest",
    "parameters": {"snapshot": "approved"},
}
CONTRACT["contract_digest"] = canonical_digest({k: v for k, v in CONTRACT.items() if k != "contract_digest"})
VALID_RECEIPT["action_digest"] = canonical_digest({k: v for k, v in CONTRACT.items() if k != "contract_digest"})
VALID_RECEIPT["contract_digest"] = CONTRACT["contract_digest"]
VALID_RECEIPT["signature"]["value"] = hashlib.sha256(signed_payload(VALID_RECEIPT)).hexdigest()


# === Fake implementations for testing ===

class FakeKeyStore(KeyStore):
    """Fake key store for testing."""

    def __init__(
        self,
        valid_keys: set[str] | None = None,
        revoked_keys: set[str] | None = None,
        signature_valid: bool = True,
    ):
        self.valid_keys = valid_keys if valid_keys is not None else {"key-001", "key-002"}
        self.revoked_keys = revoked_keys if revoked_keys is not None else set()
        self.signature_valid = signature_valid

    def verify_signature(self, signature: Mapping[str, Any], payload: bytes) -> bool:
        if signature.get("key_id") in self.revoked_keys:
            return False
        if signature.get("key_id") not in self.valid_keys:
            return False
        return self.signature_valid and signature.get("value") == hashlib.sha256(payload).hexdigest()


def _resign(receipt):
    receipt = {**receipt, "signature": dict(receipt["signature"])}
    receipt["signature"]["value"] = hashlib.sha256(signed_payload(receipt)).hexdigest()
    return receipt


class FakeApproverPolicy(ApproverPolicy):
    """Fake approver policy for testing."""

    def __init__(
        self,
        authorized_approvers: dict[str, set[str]] | None = None,
        requester_authorized: bool = True,
    ):
        # Maps (capability, target_class) -> set of authorized issuers
        self.authorized_approvers = authorized_approvers if authorized_approvers is not None else {
            ("snapshot_guest", "guest"): {"user-001", "user-002"},
        }
        self.requester_authorized = requester_authorized

    def is_authorized_approver(
        self, issuer: str, capability: str, target: Mapping[str, Any]
    ) -> bool:
        # Extract target class from target mapping
        target_class = target.get("type", "")
        key = (capability, target_class)
        return issuer in self.authorized_approvers.get(key, set())

    def is_requester_authorized(self, requester: str, capability: str) -> bool:
        return self.requester_authorized


class FakeApprovalStore(ApprovalStore):
    """Fake approval store for testing."""

    def __init__(
        self,
        request_status: dict[str, str] | None = None,
        consumed_nonces: set[str] | None = None,
        consumed_receipt_ids: set[str] | None = None,
        consumed_request_ids: set[str] | None = None,
        available: bool = True,
    ):
        self.request_status = request_status or {}
        self.consumed_nonces = consumed_nonces or set()
        self.consumed_receipt_ids = consumed_receipt_ids or set()
        self.consumed_request_ids = consumed_request_ids or set()
        self.available = available

    def get_request_status(self, request_id: str) -> str | None:
        if not self.available:
            return None
        return self.request_status.get(request_id)

    def is_available(self) -> bool:
        return self.available

    def reserve_and_record_verification(self, receipt_id, nonce, request_id, timestamp):
        if not self.available or getattr(self, "fail_audit", False):
            return ReservationOutcome.AUDIT_UNAVAILABLE
        if (nonce in self.consumed_nonces or receipt_id in self.consumed_receipt_ids
                or request_id in self.consumed_request_ids):
            return ReservationOutcome.REPLAY
        self.consumed_nonces.add(nonce)
        self.consumed_receipt_ids.add(receipt_id)
        self.consumed_request_ids.add(request_id)
        self.verification_events = getattr(self, "verification_events", [])
        self.verification_events.append((receipt_id, timestamp))
        return ReservationOutcome.RESERVED

class FakeClock(Clock):
    """Fake clock for testing."""

    def __init__(self, now: datetime):
        self.now = now

    def utcnow(self) -> datetime:
        return self.now


# === Test helper functions ===

def make_result(
    success: bool = True,
    category: VerificationCategory = VERIFICATION_FAILED,
    reason: str = "",
    lease_id: str = "",
) -> VerificationResult:
    return VerificationResult(
        success=success,
        category=category,
        reason=reason,
        lease_id=lease_id,
    )


# === Tests ===

def test_valid_receipt_issues_authorization():
    """Valid signed receipt issues authorization only when ALL checks pass."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(
        request_status={"req-001": "approved"},
    )

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert result.success
    assert result.category != VERIFICATION_FAILED
    assert result.lease_id  # Lease ID is issued
    assert len(result.lease_id) > 0


def test_target_mismatch_rejected():
    """Target mismatch is rejected with no lease."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    mismatched_contract = {
        "target": {"cluster": "different", "type": "guest", "id": "123"},
        "capability": "snapshot_guest",
        "parameters": {"snapshot": "approved"},
    }

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=mismatched_contract,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_capability_mismatch_rejected():
    """Capability mismatch is rejected with no lease."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    mismatched_contract = {
        "target": {"cluster": "example", "type": "guest", "id": "123"},
        "capability": "delete_guest",  # Different capability
        "parameters": {"snapshot": "approved"},
    }

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=mismatched_contract,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_parameters_mismatch_rejected():
    """Parameters mismatch is rejected with no lease."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    mismatched_contract = {
        "target": {"cluster": "example", "type": "guest", "id": "123"},
        "capability": "snapshot_guest",
        "parameters": {"snapshot": "different"},  # Different parameter value
    }

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=mismatched_contract,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_action_digest_substitution_rejected_before_replay_reservation():
    receipt = _resign({**VALID_RECEIPT, "action_digest": "sha256:" + "b" * 64})
    store = FakeApprovalStore(request_status={"req-001": "approved"})
    result = verify_approval_receipt(receipt, CONTRACT, "broker-001", "requester-001",
                                     FakeKeyStore(), FakeApproverPolicy(), store, FakeClock(NOW))
    assert not result.success
    assert result.category == ACTION_MISMATCH
    assert not store.consumed_nonces


def test_action_digest_binds_complete_fieldbook_action_package():
    contract = {
        **CONTRACT,
        "lease_ttl": 300,
        "operation_limit": 1,
        "verification_method": "direct-query",
        "rollback": {"required": True},
        "abort_conditions": ["verification-fails"],
        "approval_expires_at": "2025-01-01T12:10:00Z",
    }
    contract.pop("contract_digest", None)
    contract["contract_digest"] = canonical_digest(contract)
    receipt = _resign({**VALID_RECEIPT, "contract_digest": contract["contract_digest"], "action_digest": canonical_digest({k: v for k, v in contract.items() if k != "contract_digest"})})
    result = verify_approval_receipt(
        receipt, contract, "broker-001", "requester-001", FakeKeyStore(),
        FakeApproverPolicy(), FakeApprovalStore(request_status={"req-001": "approved"}),
        FakeClock(NOW),
    )
    assert result.success

    changed = {**contract, "operation_limit": 2}
    changed_result = verify_approval_receipt(
        receipt, changed, "broker-001", "requester-001", FakeKeyStore(),
        FakeApproverPolicy(), FakeApprovalStore(request_status={"req-001": "approved"}),
        FakeClock(NOW),
    )
    assert changed_result.category == ACTION_MISMATCH


def test_signature_is_payload_sensitive():
    altered = {**VALID_RECEIPT, "capability": "delete_guest"}
    result = verify_approval_receipt(altered, CONTRACT, "broker-001", "requester-001",
                                     FakeKeyStore(), FakeApproverPolicy(),
                                     FakeApprovalStore(request_status={"req-001": "approved"}), FakeClock(NOW))
    assert not result.success
    assert result.category == INVALID_SIGNATURE


def test_audit_failure_does_not_strand_replay_reservation_and_retry_succeeds():
    store = FakeApprovalStore(request_status={"req-001": "approved"})
    store.fail_audit = True
    first = verify_approval_receipt(VALID_RECEIPT, CONTRACT, "broker-001", "requester-001",
                                    FakeKeyStore(), FakeApproverPolicy(), store, FakeClock(NOW))
    assert not first.success
    assert first.category == STORE_UNAVAILABLE
    assert not store.consumed_nonces
    store.fail_audit = False
    second = verify_approval_receipt(VALID_RECEIPT, CONTRACT, "broker-001", "requester-001",
                                     FakeKeyStore(), FakeApproverPolicy(), store, FakeClock(NOW))
    assert second.success


def test_duplicate_durable_verification_is_idempotent():
    store = FakeApprovalStore(request_status={"req-001": "approved"})
    assert store.reserve_and_record_verification("receipt-001", "nonce-001", "req-001", NOW) is ReservationOutcome.RESERVED
    assert store.reserve_and_record_verification("receipt-001", "nonce-001", "req-001", NOW) is ReservationOutcome.REPLAY
    assert len(store.verification_events) == 1


def test_audience_mismatch_rejected():
    """Audience mismatch is rejected with no lease."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-different",  # Different audience
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == AUDIENCE_MISMATCH


def test_boolean_integer_substitution_rejected():
    """Boolean/integer substitution is rejected in nested structures."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    # Receipt has boolean True
    receipt_with_bool = _resign({
        **VALID_RECEIPT,
        "parameters": {"flag": True},
    })

    # Contract has integer 1 (type confusion attack)
    contract_with_int = {
        "target": {"cluster": "example", "type": "guest", "id": "123"},
        "capability": "snapshot_guest",
        "parameters": {"flag": 1},
    }

    result = verify_approval_receipt(
        receipt=receipt_with_bool,
        contract=contract_with_int,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_integer_float_substitution_rejected():
    """Integer/float substitution is rejected in nested structures."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    # Receipt has integer
    receipt_with_int = _resign({
        **VALID_RECEIPT,
        "parameters": {"count": 1},
    })

    # Contract has float (type confusion attack)
    contract_with_float = {
        "target": {"cluster": "example", "type": "guest", "id": "123"},
        "capability": "snapshot_guest",
        "parameters": {"count": 1.0},
    }

    result = verify_approval_receipt(
        receipt=receipt_with_int,
        contract=contract_with_float,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_nested_type_confusion_rejected():
    """Type confusion in nested mappings and lists is rejected."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    # Receipt with nested structure
    receipt_nested = _resign({
        **VALID_RECEIPT,
        "parameters": {
            "nested": {"items": [True, False, True]},
        },
    })

    # Contract with integer substitution in list
    contract_nested = {
        "target": {"cluster": "example", "type": "guest", "id": "123"},
        "capability": "snapshot_guest",
        "parameters": {
            "nested": {"items": [1, 0, 1]},  # Integers instead of booleans
        },
    }

    result = verify_approval_receipt(
        receipt=receipt_nested,
        contract=contract_nested,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == ACTION_MISMATCH


def test_unknown_key_fails_closed():
    """Unknown issuer key fails closed."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore(valid_keys=set())  # No valid keys
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == INVALID_SIGNATURE


def test_revoked_key_fails_closed():
    """Revoked issuer key fails closed."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore(revoked_keys={"key-001"})
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == INVALID_SIGNATURE


def test_invalid_signature_fails_closed():
    """Invalid signature fails closed."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore(signature_valid=False)
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == INVALID_SIGNATURE


def test_unknown_issuer_fails_closed():
    """Unknown issuer fails closed."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy(authorized_approvers={})  # No authorized approvers
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == UNKNOWN_ISSUER


def test_nonce_replay_rejected():
    """Nonce replay is rejected atomically."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(
        request_status={"req-001": "approved"},
        consumed_nonces={"nonce-001"},  # Already consumed
    )

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == REPLAY_DETECTED


def test_receipt_id_replay_rejected():
    """Receipt ID replay is rejected atomically."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(
        request_status={"req-001": "approved"},
        consumed_receipt_ids={"receipt-001"},  # Already consumed
    )

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == REPLAY_DETECTED


def test_approval_request_id_replay_rejected():
    """Approval request ID replay is rejected (one-time mandatory)."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(
        request_status={"req-001": "approved"},
        consumed_request_ids={"req-001"},  # Already authorized a lease
    )

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == REPLAY_DETECTED


def test_concurrent_replay_rejected_atomically():
    """Concurrent replay attempts fail for all but one."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    results = []
    errors = []

    def verify_once():
        try:
            result = verify_approval_receipt(
                receipt=VALID_RECEIPT,
                contract=CONTRACT,
                broker_audience="broker-001",
                requester="requester-001",
                keystore=keystore,
                policy=policy,
                store=store,
                clock=clock,
                clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
            )
            results.append(result)
        except Exception as e:
            errors.append(e)

    # Launch 5 concurrent verifications
    threads = [threading.Thread(target=verify_once) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # At most one should succeed, others should fail with REPLAY_DETECTED
    success_count = sum(1 for r in results if r.success)
    replay_count = sum(1 for r in results if not r.success and r.category == REPLAY_DETECTED)

    assert success_count <= 1, "At most one verification should succeed"
    assert replay_count >= 4, "All other attempts should detect replay"
    assert len(errors) == 0, "No exceptions should be raised"


def test_store_unavailable_fails_closed():
    """Approval store unavailable fails closed."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(available=False)

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == STORE_UNAVAILABLE


def test_verification_records_event():
    """Verification records a durable receipt-verification event."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})


    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert result.success
    assert store.verification_events == [("receipt-001", NOW)]


def test_expired_receipt_rejected():
    """Expired receipt (outside validity window) is rejected."""
    # Receipt issued 20 minutes ago, expired 10 minutes ago
    expired_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T11:40:00Z",
        "valid_until": "2025-01-01T11:50:00Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=expired_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == EXPIRED


def test_future_dated_receipt_rejected():
    """Future-dated receipt beyond skew bound is rejected."""
    # Receipt issued 1 minute in the future (beyond 30s skew)
    future_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T12:01:00Z",
        "valid_until": "2025-01-01T12:11:00Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=future_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == EXPIRED


def test_clock_skew_boundary_lower_accepted():
    """Receipt issued exactly 30s in the future is accepted (at skew boundary)."""
    # issued_at is 30s in the future: now == issued_at - skew (boundary accepted)
    boundary_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T12:00:30Z",
        "valid_until": "2025-01-01T12:10:30Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=boundary_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert result.success


def test_clock_skew_boundary_upper_accepted():
    """Receipt that expired exactly 30s ago is accepted (at skew boundary)."""
    # valid_until is 30s in the past: now == valid_until + skew (boundary accepted)
    boundary_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T11:49:30Z",
        "valid_until": "2025-01-01T11:59:30Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=boundary_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert result.success


def test_clock_skew_boundary_lower_rejected():
    """Receipt issued 31s in the future is rejected (1s beyond skew bound)."""
    # issued_at is 31s in the future: now < issued_at - skew (rejected)
    boundary_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T12:00:31Z",
        "valid_until": "2025-01-01T12:10:31Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=boundary_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == EXPIRED


def test_clock_skew_boundary_upper_rejected():
    """Receipt that expired 31s ago is rejected (1s beyond skew bound)."""
    # valid_until is 31s in the past: now > valid_until + skew (rejected)
    boundary_receipt = _resign({
        **VALID_RECEIPT,
        "issued_at": "2025-01-01T11:49:29Z",
        "valid_until": "2025-01-01T11:59:29Z",
    })

    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=boundary_receipt,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == EXPIRED


def test_requester_policy_denied():
    """Requester without authorization fails even with human approval."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy(requester_authorized=False)
    store = FakeApprovalStore(request_status={"req-001": "approved"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success
    assert result.category == POLICY_DENIED


def test_pending_request_approved():
    """Request with pending/approved status is accepted."""
    for status in ("pending", "approved"):
        clock = FakeClock(NOW)
        keystore = FakeKeyStore()
        policy = FakeApproverPolicy()
        store = FakeApprovalStore(request_status={"req-001": status})

        result = verify_approval_receipt(
            receipt=VALID_RECEIPT,
            contract=CONTRACT,
            broker_audience="broker-001",
            requester="requester-001",
            keystore=keystore,
            policy=policy,
            store=store,
            clock=clock,
            clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
        )

        assert result.success


def test_rejected_request_denied():
    """Request with rejected status is denied."""
    clock = FakeClock(NOW)
    keystore = FakeKeyStore()
    policy = FakeApproverPolicy()
    store = FakeApprovalStore(request_status={"req-001": "rejected"})

    result = verify_approval_receipt(
        receipt=VALID_RECEIPT,
        contract=CONTRACT,
        broker_audience="broker-001",
        requester="requester-001",
        keystore=keystore,
        policy=policy,
        store=store,
        clock=clock,
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )

    assert not result.success