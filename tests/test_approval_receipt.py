"""Runtime invariants for approval receipts."""

import hashlib
from pathlib import Path

import yaml

from agentic_fieldbook.receipt import (
    validate_approval_receipt,
    canonicalize,
    canonical_digest,
    signed_payload,
    check_approval_receipt,
    APPROVAL_RECEIPT_REQUIRED_FIELDS,
    QUORUM_REQUIRED_FIELDS,
)

# Valid receipt fixture (all required fields, minimal structure)
VALID = {
    "receipt_version": "1",
    "approval_request_id": "req-001",
    "decision": "approved",
    "action_digest": "sha256:" + "a" * 64,
    "target": {"cluster": "example", "type": "guest", "id": "123"},
    "capability": "snapshot_guest",
    "parameters": {"snapshot": "approved"},
    "issuer": "user-001",
    "issued_at": "2025-01-01T00:00:00Z",
    "valid_until": "2025-01-02T00:00:00Z",
    "audience": "broker-001",
    "receipt_id": "receipt-001",
    "nonce": "nonce-001",
    "signature": {
        "algorithm": "ed25519",
        "key_id": "key-001",
        "value": "signature-value",
    },
}

# Valid receipt with quorum (2-of-2 approval)
VALID_QUORUM = {
    **VALID,
    "approval_request_id": "req-002",
    "receipt_id": "receipt-002",
    "nonce": "nonce-002",
    "quorum": {
        "required": 2,
        "approved": 2,
        "signers": [
            {"subject": "user-001", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"},
            {"subject": "user-002", "decision": "approved", "timestamp": "2025-01-01T00:01:00Z"},
        ],
        "shared_digest": "sha256:" + "b" * 64,
        "one_lease_max": True,
    },
}


def test_valid_receipt_has_no_errors():
    assert validate_approval_receipt(VALID) == []


def test_valid_quorum_receipt_has_no_errors():
    assert validate_approval_receipt(VALID_QUORUM) == []


def test_missing_required_fields_are_named():
    errors = validate_approval_receipt({})
    assert errors == [f"missing required field: {field}" for field in (
        "receipt_version", "approval_request_id", "decision", "action_digest",
        "target", "capability", "parameters", "issuer", "issued_at", "valid_until",
        "audience", "receipt_id", "nonce", "signature",
    )]


def test_invalid_receipt_version_rejected():
    errors = validate_approval_receipt({**VALID, "receipt_version": "2"})
    assert errors == ["receipt_version must be exactly '1'"]


def test_non_approved_decision_cannot_authorize():
    for decision in ("rejected", "expired", "revoked"):
        errors = validate_approval_receipt({**VALID, "decision": decision})
        assert errors == [
            f"decision must be 'approved' to authorize; got '{decision}'"
        ]


def test_unknown_decision_value_rejected():
    errors = validate_approval_receipt({**VALID, "decision": "unknown"})
    assert errors == [
        "decision must be one of: approved, expired, rejected, revoked; got 'unknown'",
        "decision must be 'approved' to authorize; got 'unknown'",
    ]


def test_digest_whitespace_rejected():
    padded = f" {VALID['action_digest']} "
    errors = validate_approval_receipt({**VALID, "action_digest": padded})
    assert errors == ["action_digest must be a sha256:<64 hex characters> digest"]


def test_malformed_digest_rejected():
    errors = validate_approval_receipt({**VALID, "action_digest": "sha256:abc"})
    assert errors == ["action_digest must be a sha256:<64 hex characters> digest"]


def test_empty_target_rejected():
    errors = validate_approval_receipt({**VALID, "target": {}})
    assert errors == ["target must contain non-empty identity values"]


def test_malformed_target_identity_values_rejected():
    for member in ("", " ", None, True):
        target = {"id": member}
        errors = validate_approval_receipt({**VALID, "target": target})
        assert errors == ["target must contain non-empty identity values"]


def test_empty_string_fields_rejected():
    # These fields are set to valid values in VALID, so we can test empty string rejection
    errors = validate_approval_receipt({**VALID, "capability": ""})
    assert "capability must be a non-empty string" in errors
    errors = validate_approval_receipt({**VALID, "audience": ""})
    assert "audience must be a non-empty string" in errors


def test_empty_issuer_rejected():
    errors = validate_approval_receipt({**VALID, "issuer": ""})
    assert "issuer must be a non-empty string" in errors


def test_valid_until_must_be_after_issued_at():
    errors = validate_approval_receipt({
        **VALID,
        "issued_at": "2025-01-02T00:00:00Z",
        "valid_until": "2025-01-01T00:00:00Z",
    })
    assert errors == ["valid_until must be after issued_at"]


def test_parameters_must_be_mapping():
    errors = validate_approval_receipt({**VALID, "parameters": "not-a-mapping"})
    assert errors == ["parameters must be a mapping"]


def test_signature_must_be_mapping():
    errors = validate_approval_receipt({**VALID, "signature": "not-a-mapping"})
    assert errors == ["signature must be a mapping"]


def test_signature_missing_fields_rejected():
    errors = validate_approval_receipt({**VALID, "signature": {}})
    assert errors == [f"signature missing field: {field}" for field in (
        "algorithm", "key_id", "value"
    )]


def test_quorum_must_be_mapping():
    errors = validate_approval_receipt({**VALID, "quorum": "not-a-mapping"})
    assert errors == ["quorum must be a mapping"]


def test_quorum_missing_fields_rejected():
    errors = validate_approval_receipt({**VALID, "quorum": {}})
    assert errors == [f"quorum missing field: {field}" for field in QUORUM_REQUIRED_FIELDS]


def test_quorum_required_approved_must_be_integers():
    for field in ("required", "approved"):
        for value in (True, False, 1.0, "1"):
            errors = validate_approval_receipt({**VALID, "quorum": {"required": 1, "approved": 1, **{field: value}, "signers": [{"subject": "u", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}], "shared_digest": "sha256:" + "a" * 64, "one_lease_max": True}})
            assert errors == [f"quorum.{field} must be an integer >= 1"]


def test_quorum_below_required_rejected():
    errors = validate_approval_receipt({**VALID, "quorum": {
        "required": 2,
        "approved": 1,
        "signers": [{"subject": "u1", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}],
        "shared_digest": "sha256:" + "a" * 64,
        "one_lease_max": True,
    }})
    assert errors == ["quorum.approved (1) must equal quorum.required (2)"]


def test_quorum_signer_not_approved_rejected():
    errors = validate_approval_receipt({**VALID, "quorum": {
        "required": 1,
        "approved": 1,
        "signers": [{"subject": "u1", "decision": "rejected", "timestamp": "2025-01-01T00:00:00Z"}],
        "shared_digest": "sha256:" + "a" * 64,
        "one_lease_max": True,
    }})
    assert errors == ["quorum.signers[0].decision must be 'approved'"]


def test_quorum_shared_digest_malformed_rejected():
    errors = validate_approval_receipt({**VALID, "quorum": {
        "required": 1,
        "approved": 1,
        "signers": [{"subject": "u1", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}],
        "shared_digest": "sha256:abc",
        "one_lease_max": True,
    }})
    assert errors == ["quorum.shared_digest must be a sha256:<64 hex characters> digest"]


def test_quorum_one_lease_max_must_be_true():
    errors = validate_approval_receipt({**VALID, "quorum": {
        "required": 1,
        "approved": 1,
        "signers": [{"subject": "u1", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}],
        "shared_digest": "sha256:" + "a" * 64,
        "one_lease_max": False,
    }})
    assert errors == ["quorum.one_lease_max must be true"]


# === Canonicalization tests (THE critical acceptance items) ===


def test_boolean_not_coerced_to_integer():
    """Canonicalization preserves boolean vs integer distinction."""
    # True != 1, so digests must differ
    digest_bool = canonical_digest(True)
    digest_int = canonical_digest(1)
    assert digest_bool != digest_int


def test_integer_not_coerced_to_float():
    """Canonicalization preserves integer vs float distinction."""
    # 1 != 1.0, so digests must differ
    digest_int = canonical_digest(1)
    digest_float = canonical_digest(1.0)
    assert digest_int != digest_float


def test_mapping_order_does_not_change_digest():
    """Canonicalization sorts mapping keys, so order doesn't affect digest."""
    mapping1 = {"a": 1, "b": 2, "c": 3}
    mapping2 = {"c": 3, "a": 1, "b": 2}
    digest1 = canonical_digest(mapping1)
    digest2 = canonical_digest(mapping2)
    assert digest1 == digest2


def test_list_order_does_change_digest():
    """Canonicalization preserves list order, so different order = different digest."""
    list1 = [1, 2, 3]
    list2 = [3, 2, 1]
    digest1 = canonical_digest(list1)
    digest2 = canonical_digest(list2)
    assert digest1 != digest2


def test_nested_canonicalization_is_recursive():
    """Canonicalization sorts keys at all nesting levels."""
    nested1 = {"outer": {"inner": {"c": 3, "a": 1, "b": 2}}}
    nested2 = {"outer": {"inner": {"a": 1, "b": 2, "c": 3}}}
    digest1 = canonical_digest(nested1)
    digest2 = canonical_digest(nested2)
    assert digest1 == digest2


def test_none_handled_explicitly():
    """None is handled explicitly, not dropped or coerced."""
    mapping_with_none = {"key": None}
    canonical = canonicalize(mapping_with_none)
    # None should be present as JSON null
    assert "null" in canonical
    digest = canonical_digest(mapping_with_none)
    # Digest should be deterministic
    assert isinstance(digest, str) and digest.startswith("sha256:")


def test_canonicalization_is_deterministic():
    """Same input always produces same digest."""
    value = {"a": [1, 2, 3], "b": {"x": 10, "y": 20}}
    digest1 = canonical_digest(value)
    digest2 = canonical_digest(value)
    assert digest1 == digest2


# === Signed payload tests ===


def test_signed_payload_excludes_only_signature_value():
    """Signed payload includes algorithm + key_id, excludes value."""
    payload = signed_payload(VALID)
    payload_str = payload.decode("utf-8")

    # Algorithm and key_id should be present
    assert '"algorithm":"ed25519"' in payload_str
    assert '"key_id":"key-001"' in payload_str

    # Value should be excluded
    assert '"value"' not in payload_str
    assert "signature-value" not in payload_str


def test_signed_payload_is_deterministic():
    """Same receipt produces same signed payload bytes."""
    payload1 = signed_payload(VALID)
    payload2 = signed_payload(VALID)
    assert payload1 == payload2


def test_signed_payload_canonicalizes_all_fields():
    """Signed payload canonicalizes all receipt fields except signature.value."""
    payload = signed_payload(VALID)
    payload_str = payload.decode("utf-8")

    # Check that all other fields are present and canonicalized
    assert '"receipt_version":"1"' in payload_str
    assert '"decision":"approved"' in payload_str
    assert '"capability":"snapshot_guest"' in payload_str

    # Mapping keys should be sorted (e.g., signature keys sorted)
    # algorithm comes before key_id lexicographically
    assert payload_str.index('"algorithm"') < payload_str.index('"key_id"')


# === Type confusion tests ===


def test_boolean_fields_rejected_where_integer_expected():
    """Boolean is not accepted where integer is required (quorum.required/approved)."""
    for field in ("required", "approved"):
        errors = validate_approval_receipt({
            **VALID,
            "quorum": {
                "required": 2,
                "approved": 2,
                **{field: True},  # Boolean instead of integer
                "signers": [{"subject": "u1", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}],
                "shared_digest": "sha256:" + "a" * 64,
                "one_lease_max": True,
            },
        })
        assert errors == [f"quorum.{field} must be an integer >= 1"]


def test_float_rejected_where_integer_expected():
    """Float is not accepted where integer is required (quorum.required/approved)."""
    for field in ("required", "approved"):
        errors = validate_approval_receipt({
            **VALID,
            "quorum": {
                "required": 2,
                "approved": 2,
                **{field: 1.0},  # Float instead of integer
                "signers": [{"subject": "u1", "decision": "approved", "timestamp": "2025-01-01T00:00:00Z"}],
                "shared_digest": "sha256:" + "a" * 64,
                "one_lease_max": True,
            },
        })
        assert errors == [f"quorum.{field} must be an integer >= 1"]


# === CLI tests ===


def test_receipt_command_exposes_runtime_validation(tmp_path: Path, capsys):
    path = tmp_path / "receipt.yaml"
    path.write_text("decision: rejected\n")
    assert check_approval_receipt(str(path)) == 1
    output = capsys.readouterr().err
    assert "missing required field" in output
    assert "decision must be 'approved' to authorize" in output


def test_receipt_command_accepts_valid_receipt(tmp_path: Path, capsys):
    path = tmp_path / "valid.yaml"
    path.write_text(yaml.safe_dump(VALID, sort_keys=False))
    assert check_approval_receipt(str(path)) == 0
    assert "Approval receipt valid" in capsys.readouterr().out


# === Combined validation tests ===


def test_multiple_errors_reported_deterministically():
    """When multiple errors exist, they are reported in deterministic order."""
    errors = validate_approval_receipt({
        "receipt_version": "2",  # Invalid version
        "decision": "unknown",  # Invalid decision
        "action_digest": "bad",  # Bad digest
        # Missing all other required fields
    })
    # Errors should be deterministic (order depends on validation sequence)
    assert "receipt_version must be exactly '1'" in errors
    assert "decision must be one of: approved, expired, rejected, revoked; got 'unknown'" in errors
    assert "action_digest must be a sha256:<64 hex characters> digest" in errors


def test_empty_receipt_all_required_fields_named():
    """Completely empty receipt names all required fields."""
    errors = validate_approval_receipt({})
    assert len(errors) == len(APPROVAL_RECEIPT_REQUIRED_FIELDS)
    for field in APPROVAL_RECEIPT_REQUIRED_FIELDS:
        assert any(field in error for error in errors)