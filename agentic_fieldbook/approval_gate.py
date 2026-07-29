"""Deployment-neutral, fail-closed approval-gate adapter contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .receipt import canonical_digest


class ApprovalOutcome(str, Enum):
    CREATED = "created"
    PRESENTED = "presented"
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"
    UNAUTHENTICATED = "unauthenticated"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


# Only this module can mint a provider assertion.  It is intentionally not a
# subject record: a subject name, dataclass, or bearer string is never proof.
_ASSERTION_SEAL = object()


class HumanAuthenticationAssertion:
    """Provider-issued opaque proof, bound to one request, audience and expiry.

    Adapters should receive this from their authentication provider and pass it
    through unchanged.  The public decision seam rejects strings, subject
    records, and arbitrary look-alikes.
    """
    __slots__ = ("_seal", "_request_id", "_audience", "_expires_at", "_subject")

    def __init__(self, seal: object, request_id: str, audience: str,
                 expires_at: str, subject_ref: str):
        if seal is not _ASSERTION_SEAL:
            raise TypeError("assertions are provider-issued opaque values")
        self._seal = seal
        self._request_id = request_id
        self._audience = audience
        self._expires_at = expires_at
        self._subject = subject_ref

    @property
    def subject_ref(self) -> str:
        return self._subject

    def is_bound_to(self, request_id: str, audience: str, now: datetime | None = None) -> bool:
        if request_id != self._request_id or audience != self._audience:
            return False
        try:
            expiry = _parse_timestamp(self._expires_at)
        except (TypeError, ValueError):
            return False
        current = now or datetime.now(timezone.utc)
        return current <= expiry


def provider_assertion(request_id: str, audience: str, expires_at: str, subject_ref: str) -> HumanAuthenticationAssertion:
    """Adapter-only minting hook for a deployment provider integration.

    This preserves deployment neutrality: the integration supplies the already
    authenticated subject and controls how that proof was obtained.
    """
    return HumanAuthenticationAssertion(_ASSERTION_SEAL, request_id, audience, expires_at, subject_ref)


@dataclass(frozen=True)
class AuthenticatedHumanSubject:
    """Legacy descriptive data; deliberately not accepted as authentication proof."""
    subject_ref: str
    auth_context: str


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return deepcopy(value)


def _thaw(value: Any) -> Any:
    """Restore immutable presentation containers for the canonical encoder."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ActionPackage:
    """Action presentation. ``contract_digest`` is a declaration, not input to its proof."""
    contract_digest: str
    target: Mapping[str, Any]
    capability: str
    parameters: Mapping[str, Any]
    lease_ttl: int
    operation_limit: int
    verification_method: str
    rollback: Any
    abort_conditions: Any
    approval_expires_at: str

    def as_mapping(self) -> dict[str, Any]:
        return {
            "contract_digest": self.contract_digest,
            "target": deepcopy(dict(self.target)),
            "capability": self.capability,
            "parameters": deepcopy(dict(self.parameters)),
            "lease_ttl": self.lease_ttl,
            "operation_limit": self.operation_limit,
            "verification_method": self.verification_method,
            "rollback": deepcopy(self.rollback),
            "abort_conditions": deepcopy(self.abort_conditions),
            "approval_expires_at": self.approval_expires_at,
        }

    def canonical_action(self) -> dict[str, Any]:
        """The one authoritative digest domain: all action fields except the declaration."""
        result = self.as_mapping()
        result.pop("contract_digest")
        return result

    def digest(self) -> str:
        return canonical_digest(self.canonical_action())


def validate_action_package(action_package: ActionPackage) -> list[str]:
    if not isinstance(action_package, ActionPackage):
        return ["action_package must be an ActionPackage"]
    errors: list[str] = []
    if not isinstance(action_package.contract_digest, str) or not action_package.contract_digest.strip():
        errors.append("contract_digest must be a non-empty string")
    if action_package.contract_digest != action_package.digest():
        errors.append("contract_digest does not match canonical action digest")
    if not isinstance(action_package.target, Mapping) or not action_package.target:
        errors.append("target is required")
    if not isinstance(action_package.capability, str) or not action_package.capability.strip():
        errors.append("capability is required")
    if type(action_package.lease_ttl) is not int or action_package.lease_ttl < 1:
        errors.append("lease_ttl must be an integer >= 1")
    if type(action_package.operation_limit) is not int or action_package.operation_limit < 1:
        errors.append("operation_limit must be an integer >= 1")
    if not isinstance(action_package.verification_method, str) or not action_package.verification_method.strip():
        errors.append("verification_method is required")
    try:
        _parse_timestamp(action_package.approval_expires_at)
    except (TypeError, ValueError):
        errors.append("approval_expires_at must be a timezone-aware ISO-8601 timestamp")
    return errors


def validate_presentation(action_package: Mapping[str, Any], action_digest: str) -> bool:
    """Re-hash an immutable presentation immediately before recording a decision."""
    if not isinstance(action_package, Mapping) or not isinstance(action_digest, str):
        return False
    declared = action_package.get("contract_digest")
    if not isinstance(declared, str) or declared != action_digest:
        return False
    candidate = _thaw(action_package)
    candidate.pop("contract_digest", None)
    try:
        return canonical_digest(candidate) == action_digest
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class RequesterContext:
    requester_ref: str
    audience: str
    idempotency_key: str


@dataclass(frozen=True)
class ApprovalRequest:
    approval_request_id: str
    action_digest: str
    action_package: Mapping[str, Any]
    requester_ref: str
    audience: str
    expires_at: str
    outcome: ApprovalOutcome = ApprovalOutcome.PENDING
    idempotency_key: str = ""


@dataclass(frozen=True)
class PresentationResult:
    outcome: ApprovalOutcome
    approval_request_id: str
    action_digest: str
    action_package: Mapping[str, Any] | None = None
    presentation_ref: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ApprovalReceipt:
    """Typed receipt boundary; payload excludes channel credentials and secrets."""
    receipt_version: str
    receipt_id: str
    approval_request_id: str
    action_digest: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.receipt_version != "1":
            raise ValueError("unsupported receipt version")
        object.__setattr__(self, "payload", _freeze(self.payload))


@dataclass(frozen=True)
class DecisionResult:
    outcome: ApprovalOutcome
    approval_request_id: str
    action_digest: str | None = None
    receipt: ApprovalReceipt | None = None
    issuer_subject_ref: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class RevocationResult:
    outcome: ApprovalOutcome
    receipt_id: str
    reason: str = ""


class ApprovalGateAdapter(ABC):
    """Deployment-neutral seam. Implementations MUST use an atomic store transaction.

    The idempotency key is scoped to requester/audience. Existing key + same
    canonical digest returns the original request; existing key + different
    digest returns IDEMPOTENCY_CONFLICT. Neither decision may be inferred from
    an ambiguous write. ``present`` must return immutable data/reference and
    ``record_decision`` must call validate_presentation before issuing a receipt.
    """
    @abstractmethod
    def create_request(self, action_package: ActionPackage, requester_context: RequesterContext) -> ApprovalRequest: ...

    @abstractmethod
    def present(self, request_id: str) -> PresentationResult: ...

    @abstractmethod
    def record_decision(self, request_id: str, decision: str,
                        authenticated_subject: HumanAuthenticationAssertion | None) -> DecisionResult: ...

    @abstractmethod
    def revoke(self, receipt_id: str, actor: HumanAuthenticationAssertion | None,
               reason: str) -> RevocationResult: ...


class ReceiptIssuer(Protocol):
    def issue(self, request: ApprovalRequest, subject: HumanAuthenticationAssertion) -> ApprovalReceipt: ...
