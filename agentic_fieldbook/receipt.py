"""Approval receipt validation and canonicalization.

Provides deterministic, type-preserving canonicalization for digest computation
and validation of versioned approval receipts.
"""

import hashlib
import json
import re
import sys
from typing import Any, Mapping

import yaml


APPROVAL_RECEIPT_REQUIRED_FIELDS = (
    "receipt_version", "approval_request_id", "decision", "action_digest",
    "target", "capability", "parameters", "issuer", "issued_at", "valid_until",
    "audience", "receipt_id", "nonce", "signature",
)


QUORUM_REQUIRED_FIELDS = ("required", "approved", "signers", "shared_digest", "one_lease_max")
SIGNER_REQUIRED_FIELDS = ("subject", "decision", "timestamp")
SIGNATURE_REQUIRED_FIELDS = ("algorithm", "key_id", "value")


def _valid_target_identity(value: Any) -> bool:
    """Accept only concrete, non-empty target identity values.

    Mirrors contract.py implementation for consistency.
    """
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if type(value) is int:
        return value >= 1
    if isinstance(value, Mapping):
        return bool(value) and all(
            isinstance(key, str) and key.strip() and _valid_target_identity(member)
            for key, member in value.items()
        )
    return False


def _strict_equal(left: Any, right: Any) -> bool:
    """Compare YAML values without Python's bool/int equality coercion.

    Mirrors contract.py implementation for consistency.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        if left.keys() != right.keys():
            return False
        return all(_strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(item, other) for item, other in zip(left, right)
        )
    return left == right


def canonicalize(value: Any) -> str:
    """Produce a deterministic, type-preserving serialization of a value.

    Rules:
    - Mapping keys are sorted recursively (lexicographic by UTF-8 bytes)
    - List order is preserved (order is semantically significant)
    - Booleans are NOT coerced to integers (True != 1)
    - Integers are NOT coerced to floats (1 != 1.0)
    - None is handled explicitly (never dropped or coerced)
    - Output is deterministic JSON-like encoding (sorted keys, no whitespace)

    The serialization uses a custom encoder that:
    - Preserves Python type distinctions from YAML parsing
    - Encodes as UTF-8 JSON with sorted keys and no whitespace
    - Ensures deterministic output for identical values

    Args:
        value: Any JSON-serializable value (dict, list, str, int, float, bool, None)

    Returns:
        Deterministic JSON string (UTF-8 encoded, sorted keys, no whitespace)

    Raises:
        TypeError: If value contains non-JSON-serializable types
    """
    def _serialize(obj: Any) -> Any:
        """Convert Python objects to JSON-serializable form while preserving types."""
        if obj is None:
            return None
        if isinstance(obj, bool):
            # Preserve boolean type (not converted to int)
            return obj
        if type(obj) is int:
            # Preserve integer type (reject bool subclass, no float coercion)
            return obj
        if type(obj) is float:
            # Preserve float type
            return obj
        if isinstance(obj, str):
            return obj
        if isinstance(obj, Mapping):
            # Recursively serialize mappings with sorted keys
            return {k: _serialize(v) for k, v in sorted(obj.items(), key=lambda x: x[0])}
        if isinstance(obj, list):
            # Preserve list order (semantically significant)
            return [_serialize(item) for item in obj]
        raise TypeError(f"Cannot canonicalize non-JSON-serializable type: {type(obj)}")

    # Serialize to JSON with no whitespace for deterministic output
    # Use separators=(',', ':') to eliminate all whitespace
    serialized = json.dumps(_serialize(value), separators=(",", ":"), ensure_ascii=False)
    return serialized


def canonical_digest(value: Any) -> str:
    """Compute SHA256 digest of canonicalized value.

    Returns the digest in the format "sha256:<64 hex characters>".
    This is the action_digest format validated in receipts.

    Args:
        value: Any value to canonicalize and digest

    Returns:
        Digest string in format "sha256:<64 hex characters>"
    """
    canonical = canonicalize(value)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def signed_payload(receipt: Mapping[str, Any]) -> bytes:
    """Extract the signed payload from a receipt.

    Canonicalizes every receipt field EXCEPT signature.value.
    The signature sub-mapping's algorithm and key_id ARE included
    (they identify how to verify); only value (the detached signature)
    is excluded.

    Args:
        receipt: Approval receipt mapping

    Returns:
        UTF-8 encoded canonicalized payload bytes

    Raises:
        ValueError: If receipt is missing required fields
    """
    # Create a copy without signature.value
    payload = dict(receipt)
    if "signature" in payload and isinstance(payload["signature"], Mapping):
        payload["signature"] = dict(payload["signature"])
        payload["signature"].pop("value", None)

    # Canonicalize and encode
    canonical = canonicalize(payload)
    return canonical.encode("utf-8")


def validate_approval_receipt(receipt: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors for an approval receipt.

    Follows the exact pattern of validate_capability_approval in contract.py.
    Returns a list of deterministic error strings (empty list = valid).

    Args:
        receipt: Approval receipt mapping to validate

    Returns:
        List of error strings; empty if receipt is valid
    """
    errors: list[str] = []

    # Check required fields
    for field in APPROVAL_RECEIPT_REQUIRED_FIELDS:
        if field not in receipt or receipt[field] is None or receipt[field] == "":
            errors.append(f"missing required field: {field}")

    # Validate receipt_version is exactly "1"
    if "receipt_version" in receipt:
        if not isinstance(receipt["receipt_version"], str) or receipt["receipt_version"] != "1":
            errors.append("receipt_version must be exactly '1'")

    # Validate decision is one of the allowed values
    valid_decisions = {"approved", "rejected", "expired", "revoked"}
    if "decision" in receipt:
        if not isinstance(receipt["decision"], str) or receipt["decision"] not in valid_decisions:
            errors.append(
                f"decision must be one of: {', '.join(sorted(valid_decisions))}; "
                f"got '{receipt.get('decision', '')}'"
            )

    # Validate digest format
    digest = receipt.get("action_digest")
    if "action_digest" in receipt and (
        not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
    ):
        errors.append("action_digest must be a sha256:<64 hex characters> digest")

    # Validate target identity
    if "target" in receipt and not _valid_target_identity(receipt["target"]):
        errors.append("target must contain non-empty identity values")

    # Validate non-empty string fields
    for field in (
        "approval_request_id", "capability", "issuer", "audience", "receipt_id", "nonce"
    ):
        if field in receipt and (not isinstance(receipt[field], str) or not receipt[field].strip()):
            errors.append(f"{field} must be a non-empty string")

    # Validate ISO-8601 timestamps
    for field in ("issued_at", "valid_until"):
        if field in receipt:
            if not isinstance(receipt[field], str) or not receipt[field].strip():
                errors.append(f"{field} must be a non-empty ISO-8601 timestamp")

    # Validate valid_until is after issued_at
    if "issued_at" in receipt and "valid_until" in receipt:
        issued = receipt["issued_at"]
        valid = receipt["valid_until"]
        if isinstance(issued, str) and isinstance(valid, str):
            # ISO-8601 timestamps are lexicographically comparable when same format
            if issued >= valid:
                errors.append("valid_until must be after issued_at")

    # Validate parameters is a mapping
    if "parameters" in receipt and not isinstance(receipt["parameters"], Mapping):
        errors.append("parameters must be a mapping")

    # Validate signature structure
    signature = receipt.get("signature")
    if "signature" in receipt and not isinstance(signature, Mapping):
        errors.append("signature must be a mapping")
    elif isinstance(signature, Mapping):
        for field in SIGNATURE_REQUIRED_FIELDS:
            if field not in signature:
                errors.append(f"signature missing field: {field}")
            elif not isinstance(signature[field], str) or not signature[field].strip():
                errors.append(f"signature.{field} must be a non-empty string")

    # Validate quorum envelope if present
    quorum = receipt.get("quorum")
    if quorum is not None:
        if not isinstance(quorum, Mapping):
            errors.append("quorum must be a mapping")
        else:
            # Check required quorum fields
            for field in QUORUM_REQUIRED_FIELDS:
                if field not in quorum:
                    errors.append(f"quorum missing field: {field}")

            # Validate required/approved are integers >= 1
            for field in ("required", "approved"):
                if field in quorum and (type(quorum[field]) is not int or quorum[field] < 1):
                    errors.append(f"quorum.{field} must be an integer >= 1")

            # Validate approved == required
            if "required" in quorum and "approved" in quorum:
                if type(quorum["required"]) is int and type(quorum["approved"]) is int:
                    if quorum["approved"] != quorum["required"]:
                        errors.append(f"quorum.approved ({quorum['approved']}) must equal quorum.required ({quorum['required']})")

            # Validate signers is a list
            if "signers" in quorum:
                if not isinstance(quorum["signers"], list):
                    errors.append("quorum.signers must be a list")
                elif not quorum["signers"]:
                    errors.append("quorum.signers must contain at least one signer")
                else:
                    # Validate each signer
                    for idx, signer in enumerate(quorum["signers"]):
                        if not isinstance(signer, Mapping):
                            errors.append(f"quorum.signers[{idx}] must be a mapping")
                        else:
                            for field in SIGNER_REQUIRED_FIELDS:
                                if field not in signer:
                                    errors.append(f"quorum.signers[{idx}] missing field: {field}")
                            # Validate signer decision is "approved"
                            if "decision" in signer:
                                if not isinstance(signer["decision"], str) or signer["decision"] != "approved":
                                    errors.append(f"quorum.signers[{idx}].decision must be 'approved'")

            # Validate shared_digest format
            shared_digest = quorum.get("shared_digest")
            if "shared_digest" in quorum and (
                not isinstance(shared_digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", shared_digest)
            ):
                errors.append("quorum.shared_digest must be a sha256:<64 hex characters> digest")

            # Validate one_lease_max is true
            if "one_lease_max" in quorum and quorum["one_lease_max"] is not True:
                errors.append("quorum.one_lease_max must be true")

    # Check if decision authorizes (only "approved" receipts authorize)
    if "decision" in receipt and receipt["decision"] != "approved":
        errors.append(
            f"decision must be 'approved' to authorize; got '{receipt['decision']}'"
        )

    return errors


def check_approval_receipt(path: str) -> int:
    """Validate a YAML approval receipt and print named failures.

    Mirrors check_capability_approval in contract.py.

    Args:
        path: Path to YAML file containing approval receipt

    Returns:
        Exit code: 0 if valid, 1 if invalid or error loading
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot load approval receipt {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("ERROR: approval receipt must be a YAML mapping", file=sys.stderr)
        return 1
    errors = validate_approval_receipt(data)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"Approval receipt valid: {path}")
    return 0