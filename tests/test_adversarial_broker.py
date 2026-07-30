"""Adversarial broker verification and adapter probes.

Tests for:
- Broker digest recomputation rejects material mutations
- Adapter-to-broker positive path works end-to-end
- Contract canonicalization reproducibility
- Type-safety in canonicalization (bool/int, int/float)
"""

import pytest
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping
from unittest.mock import Mock

from agentic_fieldbook.broker import (
    verify_approval_receipt,
    KeyStore,
    ApproverPolicy,
    ApprovalStore,
    Clock,
    DEFAULT_CLOCK_SKEW_SECONDS,
)
from agentic_fieldbook.receipt import (
    canonical_digest,
    canonicalize,
    signed_payload,
    loads_receipt,
    DuplicateKeyLoader,
)
from agentic_fieldbook.contract import (
    canonical_contract_projection,
    _strict_equal,
    _valid_target_identity,
)


# === Fixtures ===

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

def make_valid_receipt(
    receipt_id="test-receipt-001",
    approval_request_id="req-001",
    target=None,
    capability="test_capability",
    parameters=None,
    contract_digest=None,
    action_digest=None,
    lease_ttl=300,
    operation_limit=1,
) -> dict[str, Any]:
    """Create a valid receipt fixture for testing."""
    if target is None:
        target = {"cluster": "test", "id": "123"}
    if parameters is None:
        parameters = {"confirm": True}

    # Build the full contract projection the broker will see
    full_contract = {
        "target": target,
        "capability": capability,
        "parameters": parameters,
        "lease_ttl": lease_ttl,
        "operation_limit": operation_limit,
    }

    # Compute digests using the same projections the broker uses
    if contract_digest is None:
        contract_projection = canonical_contract_projection(full_contract)
        contract_digest = canonical_digest(contract_projection)
    if action_digest is None:
        # action_digest = canonical action projection (same fields minus declarations)
        action_projection = {k: v for k, v in full_contract.items()
                             if k not in {"contract_digest", "action_digest"}}
        action_digest = canonical_digest(action_projection)
    
    receipt = {
        "receipt_version": "1",
        "approval_request_id": approval_request_id,
        "decision": "approved",
        "action_digest": action_digest,
        "contract_digest": contract_digest,
        "target": target,
        "capability": capability,
        "parameters": parameters,
        "issuer": "approver-001",
        "issued_at": (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (NOW + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audience": "test-broker",
        "receipt_id": receipt_id,
        "nonce": "nonce-001",
        "signature": {
            "algorithm": "ed25519",
            "key_id": "key-001",
            "value": hashlib.sha256(signed_payload({
                "receipt_version": "1",
                "approval_request_id": approval_request_id,
                "decision": "approved",
                "action_digest": action_digest,
                "contract_digest": contract_digest,
                "target": target,
                "capability": capability,
                "parameters": parameters,
                "issuer": "approver-001",
                "issued_at": (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "valid_until": (NOW + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "audience": "test-broker",
                "receipt_id": receipt_id,
                "nonce": "nonce-001",
                "signature": {"algorithm": "ed25519", "key_id": "key-001"},
            })).hexdigest(),
        },
    }
    return receipt


class FakeKeyStore(KeyStore):
    """Fake keystore that always validates signature."""
    
    def verify_signature(self, signature: Mapping[str, Any], payload: bytes) -> bool:
        return True


class FakeApproverPolicy(ApproverPolicy):
    """Fake policy that always authorizes."""
    
    def is_authorized_approver(self, issuer: str, capability: str, target: Mapping[str, Any]) -> bool:
        return True
    
    def is_requester_authorized(self, requester: str, capability: str) -> bool:
        return True


class FakeApprovalStore(ApprovalStore):
    """Fake store that tracks reservations."""
    
    def __init__(self, requests: dict[str, str] | None = None):
        self.requests = requests or {"req-001": "approved"}
        self.reserved_receipts = set()
        self.audit_log = []
    
    def is_available(self) -> bool:
        return True
    
    def get_request_status(self, request_id: str) -> str | None:
        return self.requests.get(request_id)
    
    def reserve_and_record_verification(
        self, receipt_id: str, nonce: str, request_id: str, timestamp: datetime
    ):
        if (receipt_id, nonce) in self.reserved_receipts:
            from agentic_fieldbook.broker import ReservationOutcome
            return ReservationOutcome.REPLAY
        self.reserved_receipts.add((receipt_id, nonce))
        self.audit_log.append({
            "receipt_id": receipt_id,
            "nonce": nonce,
            "request_id": request_id,
            "timestamp": timestamp.isoformat(),
        })
        from agentic_fieldbook.broker import ReservationOutcome
        return ReservationOutcome.RESERVED
    
    def reserve_and_record_lease(
        self, receipt_id: str, nonce: str, request_id: str,
        action_digest: str, target: Mapping[str, Any],
        capability: str, parameters: Mapping[str, Any],
        issued_at: datetime, expires_at: datetime,
        operation_limit: int,
    ):
        if (receipt_id, nonce) in self.reserved_receipts:
            from agentic_fieldbook.broker import ReservationOutcome
            return ReservationOutcome.REPLAY
        self.reserved_receipts.add((receipt_id, nonce))
        self.audit_log.append({
            "receipt_id": receipt_id,
            "nonce": nonce,
            "request_id": request_id,
            "action_digest": action_digest,
            "target": target,
            "capability": capability,
            "parameters": parameters,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "operation_limit": operation_limit,
        })
        from agentic_fieldbook.broker import ReservationOutcome
        return ReservationOutcome.COMMITTED


class FakeClock(Clock):
    """Fake clock that returns NOW."""
    
    def utcnow(self) -> datetime:
        return NOW


# === Test 1: Broker rejects mutated contract ===

def test_broker_rejects_mutated_contract_parameters():
    """Broker recomputes contract digest and rejects parameter mutations."""
    # Create valid receipt and contract
    original_parameters = {"confirm": True, "mode": "safe"}
    receipt = make_valid_receipt(parameters=original_parameters)

    # Build valid contract matching the receipt
    full_contract = {
        "target": receipt["target"],
        "capability": receipt["capability"],
        "parameters": original_parameters,
        "lease_ttl": 300,
        "operation_limit": 1,
    }
    full_contract["contract_digest"] = receipt["contract_digest"]

    # Mutate parameters in submitted contract
    mutated_parameters = {"confirm": False, "mode": "safe"}  # Changed confirm to False
    mutated_contract = dict(full_contract)
    mutated_contract["parameters"] = mutated_parameters

    # Verify should FAIL due to digest mismatch
    result = verify_approval_receipt(
        receipt=receipt,
        contract=mutated_contract,
        broker_audience="test-broker",
        requester="requester-001",
        keystore=FakeKeyStore(),
        policy=FakeApproverPolicy(),
        store=FakeApprovalStore(),
        clock=FakeClock(),
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )
    
    assert not result.success
    assert result.category.name == "ACTION_MISMATCH"
    assert "parameter" in result.reason.lower() or "action" in result.reason.lower() or "contract" in result.reason.lower()


def test_broker_rejects_mutated_contract_target():
    """Broker recomputes contract digest and rejects target mutations."""
    # Create valid receipt
    original_target = {"cluster": "prod", "id": "123"}
    receipt = make_valid_receipt(target=original_target)

    # Build valid contract matching the receipt
    full_contract = {
        "target": original_target,
        "capability": receipt["capability"],
        "parameters": receipt["parameters"],
        "lease_ttl": 300,
        "operation_limit": 1,
    }
    full_contract["contract_digest"] = receipt["contract_digest"]

    # Mutate target in submitted contract
    mutated_target = {"cluster": "prod", "id": "999"}  # Different ID
    mutated_contract = dict(full_contract)
    mutated_contract["target"] = mutated_target
    
    # Verify should FAIL due to target mismatch
    result = verify_approval_receipt(
        receipt=receipt,
        contract=mutated_contract,
        broker_audience="test-broker",
        requester="requester-001",
        keystore=FakeKeyStore(),
        policy=FakeApproverPolicy(),
        store=FakeApprovalStore(),
        clock=FakeClock(),
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )
    
    assert not result.success
    assert result.category.name == "ACTION_MISMATCH"
    assert "target" in result.reason.lower() or "action" in result.reason.lower() or "contract" in result.reason.lower()


def test_broker_rejects_mutated_contract_capability():
    """Broker recomputes contract digest and rejects capability mutations."""
    # Create valid receipt
    receipt = make_valid_receipt(capability="read_database")

    # Build valid contract matching the receipt
    full_contract = {
        "target": receipt["target"],
        "capability": "read_database",
        "parameters": receipt["parameters"],
        "lease_ttl": 300,
        "operation_limit": 1,
    }
    full_contract["contract_digest"] = receipt["contract_digest"]

    # Mutate capability in submitted contract
    mutated_contract = dict(full_contract)
    mutated_contract["capability"] = "delete_database"  # Different capability!
    
    # Verify should FAIL due to capability mismatch
    result = verify_approval_receipt(
        receipt=receipt,
        contract=mutated_contract,
        broker_audience="test-broker",
        requester="requester-001",
        keystore=FakeKeyStore(),
        policy=FakeApproverPolicy(),
        store=FakeApprovalStore(),
        clock=FakeClock(),
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )
    
    assert not result.success
    assert result.category.name == "ACTION_MISMATCH"
    assert "capability" in result.reason.lower() or "action" in result.reason.lower() or "contract" in result.reason.lower()


# === Test 2: Adapter-to-broker positive path ===

def test_adapter_to_broker_positive_path():
    """End-to-end: adapter constructs receipt, broker verifies and issues lease."""
    # 1. Adapter constructs a valid approval receipt
    receipt = make_valid_receipt(
        receipt_id="adapter-receipt-001",
        approval_request_id="adapter-req-001",
        target={"service": "api", "region": "us-east-1"},
        capability="deploy_service",
        parameters={"version": "v2.3.4"},
        lease_ttl=600,
        operation_limit=10,
    )

    # 2. Adapter constructs matching contract
    contract = {
        "target": receipt["target"],
        "capability": receipt["capability"],
        "parameters": receipt["parameters"],
        "lease_ttl": 600,
        "operation_limit": 10,
    }
    contract["contract_digest"] = receipt["contract_digest"]
    
    # 3. Broker verifies receipt (store must have the approval request status)
    store = FakeApprovalStore(
        requests={receipt["approval_request_id"]: "approved"}
    )
    result = verify_approval_receipt(
        receipt=receipt,
        contract=contract,
        broker_audience="test-broker",
        requester="adapter-requester",
        keystore=FakeKeyStore(),
        policy=FakeApproverPolicy(),
        store=store,
        clock=FakeClock(),
        clock_skew_seconds=DEFAULT_CLOCK_SKEW_SECONDS,
    )
    
    # 4. Verification should succeed and issue a lease
    assert result.success
    assert result.category.name == "VERIFIED"
    assert result.lease_id
    assert result.receipt_id == receipt["receipt_id"]
    assert result.action_digest == receipt["action_digest"]


# === Test 3: Contract canonicalization reproducibility ===

def test_canonicalization_is_reproducible():
    """Canonicalization produces identical output for identical inputs."""
    value = {
        "z_key": "last",
        "a_key": "first",
        "m_key": {"nested": True, "list": [3, 1, 2]},
    }
    
    canonical1 = canonicalize(value)
    canonical2 = canonicalize(value)
    
    # Must be byte-for-byte identical
    assert canonical1 == canonical2


def test_canonicalization_sorts_keys():
    """Canonicalization sorts mapping keys lexicographically."""
    value = {
        "z_key": "z_value",
        "a_key": "a_value",
        "m_key": "m_value",
    }
    
    canonical = canonicalize(value)
    
    # Keys must appear in sorted order
    assert "a_key" in canonical
    pos_a = canonical.index("a_key")
    pos_m = canonical.index("m_key")
    pos_z = canonical.index("z_key")
    assert pos_a < pos_m < pos_z


def test_canonicalization_preserves_list_order():
    """Canonicalization preserves list order (semantically significant)."""
    value = {
        "list": ["third", "first", "second"],
    }
    
    canonical = canonicalize(value)
    
    # List order must be preserved
    assert "third" in canonical
    assert "first" in canonical
    assert "second" in canonical
    # Verify order by checking positions
    pos_third = canonical.index("third")
    pos_first = canonical.index("first")
    pos_second = canonical.index("second")
    assert pos_third < pos_first < pos_second


# === Test 4: Type-safety in canonicalization ===

def test_canonicalization_preserves_boolean_type():
    """Canonicalization preserves boolean type (not converted to int)."""
    value_true = {"flag": True}
    value_int_one = {"flag": 1}
    
    canonical_true = canonicalize(value_true)
    canonical_int = canonicalize(value_int_one)
    
    # Must produce different output
    assert canonical_true != canonical_int
    # Boolean should serialize as true/false (JSON)
    assert "true" in canonical_true
    assert "false" not in canonical_true
    # Integer should serialize as 1
    assert ":1}" in canonical_int or '"flag":1' in canonical_int


def test_canonicalization_preserves_integer_type():
    """Canonicalization preserves integer type (not converted to float)."""
    value_int = {"count": 42}
    value_float = {"count": 42.0}
    
    canonical_int = canonicalize(value_int)
    canonical_float = canonicalize(value_float)
    
    # Must produce different output
    assert canonical_int != canonical_float
    # Integer should not have decimal point
    assert "42.0" not in canonical_int or "42}" in canonical_int
    # Float should have decimal point or exponent
    assert "42.0" in canonical_float or "42e" in canonical_float


# === Test 5: Digest correctness ===

def test_digest_format_is_correct():
    """Digest format is 'sha256:<64 hex characters>'."""
    value = {"test": "data"}
    digest = canonical_digest(value)
    
    assert digest.startswith("sha256:")
    hex_part = digest[7:]  # Remove "sha256:" prefix
    assert len(hex_part) == 64
    assert all(c in "0123456789abcdefABCDEF" for c in hex_part)


def test_different_values_produce_different_digests():
    """Different inputs produce different digests."""
    digest1 = canonical_digest({"value": 1})
    digest2 = canonical_digest({"value": 2})
    
    assert digest1 != digest2


# === Test 6: Contract projection excludes digest declarations ===

def test_contract_projection_excludes_digest_declarations():
    """canonical_contract_projection excludes contract_digest and action_digest."""
    contract = {
        "target": {"id": "123"},
        "capability": "test",
        "parameters": {},
        "contract_digest": "sha256:" + "a" * 64,
        "action_digest": "sha256:" + "b" * 64,
    }
    
    projection = canonical_contract_projection(contract)
    
    # Digest declarations must be excluded
    assert "contract_digest" not in projection
    assert "action_digest" not in projection
    # Other fields must be included
    assert "target" in projection
    assert "capability" in projection
    assert "parameters" in projection


# === Test 7: _strict_equal type safety ===

def test_strict_equal_boolean_int_substitution_rejected():
    """_strict_equal rejects boolean/int substitutions."""
    assert not _strict_equal(True, 1)
    assert not _strict_equal(False, 0)
    assert not _strict_equal(1, True)
    assert not _strict_equal(0, False)


def test_strict_equal_integer_float_substitution_rejected():
    """_strict_equal rejects int/float substitutions."""
    assert not _strict_equal(1, 1.0)
    assert not _strict_equal(0, 0.0)
    assert not _strict_equal(42, 42.0)


def test_strict_equal_nested_type_safety():
    """_strict_equal enforces type safety in nested structures."""
    left = {"nested": {"flag": True}}
    right = {"nested": {"flag": 1}}
    
    assert not _strict_equal(left, right)


# === Test 8: Target identity validation ===

def test_valid_target_identity_accepts_valid_values():
    """_valid_target_identity accepts concrete, non-empty values."""
    assert _valid_target_identity("non-empty-string")
    assert _valid_target_identity(1)
    assert _valid_target_identity(42)
    assert _valid_target_identity({"key": "value"})
    assert _valid_target_identity({"nested": {"deep": "value"}})


def test_valid_target_identity_rejects_invalid_values():
    """_valid_target_identity rejects None, bool, empty strings, empty mappings."""
    assert not _valid_target_identity(None)
    assert not _valid_target_identity(True)
    assert not _valid_target_identity(False)
    assert not _valid_target_identity("")
    assert not _valid_target_identity("   ")
    assert not _valid_target_identity({})
    assert not _valid_target_identity({"nested": {}})
    assert not _valid_target_identity({"key": ""})


# === Test 9: Signed payload excludes signature.value ===

def test_signed_payload_excludes_signature_value():
    """signed_payload excludes signature.value from the payload."""
    receipt = {
        "target": {"id": "123"},
        "capability": "test",
        "parameters": {},
        "signature": {
            "algorithm": "ed25519",
            "key_id": "key-001",
            "value": "super-secret-signature",
        },
    }
    
    payload_bytes = signed_payload(receipt)
    payload_str = payload_bytes.decode("utf-8")
    
    # The signature.value must NOT be in the payload
    assert "super-secret-signature" not in payload_str
    # But other signature fields must be present
    assert "ed25519" in payload_str
    assert "key-001" in payload_str


# === Test 10: Duplicate key rejection ===

def test_duplicate_key_loader_rejects_duplicate_keys():
    """DuplicateKeyLoader raises error on duplicate mapping keys."""
    yaml_with_duplicate = """
target:
  cluster: prod
  cluster: staging  # Duplicate key!
"""
    with pytest.raises(Exception):  # ConstructorError
        loads_receipt(yaml_with_duplicate)