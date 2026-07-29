"""Approval receipt validation and canonicalization.

Provides deterministic, type-preserving canonicalization for digest computation
and validation of versioned approval receipts.
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

import yaml

from .contract import _strict_equal, _valid_target_identity


APPROVAL_RECEIPT_REQUIRED_FIELDS = (
    "receipt_version", "approval_request_id", "decision", "action_digest",
    "contract_digest", "target", "capability", "parameters", "issuer", "issued_at", "valid_until",
    "audience", "receipt_id", "nonce", "signature",
)


QUORUM_REQUIRED_FIELDS = ("required", "approved", "signers", "shared_digest", "one_lease_max")
SIGNER_REQUIRED_FIELDS = ("subject", "decision", "timestamp")
SIGNATURE_REQUIRED_FIELDS = ("algorithm", "key_id", "value")


class DuplicateKeyLoader(yaml.SafeLoader):
    """SafeLoader subclass that rejects duplicate mapping keys.

    PyYAML's default safe_load silently keeps the last value for a duplicate
    key, which is unsafe in an authorization context: a tampered or malformed
    receipt YAML could silently swap field values without any validation error.
    This loader makes duplicate keys a hard parse error.
    """


def _no_duplicates_constructor(loader, node, deep=False):
    """Mapping constructor that fails on duplicate keys."""
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None,
                f"duplicate key {key!r} found in mapping",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _no_duplicates_constructor,
)


def loads_receipt(text: str) -> Any:
    """Parse YAML receipt text, rejecting duplicate mapping keys.

    Raises yaml.YAMLError on any parse error including duplicate keys.
    """
    return yaml.load(text, Loader=DuplicateKeyLoader)


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


def parse_utc_timestamp(value: Any) -> datetime:
    """Parse a timezone-bearing ISO-8601 timestamp, or fail closed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_approval_receipt(receipt: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors for an approval receipt.

    Follows the exact pattern of validate_capability_approval in contract.py.
    Returns a list of deterministic error strings (empty list = valid).

    Args:
        receipt: Approval receipt mapping to validate

    Returns:
        List of error strings; empty if receipt is valid
    """
    # This public seam must fail closed for look-alike inputs rather than
    # raising while indexing a non-mapping.
    if not isinstance(receipt, Mapping):
        return ["receipt must be a mapping"]
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

    contract_digest = receipt.get("contract_digest")
    if "contract_digest" in receipt and (
        not isinstance(contract_digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", contract_digest)
    ):
        errors.append("contract_digest must be a sha256:<64 hex characters> digest")

    # Validate target identity
    if "target" in receipt and not _valid_target_identity(receipt["target"]):
        errors.append("target must contain non-empty identity values")

    # Validate non-empty string fields
    for field in (
        "approval_request_id", "capability", "issuer", "audience", "receipt_id", "nonce"
    ):
        if field in receipt and (not isinstance(receipt[field], str) or not receipt[field].strip()):
            errors.append(f"{field} must be a non-empty string")

    # Validate ISO-8601 timestamps and ordering using parsed UTC values.
    parsed_times: dict[str, datetime] = {}
    for field in ("issued_at", "valid_until"):
        if field in receipt:
            if not isinstance(receipt[field], str) or not receipt[field].strip():
                errors.append(f"{field} must be a non-empty ISO-8601 timestamp")
            else:
                try:
                    parsed_times[field] = parse_utc_timestamp(receipt[field])
                except (TypeError, ValueError):
                    errors.append(f"{field} must be a timezone-aware ISO-8601 timestamp")

    # Validate valid_until is after issued_at
    if "issued_at" in parsed_times and "valid_until" in parsed_times:
        if parsed_times["issued_at"] >= parsed_times["valid_until"]:
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
            data = loads_receipt(f.read())
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