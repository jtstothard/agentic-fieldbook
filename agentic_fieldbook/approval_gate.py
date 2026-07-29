"""Deployment-neutral approval-gate adapter contract.

This module defines the Fieldbook seam for native human approval. It contains
no channel, identity-provider, signing-key, or deployment configuration. A
deployment owns authentication, presentation delivery, durable storage, and
receipt signing behind this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from .receipt import canonical_digest


class ApprovalOutcome(str, Enum):
    """Safe, explicit outcomes returned by an approval adapter."""

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


@dataclass(frozen=True)
class AuthenticatedHumanSubject:
    """Opaque result of deployment-controlled human authentication.

    ``subject_ref`` is a deployment-approved pseudonymous reference.  It is
    deliberately not accepted as a string by ``record_decision``: the adapter
    must receive an authentication result produced independently of the
    requester's identity.  ``auth_context`` is metadata, not a secret or token.
    """

    subject_ref: str
    auth_context: str


@dataclass(frozen=True)
class ActionPackage:
    """The exact immutable action package shown to the human approver."""

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
        """Return a detached mapping suitable for presentation and hashing."""
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

    def digest(self) -> str:
        """Compute the deterministic digest of the complete action package."""
        return canonical_digest(self.as_mapping())


def validate_action_package(action_package: ActionPackage) -> list[str]:
    """Return safe, deterministic malformed-package reasons."""
    errors: list[str] = []
    if not isinstance(action_package, ActionPackage):
        return ["action_package must be an ActionPackage"]
    if not action_package.contract_digest:
        errors.append("contract_digest is required")
    if not action_package.target:
        errors.append("target is required")
    if not action_package.capability.strip():
        errors.append("capability is required")
    if action_package.lease_ttl < 1:
        errors.append("lease_ttl must be >= 1")
    if action_package.operation_limit < 1:
        errors.append("operation_limit must be >= 1")
    if not action_package.verification_method.strip():
        errors.append("verification_method is required")
    if not action_package.approval_expires_at.strip():
        errors.append("approval_expires_at is required")
    return errors


@dataclass(frozen=True)
class RequesterContext:
    """Deployment-neutral request context with an explicit retry key."""

    requester_ref: str
    audience: str
    idempotency_key: str


@dataclass(frozen=True)
class ApprovalRequest:
    """Immutable request identity and exact presentation binding."""

    approval_request_id: str
    action_digest: str
    action_package: Mapping[str, Any]
    requester_ref: str
    audience: str
    expires_at: str
    outcome: ApprovalOutcome = ApprovalOutcome.PENDING


@dataclass(frozen=True)
class PresentationResult:
    outcome: ApprovalOutcome
    approval_request_id: str
    action_digest: str
    action_package: Mapping[str, Any] | None = None
    presentation_ref: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class DecisionResult:
    outcome: ApprovalOutcome
    approval_request_id: str
    action_digest: str | None = None
    receipt: Mapping[str, Any] | None = None
    issuer_subject_ref: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class RevocationResult:
    outcome: ApprovalOutcome
    receipt_id: str
    reason: str = ""


class ApprovalGateAdapter(ABC):
    """Deployment-neutral approval-gate boundary.

    Implementations must make ``create_request`` idempotent for the same
    requester idempotency key and immutable action package.  A changed package
    must receive a new request.  ``authenticated_subject`` must be an
    authentication-provider result, never a caller-supplied issuer string.
    """

    @abstractmethod
    def create_request(
        self, action_package: ActionPackage, requester_context: RequesterContext
    ) -> ApprovalRequest:
        """Create or return the stable request for an idempotent retry."""
        raise NotImplementedError

    @abstractmethod
    def present(self, request_id: str) -> PresentationResult:
        """Expose the exact package or immutable reference for presentation."""
        raise NotImplementedError

    @abstractmethod
    def record_decision(
        self,
        request_id: str,
        decision: str,
        authenticated_subject: AuthenticatedHumanSubject | None,
    ) -> DecisionResult:
        """Record an independently authenticated human decision."""
        raise NotImplementedError

    @abstractmethod
    def revoke(self, receipt_id: str, actor: AuthenticatedHumanSubject | None, reason: str) -> RevocationResult:
        """Revoke an issued receipt without silently changing its history."""
        raise NotImplementedError


class ReceiptIssuer(Protocol):
    """Deployment-owned receipt signer used by an adapter implementation."""

    def issue(self, request: ApprovalRequest, subject: AuthenticatedHumanSubject) -> Mapping[str, Any]: ...
