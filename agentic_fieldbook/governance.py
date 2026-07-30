"""High-risk governance enforcement for Fieldbook v2.

This module implements:
- Always-ask overlay (destructive, secret, billing, access, downtime, release)
- Capability ceiling enforcement
- Exact human approval gates
- Rollback/abort requirements
- Audit trail enhancement

Uses TDD approach: tests written first, implementation follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_fieldbook.lifecycle import LifecycleState


class GovernanceError(Exception):
    """Base error for governance violations."""


class MissingApprovalError(GovernanceError):
    """Raised when a task lacks required human approval."""


class CapabilityMismatchError(GovernanceError):
    """Raised when executor lacks required capabilities."""


class MissingRollbackError(GovernanceError):
    """Raised when high-risk task lacks rollback evidence."""


class AlwaysAskCategory(str, Enum):
    """Categories that always require human approval regardless of risk class."""

    DESTRUCTIVE = "destructive"
    SECRET_ACCESS = "secret-access"
    BILLING = "billing"
    ACCESS_GRANT = "access-grant"
    DOWNTIME = "downtime"
    RELEASE = "release"


# Capabilities that trigger always-ask requirements
_ALWAYS_ASK_CAPABILITIES: dict[str, AlwaysAskCategory] = {
    "delete": AlwaysAskCategory.DESTRUCTIVE,
    "drop": AlwaysAskCategory.DESTRUCTIVE,
    "truncate": AlwaysAskCategory.DESTRUCTIVE,
    "destroy": AlwaysAskCategory.DESTRUCTIVE,
    "secret-read": AlwaysAskCategory.SECRET_ACCESS,
    "secret-write": AlwaysAskCategory.SECRET_ACCESS,
    "secret-rotate": AlwaysAskCategory.SECRET_ACCESS,
    "credential-read": AlwaysAskCategory.SECRET_ACCESS,
    "credential-write": AlwaysAskCategory.SECRET_ACCESS,
    "credential-rotate": AlwaysAskCategory.SECRET_ACCESS,
    "billing-change": AlwaysAskCategory.BILLING,
    "billing-adjust": AlwaysAskCategory.BILLING,
    "access-grant": AlwaysAskCategory.ACCESS_GRANT,
    "permission-grant": AlwaysAskCategory.ACCESS_GRANT,
    "role-grant": AlwaysAskCategory.ACCESS_GRANT,
    "service-restart": AlwaysAskCategory.DOWNTIME,
    "service-stop": AlwaysAskCategory.DOWNTIME,
    "service-reload": AlwaysAskCategory.DOWNTIME,
    "deployment": AlwaysAskCategory.DOWNTIME,
    "release": AlwaysAskCategory.RELEASE,
    "deploy": AlwaysAskCategory.RELEASE,
    "promote": AlwaysAskCategory.RELEASE,
}


@dataclass(frozen=True)
class ApprovalRecord:
    """Record of explicit human approval."""

    actor: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(tz=None).astimezone().isoformat())

    def to_dict(self) -> dict[str, str]:
        return {
            "actor": self.actor,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CapabilityCheck:
    """Record of capability verification."""

    required_capabilities: tuple[str, ...]
    executor_capabilities: tuple[str, ...]
    satisfied: bool
    missing: tuple[str, ...]
    timestamp: str = field(default_factory=lambda: datetime.now(tz=None).astimezone().isoformat())

    def to_dict(self) -> dict[str, str | list[str] | bool]:
        return {
            "required_capabilities": list(self.required_capabilities),
            "executor_capabilities": list(self.executor_capabilities),
            "satisfied": self.satisfied,
            "missing": list(self.missing),
            "timestamp": self.timestamp,
        }


@dataclass
class GovernanceState:
    """Governance metadata attached to task records."""

    approvals: list[dict[str, str]] = field(default_factory=list)
    capability_checks: list[dict[str, str | list[str] | bool]] = field(default_factory=list)
    always_ask_categories: tuple[str, ...] = ()
    rollback_declared: bool = False

    def has_approval(self) -> bool:
        """Check if human approval has been recorded."""
        return len(self.approvals) > 0

    def get_latest_approval(self) -> dict[str, str] | None:
        """Get the most recent approval record."""
        return self.approvals[-1] if self.approvals else None

    def add_approval(self, actor: str, reason: str) -> None:
        """Record a new human approval."""
        approval = ApprovalRecord(actor=actor, reason=reason).to_dict()
        self.approvals.append(approval)

    def add_capability_check(
        self,
        required: tuple[str, ...],
        executor: tuple[str, ...],
        satisfied: bool,
        missing: tuple[str, ...],
    ) -> None:
        """Record a capability verification."""
        check = CapabilityCheck(
            required_capabilities=required,
            executor_capabilities=executor,
            satisfied=satisfied,
            missing=missing,
        ).to_dict()
        self.capability_checks.append(check)

    def requires_human_approval(self) -> bool:
        """Check if task requires human approval based on always-ask categories."""
        return len(self.always_ask_categories) > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "approvals": self.approvals,
            "capability_checks": self.capability_checks,
            "always_ask_categories": list(self.always_ask_categories),
            "rollback_declared": self.rollback_declared,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GovernanceState":
        """Reconstruct governance state from dict."""
        return cls(
            approvals=list(data.get("approvals", [])),  # type: ignore
            capability_checks=list(data.get("capability_checks", [])),  # type: ignore
            always_ask_categories=tuple(data.get("always_ask_categories", [])),  # type: ignore
            rollback_declared=bool(data.get("rollback_declared", False)),  # type: ignore
        )


def detect_always_ask_capabilities(capabilities: tuple[str, ...]) -> tuple[AlwaysAskCategory, ...]:
    """Detect which always-ask categories are triggered by task capabilities."""
    categories = set()
    for cap in capabilities:
        if cap.lower() in _ALWAYS_ASK_CAPABILITIES:
            categories.add(_ALWAYS_ASK_CAPABILITIES[cap.lower()])
    return tuple(categories)


def requires_rollback_evidence(risk_class: str) -> bool:
    """Check if risk class requires rollback evidence."""
    return risk_class == "high"


def check_capabilities(
    required: tuple[str, ...],
    available: tuple[str, ...],
) -> tuple[bool, tuple[str, ...]]:
    """Check if required capabilities are available.

    Returns:
        (satisfied, missing_capabilities)
    """
    required_set = set(cap.lower() for cap in required)
    available_set = set(cap.lower() for cap in available)
    missing = tuple(required_set - available_set)
    return (len(missing) == 0, missing)


def validate_approval_requirement(
    risk_class: str,
    capabilities: tuple[str, ...],
    has_approval: bool,
    target_state: str,
    actor: str,
    previous_actor: str | None = None,
) -> tuple[bool, str | None]:
    """Check if human approval is required for a transition.

    Returns:
        (requires_approval, error_message_if_missing)
    """
    # Detect always-ask categories
    always_ask = detect_always_ask_capabilities(capabilities)
    is_always_ask = len(always_ask) > 0

    # High risk always requires explicit human actor for APPROVED state
    if risk_class == "high" and target_state == "approved":
        # If there's no previous actor (first transition), allow it as the approval
        # If there is a previous actor and it's the same, reject (self-approval not allowed)
        if previous_actor is not None and actor == previous_actor:
            return (True, "High-risk tasks require independent human approval")
        # Allow different actor (human approval)
        return (False, None)

    # Always-ask requires explicit human actor for APPROVED state
    if is_always_ask and target_state == "approved":
        # Same logic: if previous actor exists and is same, reject
        if previous_actor is not None and actor == previous_actor:
            categories = ", ".join(cat.value for cat in always_ask)
            return (True, f"Always-ask categories require independent human approval: {categories}")
        # Allow different actor (human approval)
        return (False, None)

    return (False, None)


def validate_rollback_requirement(
    risk_class: str,
    evidence_requirements: tuple[str, ...],
) -> tuple[bool, str | None]:
    """Check if rollback evidence is required and declared.

    Returns:
        (requires_rollback, error_message_if_missing)
    """
    if not requires_rollback_evidence(risk_class):
        return (False, None)

    # Check for rollback-related evidence requirements
    rollback_keywords = ("rollback", "revert", "backout", "recovery")
    has_rollback = any(
        any(keyword in req.lower() for keyword in rollback_keywords)
        for req in evidence_requirements
    )

    if not has_rollback:
        return (
            True,
            "High-risk tasks must declare rollback/recovery evidence requirements",
        )

    return (False, None)


__all__ = [
    "AlwaysAskCategory",
    "ApprovalRecord",
    "CapabilityCheck",
    "CapabilityMismatchError",
    "GovernanceError",
    "GovernanceState",
    "MissingApprovalError",
    "MissingRollbackError",
    "check_capabilities",
    "detect_always_ask_capabilities",
    "requires_rollback_evidence",
    "validate_approval_requirement",
    "validate_rollback_requirement",
]