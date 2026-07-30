"""Broker-side approval receipt verification and replay protection.

The broker independently verifies approval receipts before issuing a lease,
enforcing all 10 verification rules from the native approval wiring spec
(§ "Verification rules"). This module defines deployment-neutral interfaces
(KeyStore, ApproverPolicy, ApprovalStore, Clock) that a deployment adapter
must implement. The broker never trusts the adapter's success response without
verifying the receipt itself.

Policy defaults (from Ticket 01 — Deployment Approval-Policy Decision Record):
- Default approval validity: 10 minutes
- Permitted clock skew: 30 seconds
- One-time mandatory: one receipt authorizes exactly one lease
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace as dataclass_replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping

from .contract import _strict_equal
from .receipt import canonical_digest, validate_approval_receipt, signed_payload, parse_utc_timestamp


# ── Policy defaults (Ticket 01) ──────────────────────────────────────────

DEFAULT_CLOCK_SKEW_SECONDS = 30
DEFAULT_VALIDITY_MINUTES = 10


# ── Failure categories ───────────────────────────────────────────────────

class VerificationCategory(str, Enum):
    """Specific non-success categories for receipt verification failures.

    A failed check returns one of these categories. None of them disclose
    secrets, signing material, or unnecessary private identity data.
    """

    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    INVALID_SIGNATURE = "invalid_signature"
    UNKNOWN_ISSUER = "unknown_issuer"
    AUDIENCE_MISMATCH = "audience_mismatch"
    EXPIRED = "expired"
    REPLAY_DETECTED = "replay_detected"
    ACTION_MISMATCH = "action_mismatch"
    POLICY_DENIED = "policy_denied"
    STORE_UNAVAILABLE = "store_unavailable"


class ReservationOutcome(str, Enum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    REPLAY = "replay"
    AUDIT_UNAVAILABLE = "audit_unavailable"


class OperationOutcome(str, Enum):
    RESERVED = "reserved"
    REPLAY = "replay"
    UNAVAILABLE = "unavailable"
    CONSUMED = "consumed"


class LeaseState(str, Enum):
    """Lifecycle of broker authority, distinct from capability success."""
    ISSUED = "issued"
    EXECUTING = "executing"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


@dataclass(frozen=True)
class Lease:
    lease_id: str
    receipt_id: str
    action_digest: str
    target: Mapping[str, Any]
    capability: str
    parameters: Mapping[str, Any]
    issued_at: datetime
    expires_at: datetime
    operation_limit: int
    operations_used: int = 0
    state: LeaseState = LeaseState.ISSUED


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    timestamp: datetime
    approval_request_id: str
    receipt_id: str = ""
    lease_id: str = ""
    action_digest: str = ""
    subject_ref: str = ""
    reason: str = ""


class LeaseAuthority:
    """Append-only lease state seam with fail-closed expiry/revocation."""
    def __init__(self) -> None:
        self.leases: dict[str, Lease] = {}
        self.audit_events: list[AuditEvent] = []
        self.operations: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()

    def issue(self, lease: Lease) -> Lease:
        with self._lock:
            existing = self.leases.get(lease.lease_id)
            if existing is not None:
                return existing
            event = AuditEvent("lease_issued", lease.issued_at, "",
                               lease.receipt_id, lease.lease_id,
                               lease.action_digest)
            # Commit the durable evidence before exposing the authority. If the
            # audit sink fails, no lease is left behind to strand authorization.
            self.audit_events.append(event)
            try:
                self.leases[lease.lease_id] = lease
            except Exception:
                self.audit_events.pop()
                raise
            return lease

    def revoke(self, lease_id: str, timestamp: datetime, reason: str) -> Lease:
        with self._lock:
            lease = self.leases[lease_id]
            if lease.state not in {LeaseState.REVOKED, LeaseState.EXPIRED}:
                lease = dataclass_replace(lease, state=LeaseState.REVOKED)
                self.leases[lease_id] = lease
                self.audit_events.append(AuditEvent("lease_revoked", timestamp, "",
                                                    lease.receipt_id, lease_id,
                                                    lease.action_digest, reason=reason))
            return lease

    def usable(self, lease_id: str, timestamp: datetime) -> bool:
        with self._lock:
            lease = self.leases[lease_id]
            if timestamp >= lease.expires_at and lease.state not in {LeaseState.EXPIRED, LeaseState.REVOKED}:
                lease = dataclass_replace(lease, state=LeaseState.EXPIRED)
                self.leases[lease_id] = lease
                self.audit_events.append(AuditEvent("lease_expired", timestamp, "",
                                                    lease.receipt_id, lease_id,
                                                    lease.action_digest))
            return lease.state is LeaseState.ISSUED and lease.operations_used < lease.operation_limit

    def reserve_operation(self, lease_id: str, operation_id: str,
                          timestamp: datetime) -> OperationOutcome:
        """Atomically reserve one operation, before the capability call."""
        with self._lock:
            if operation_id in self.operations:
                return OperationOutcome.REPLAY
            lease = self.leases[lease_id]
            if timestamp >= lease.expires_at:
                if lease.state is LeaseState.ISSUED:
                    self.leases[lease_id] = dataclass_replace(lease, state=LeaseState.EXPIRED)
                return OperationOutcome.UNAVAILABLE
            if lease.state is not LeaseState.ISSUED or lease.operations_used >= lease.operation_limit:
                return OperationOutcome.UNAVAILABLE
            self.leases[lease_id] = dataclass_replace(
                lease, state=LeaseState.EXECUTING, operations_used=lease.operations_used + 1
            )
            self.operations[operation_id] = (lease_id, LeaseState.EXECUTING.value)
            return OperationOutcome.RESERVED

    def consume_operation(self, lease_id: str, operation_id: str,
                          timestamp: datetime) -> OperationOutcome:
        """Atomically finish a reserved operation and consume its lease budget."""
        with self._lock:
            record = self.operations.get(operation_id)
            if record != (lease_id, LeaseState.EXECUTING.value):
                return OperationOutcome.REPLAY if record else OperationOutcome.UNAVAILABLE
            lease = self.leases[lease_id]
            next_state = (LeaseState.CONSUMED
                          if lease.operations_used >= lease.operation_limit
                          else LeaseState.ISSUED)
            self.operations[operation_id] = (lease_id, LeaseState.CONSUMED.value)
            self.leases[lease_id] = dataclass_replace(lease, state=next_state)
            self.audit_events.append(AuditEvent("operation_consumed", timestamp, "",
                                                lease.receipt_id, lease_id,
                                                lease.action_digest))
            return OperationOutcome.CONSUMED

    def recover(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self.audit_events)

VERIFIED = VerificationCategory.VERIFIED
VERIFICATION_FAILED = VerificationCategory.VERIFICATION_FAILED
INVALID_SIGNATURE = VerificationCategory.INVALID_SIGNATURE
UNKNOWN_ISSUER = VerificationCategory.UNKNOWN_ISSUER
AUDIENCE_MISMATCH = VerificationCategory.AUDIENCE_MISMATCH
EXPIRED = VerificationCategory.EXPIRED
REPLAY_DETECTED = VerificationCategory.REPLAY_DETECTED
ACTION_MISMATCH = VerificationCategory.ACTION_MISMATCH
POLICY_DENIED = VerificationCategory.POLICY_DENIED
STORE_UNAVAILABLE = VerificationCategory.STORE_UNAVAILABLE


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of receipt verification.

    Attributes:
        success: True only if all verification checks passed and a lease was issued.
        category: Specific failure category (or a success sentinel on success).
        reason: Human-readable reason (no secrets or private identity data).
        lease_id: Issued lease ID on success; empty on failure.
    """

    success: bool
    category: VerificationCategory = VERIFICATION_FAILED
    reason: str = ""
    lease_id: str = ""
    receipt_id: str = ""
    action_digest: str = ""


# ── Deployment-neutral interfaces ────────────────────────────────────────

class KeyStore(ABC):
    """Verifies receipt signatures against a trusted, non-revoked key set.

    A deployment adapter implements this with its KMS/HSM or equivalent
    non-exportable signing key infrastructure (Ticket 01 §4).
    Revoked or compromised keys must return False; unknown keys must return
    False. Historical verification under previously trusted keys remains
    possible subject to receipt validity and retention policy.
    """

    @abstractmethod
    def verify_signature(self, signature: Mapping[str, Any], payload: bytes) -> bool:
        """Verify a detached signature against the signed payload bytes.

        Args:
            signature: Mapping with algorithm, key_id, value.
            payload: Canonicalized signed payload bytes (excludes signature.value).

        Returns:
            True if the signature is valid and the key is trusted and non-revoked.
        """
        ...


class ApproverPolicy(ABC):
    """Checks whether issuers and requesters are authorized.

    A deployment adapter implements this with its identity provider,
    approver group mapping, and phishing-resistant MFA integration
    (Ticket 01 §1, §6). A caller-supplied issuer, channel membership,
    display name, or model output is never proof of human approval.
    """

    @abstractmethod
    def is_authorized_approver(
        self, issuer: str, capability: str, target: Mapping[str, Any]
    ) -> bool:
        """Check if issuer is an authorized human approver for this capability and target class.

        The policy matrix must classify both capability and target; the stricter
        applicable class wins (Ticket 01 §6).
        """
        ...

    @abstractmethod
    def is_requester_authorized(self, requester: str, capability: str) -> bool:
        """Check if the requester's authorization permits requesting this capability.

        Human approval does not override policy denial (spec rule 9).
        """
        ...


class ApprovalStore(ABC):
    """Authoritative store for approval requests, replay tokens, and lease state.

    A deployment adapter implements this with its durable, append-only storage.
    Replay-key reservation and the durable verification event are one
    transaction. One-time mandatory: one receipt authorizes exactly one lease.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the store is reachable and operational.

        When unavailable, the broker fails closed and does not use cached
        approval as authorization (spec failure requirement).
        """
        ...

    @abstractmethod
    def get_request_status(self, request_id: str) -> str | None:
        """Get the status of an approval request.

        Returns "pending", "approved", "rejected", "expired", "revoked",
        or None if not found.
        """
        ...


    @abstractmethod
    def reserve_and_record_verification(
        self, receipt_id: str, nonce: str, request_id: str, timestamp: datetime
    ) -> ReservationOutcome:
        """Atomically reserve replay keys and record the verification event.

        The operation is transactional: a failed audit write must not leave
        any replay key consumed. It is idempotent for an already durable event
        so a caller can safely retry after an ambiguous store response.
        """
        ...

    def reserve_and_record_lease(self, receipt_id: str, nonce: str, request_id: str,
                                 action_digest: str, target: Mapping[str, Any],
                                 capability: str, parameters: Mapping[str, Any],
                                 issued_at: datetime, expires_at: datetime,
                                 operation_limit: int) -> ReservationOutcome:
        """Atomically commit replay, verification, lease, and lease audit."""
        raise NotImplementedError("durable atomic lease commit is required")

    def record_audit_event(self, event: AuditEvent) -> bool:
        raise NotImplementedError("durable audit is required")

    def recover(self) -> tuple[AuditEvent, ...]:
        """Replay audit state without reviving terminal authority."""
        raise NotImplementedError("durable recovery is required")

    def reserve_operation(self, lease_id: str, operation_id: str,
                          timestamp: datetime) -> OperationOutcome:
        raise NotImplementedError("atomic operation reservation is required")

    def consume_operation(self, lease_id: str, operation_id: str,
                          timestamp: datetime) -> OperationOutcome:
        raise NotImplementedError("atomic operation consumption is required")


class Clock(ABC):
    """Injectable clock for deterministic time-window testing."""

    @abstractmethod
    def utcnow(self) -> datetime:
        """Return the current UTC time."""
        ...


# ── Module-level lock for atomic replay protection ──────────────────────
#
# This serializes the consume-or-reject critical section across concurrent
# verify_approval_receipt calls. A production deployment with per-receipt
# locking or store-level transactions would not need this module-level lock,
# but it ensures correctness for the interface contract: concurrent
# verification of the same receipt fails for all but one.

_consume_lock = threading.Lock()


# ── Internal helpers ─────────────────────────────────────────────────────

def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, handling the 'Z' suffix.

    Ensures the result is timezone-aware (UTC).
    """
    return parse_utc_timestamp(ts)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _canonical_action_package(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical action-package projection used by Fieldbook.

    ``ActionPackage.as_mapping`` in ``approval_gate.py`` defines these fields.
    The four-field fallback keeps the broker compatible with the existing
    receipt/contract seam while richer contracts bind the complete package.
    """
    fields = (
        "contract_digest",
        "target",
        "capability",
        "parameters",
        "lease_ttl",
        "operation_limit",
        "verification_method",
        "rollback",
        "abort_conditions",
        "approval_expires_at",
    )
    # ``contract_digest`` is a declaration of this digest, not part of its
    # own domain.  This must match ActionPackage.canonical_action()/digest().
    return {field: contract[field] for field in fields
            if field in contract and field != "contract_digest"}


def _canonical_contract_projection(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete contract projection, excluding digest declarations.

    Must match contract.canonical_contract_projection() output.
    """
    return {key: value for key, value in contract.items()
            if key not in ("contract_digest", "action_digest")}


# ── Public verification function ─────────────────────────────────────────

def verify_approval_receipt(
    receipt: Mapping[str, Any],
    contract: Mapping[str, Any],
    broker_audience: str,
    requester: str,
    keystore: KeyStore,
    policy: ApproverPolicy,
    store: ApprovalStore,
    clock: Clock,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
) -> VerificationResult:
    """Independently verify an approval receipt before issuing a lease.

    Enforces all 10 verification rules from the spec. The broker never trusts
    the adapter's success response — it verifies the receipt itself.

    Args:
        receipt: The approval receipt mapping (validated against version 1 schema).
        contract: The submitted contract with target, capability, parameters.
        broker_audience: The receiving deployment/broker identifier.
        requester: The identity of the requesting caller.
        keystore: Key verification interface (deployment-injected).
        policy: Approver/requester authorization policy (deployment-injected).
        store: Approval/replay store (deployment-injected).
        clock: Injectable clock for time-window testing.
        clock_skew_seconds: Permitted clock skew in seconds (default 30).

    Returns:
        VerificationResult with success/failure, category, reason, and lease_id.
        Never discloses secrets, signing material, or unnecessary private data.
    """
    # ── Rule 1: Receipt parses against supported version ───────────────
    if not isinstance(receipt, Mapping) or not isinstance(contract, Mapping):
        return VerificationResult(False, VERIFICATION_FAILED,
                                  "receipt and contract must be mappings", "")
    errors = validate_approval_receipt(receipt)
    if errors:
        return VerificationResult(
            success=False,
            category=VERIFICATION_FAILED,
            reason=f"receipt validation failed: {'; '.join(errors[:3])}",
        )

    # ── Store availability check (fail closed if store is down) ────────
    if not store.is_available():
        return VerificationResult(
            success=False,
            category=STORE_UNAVAILABLE,
            reason="approval store is unavailable; failing closed",
        )

    # ── Rule 2: Signature validates against trusted, non-revoked key ──
    try:
        payload = signed_payload(receipt)
        if not keystore.verify_signature(receipt["signature"], payload):
            return VerificationResult(
                success=False,
                category=INVALID_SIGNATURE,
                reason="signature verification failed or key is unknown/revoked",
            )
    except Exception:
        return VerificationResult(
            success=False,
            category=INVALID_SIGNATURE,
            reason="signature verification encountered an error",
        )

    # ── Rule 3: Issuer maps to an authorized human approver ───────────
    if not policy.is_authorized_approver(
        receipt["issuer"], receipt["capability"], receipt["target"]
    ):
        return VerificationResult(
            success=False,
            category=UNKNOWN_ISSUER,
            reason="issuer is not an authorized approver for this capability and target",
        )

    # ── Rule 4: Audience matches the receiving broker ─────────────────
    if receipt["audience"] != broker_audience:
        return VerificationResult(
            success=False,
            category=AUDIENCE_MISMATCH,
            reason="receipt audience does not match this broker",
        )

    # ── Rule 5: Current time within validity window (with skew) ───────
    now = _ensure_utc(clock.utcnow())
    try:
        issued_at = _parse_timestamp(receipt["issued_at"])
        valid_until = _parse_timestamp(receipt["valid_until"])
    except (TypeError, ValueError):
        return VerificationResult(False, VERIFICATION_FAILED,
                                  "receipt timestamps are invalid", "")
    if valid_until <= issued_at:
        return VerificationResult(False, VERIFICATION_FAILED,
                                  "receipt validity ordering is invalid", "")
    skew = timedelta(seconds=clock_skew_seconds)

    lower_bound = issued_at - skew
    upper_bound = valid_until + skew

    if now < lower_bound or now > upper_bound:
        return VerificationResult(
            success=False,
            category=EXPIRED,
            reason="receipt is outside the validity window (with clock-skew tolerance)",
        )

    # ── Rule 7: Action binding — target, capability, parameters match ─
    declared_contract_digest = contract.get("contract_digest")
    try:
        expected_contract_digest = canonical_digest(_canonical_contract_projection(contract))
    except (TypeError, ValueError, KeyError):
        return VerificationResult(False, ACTION_MISMATCH,
                                  "submitted contract is malformed", "")
    if (not isinstance(declared_contract_digest, str)
            or declared_contract_digest != expected_contract_digest
            or receipt["contract_digest"] != expected_contract_digest):
        return VerificationResult(False, ACTION_MISMATCH,
                                  "receipt contract digest does not match the complete contract projection", "")
    try:
        expected_action_digest = canonical_digest(_canonical_action_package(contract))
    except (TypeError, ValueError, KeyError):
        return VerificationResult(False, ACTION_MISMATCH,
                                  "submitted contract action package is malformed", "")
    required_action_fields = ("target", "capability", "parameters")
    if any(field not in contract for field in required_action_fields):
        return VerificationResult(False, ACTION_MISMATCH,
                                  "submitted contract action package is incomplete", "")
    if receipt["action_digest"] != expected_action_digest:
        return VerificationResult(
            success=False,
            category=ACTION_MISMATCH,
            reason="receipt action digest does not match the canonical contract action package",
        )
    if not _strict_equal(receipt["target"], contract["target"]):
        return VerificationResult(
            success=False,
            category=ACTION_MISMATCH,
            reason="receipt target does not match the submitted contract",
        )
    if receipt["capability"] != contract["capability"]:
        return VerificationResult(
            success=False,
            category=ACTION_MISMATCH,
            reason="receipt capability does not match the submitted contract",
        )
    if not _strict_equal(receipt["parameters"], contract["parameters"]):
        return VerificationResult(
            success=False,
            category=ACTION_MISMATCH,
            reason="receipt parameters do not match the submitted contract",
        )

    # ── Rule 9: Requester authorization (human approval ≠ policy grant) ─
    if not policy.is_requester_authorized(requester, receipt["capability"]):
        return VerificationResult(
            success=False,
            category=POLICY_DENIED,
            reason="requester is not authorized to request this capability",
        )


    # ── Rule 8: Request status in authoritative store ─────────────────
    request_id = receipt["approval_request_id"]
    status = store.get_request_status(request_id)
    if status is not None and status not in ("pending", "approved"):
        return VerificationResult(
            success=False,
            category=VERIFICATION_FAILED,
            reason=f"approval request status is '{status}'; cannot authorize",
        )
    if status is None:
        # Request not found in the authoritative store — cannot verify
        return VerificationResult(
            success=False,
            category=VERIFICATION_FAILED,
            reason="approval request not found in the authoritative store",
        )

    # ── Rules 6 + 8 + 10: transactional replay and audit ───────────────
    with _consume_lock:
        nonce = receipt["nonce"]
        receipt_id = receipt["receipt_id"]
        operation_limit = contract.get("operation_limit", 1)
        if type(operation_limit) is not int or operation_limit < 1:
            return VerificationResult(False, VERIFICATION_FAILED, "operation limit is invalid")
        ttl = contract.get("lease_ttl")
        if ttl is not None and (type(ttl) is not int or ttl < 1):
            return VerificationResult(False, VERIFICATION_FAILED, "lease TTL is invalid")
        lease_expires_at = now + timedelta(seconds=ttl) if ttl is not None else valid_until
        lease_id = hashlib.sha256(
            f"{receipt_id}:{nonce}:{request_id}".encode("utf-8")
        ).hexdigest()[:16]
        reserve_lease = getattr(store, "reserve_and_record_lease", None)
        if (not callable(reserve_lease)
                or type(store).reserve_and_record_lease is ApprovalStore.reserve_and_record_lease):
            return VerificationResult(False, STORE_UNAVAILABLE,
                                      "durable atomic lease commit is unsupported")
        try:
            reservation = reserve_lease(
                receipt_id, nonce, request_id, receipt["action_digest"], receipt["target"],
                receipt["capability"], receipt["parameters"], now, lease_expires_at,
                operation_limit,
            )
        except (NotImplementedError, TypeError, OSError):
            return VerificationResult(False, STORE_UNAVAILABLE,
                                      "durable atomic lease commit failed")
        if reservation not in (ReservationOutcome.RESERVED, ReservationOutcome.COMMITTED):
            return VerificationResult(
                success=False,
                category=(STORE_UNAVAILABLE if reservation is ReservationOutcome.AUDIT_UNAVAILABLE
                          else REPLAY_DETECTED),
                reason=("failed to durably record receipt-verification event"
                        if reservation is ReservationOutcome.AUDIT_UNAVAILABLE
                        else "replay detected"),
            )
    return VerificationResult(
        success=True,
        category=VERIFIED,
        reason="receipt verified; lease issued",
        lease_id=lease_id,
        receipt_id=receipt["receipt_id"],
        action_digest=receipt["action_digest"],
    )


__all__ = [
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_VALIDITY_MINUTES",
    "VerificationCategory",
    "VerificationResult",
    "ReservationOutcome",
    "OperationOutcome",
    "LeaseState",
    "Lease",
    "AuditEvent",
    "LeaseAuthority",
    "KeyStore",
    "ApproverPolicy",
    "ApprovalStore",
    "Clock",
    "verify_approval_receipt",
    # Category aliases
    "VERIFIED",
    "VERIFICATION_FAILED",
    "INVALID_SIGNATURE",
    "UNKNOWN_ISSUER",
    "AUDIENCE_MISMATCH",
    "EXPIRED",
    "REPLAY_DETECTED",
    "ACTION_MISMATCH",
    "POLICY_DENIED",
    "STORE_UNAVAILABLE",
]
