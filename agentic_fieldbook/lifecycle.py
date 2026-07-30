"""Fieldbook v1 universal task lifecycle and portable record seam.

The module deliberately contains no storage backend. ``CanonicalTaskRecord`` is
plain data plus the lifecycle/evidence invariants, so it can be persisted as
JSON by any harness or adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Any, Iterable, Mapping

from .governance import (
    CapabilityMismatchError,
    GovernanceState,
    MissingApprovalError,
    MissingRollbackError,
    detect_always_ask_capabilities,
    requires_rollback_evidence,
    validate_approval_requirement,
    validate_rollback_requirement,
)


class LifecycleState(str, Enum):
    PROPOSED = "proposed"
    PLANNED = "planned"
    APPROVED = "approved"
    EXECUTING = "executing"
    REPORTED_COMPLETE = "reported_complete"
    REVIEW = "review"
    VERIFICATION = "verification"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class LifecycleError(ValueError):
    """Base error for violations of the Fieldbook lifecycle interface."""


class InvalidTransitionError(LifecycleError):
    """Raised when a record attempts a transition not allowed by the contract."""


class MissingEvidenceError(LifecycleError):
    """Raised when verification lacks a required evidence item."""


@dataclass(frozen=True)
class TaskContract:
    """Small universal contract shared by all Fieldbook v1 records.

    Tuples make the contract immutable after creation; ``to_dict`` converts it
    into portable JSON-shaped data. Domain-specific fields belong in extensions
    and do not alter the universal lifecycle.
    """

    contract_id: str
    objective: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    risk_class: str
    capabilities: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required_evidence: tuple[str, ...]
    domain: str = ""
    revision: int = 1

    def __post_init__(self) -> None:
        for name in ("contract_id", "objective", "risk_class"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.risk_class not in {"low", "medium", "high"}:
            raise ValueError("risk_class must be low, medium, or high")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        for name in (
            "scope", "exclusions", "capabilities", "acceptance_criteria", "required_evidence"
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} must be a tuple of non-empty strings")

        # Validate high-risk contracts have rollback requirements
        if self.risk_class == "high":
            rollback_keywords = ("rollback", "revert", "backout", "recovery")
            has_rollback = any(
                any(keyword in req.lower() for keyword in rollback_keywords)
                for req in self.required_evidence
            )
            if not has_rollback:
                raise ValueError(
                    "High-risk contracts must declare rollback/recovery evidence requirements"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "revision": self.revision,
            "objective": self.objective,
            "scope": list(self.scope),
            "exclusions": list(self.exclusions),
            "risk_class": self.risk_class,
            "capabilities": list(self.capabilities),
            "acceptance_criteria": list(self.acceptance_criteria),
            "required_evidence": list(self.required_evidence),
            "domain": self.domain,
        }


@dataclass(frozen=True)
class Evidence:
    """Portable evidence item identified by the contract requirement it covers."""

    requirement: str
    claim: str
    tool: str
    result: str
    passed: bool = True

    def __post_init__(self) -> None:
        for name in ("requirement", "claim", "tool", "result"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "claim": self.claim,
            "tool": self.tool,
            "result": self.result,
            "passed": self.passed,
        }


_FORWARD_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.PROPOSED: frozenset({LifecycleState.PLANNED}),
    LifecycleState.PLANNED: frozenset({LifecycleState.APPROVED}),
    LifecycleState.APPROVED: frozenset({LifecycleState.EXECUTING}),
    LifecycleState.EXECUTING: frozenset({LifecycleState.REPORTED_COMPLETE}),
    LifecycleState.REPORTED_COMPLETE: frozenset({LifecycleState.REVIEW}),
    LifecycleState.REVIEW: frozenset({LifecycleState.VERIFICATION, LifecycleState.EXECUTING}),
    LifecycleState.VERIFICATION: frozenset({LifecycleState.VERIFIED, LifecycleState.EXECUTING, LifecycleState.REVIEW}),
    # Recovery transitions from side states
    LifecycleState.BLOCKED: frozenset({LifecycleState.PLANNED}),
}
# Explicit side transition table: which source states can go to which side states
_SIDE_TRANSITION_TABLE: dict[LifecycleState, frozenset[LifecycleState]] = {
    # Any primary state may be stopped by governance or execution failure.
    LifecycleState.PROPOSED: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    LifecycleState.PLANNED: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    LifecycleState.APPROVED: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    LifecycleState.EXECUTING: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    # Every non-terminal primary state can enter blocker/failure side states.
    # reported_complete is only a claim, so review/verification may still reject it.
    LifecycleState.REPORTED_COMPLETE: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    LifecycleState.REVIEW: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
    LifecycleState.VERIFICATION: frozenset({LifecycleState.BLOCKED, LifecycleState.FAILED, LifecycleState.CANCELLED, LifecycleState.SUPERSEDED}),
}
_TERMINAL_STATES = frozenset({
    LifecycleState.VERIFIED,
    LifecycleState.FAILED,
    LifecycleState.CANCELLED,
    LifecycleState.SUPERSEDED,
})


def _state(value: LifecycleState | str) -> LifecycleState:
    try:
        return value if isinstance(value, LifecycleState) else LifecycleState(value)
    except ValueError as exc:
        raise InvalidTransitionError(f"unknown lifecycle state: {value!r}") from exc


def _evidence_item(value: Evidence | Mapping[str, Any]) -> Evidence:
    if isinstance(value, Evidence):
        return value
    if isinstance(value, Mapping):
        passed = value.get("passed", True)
        if not isinstance(passed, bool):
            raise ValueError("passed must be bool")
        return Evidence(
            requirement=value["requirement"],
            claim=value["claim"],
            tool=value["tool"],
            result=value["result"],
            passed=passed,
        )
    raise TypeError("evidence must contain Evidence or mapping values")


@dataclass
class CanonicalTaskRecord:
    """Portable task record enforcing lifecycle transitions at one public seam."""

    contract: TaskContract
    task_id: str
    _state: LifecycleState = field(default=LifecycleState.PROPOSED, init=False, repr=False)
    _history: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _evidence: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _governance: GovernanceState = field(default_factory=GovernanceState, init=False, repr=False)
    _provenance: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _approval_epoch: int = field(default=0, init=False, repr=False)
    _recovery_attempt: int = field(default=0, init=False, repr=False)
    _approval_receipt_id: str | None = field(default=None, init=False, repr=False)
    _approval_contract_digest: str | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(cls, contract: TaskContract, *, task_id: str) -> "CanonicalTaskRecord":
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        record = cls(contract=contract, task_id=task_id)

        # Initialize governance state with always-ask categories
        always_ask = detect_always_ask_capabilities(contract.capabilities)
        record._governance.always_ask_categories = tuple(cat.value for cat in always_ask)
        record._governance.rollback_declared = requires_rollback_evidence(contract.risk_class)

        return record

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def history(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._history)

    @property
    def evidence(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._evidence)

    @property
    def approval_epoch(self) -> int:
        return self._approval_epoch

    @property
    def recovery_attempt(self) -> int:
        return self._recovery_attempt

    def bind_approval_receipt(self, *, receipt_id: str, contract_digest: str,
                              epoch: int, recovery_attempt: int) -> None:
        """Bind broker-validated approval to this exact recovery attempt."""
        if (epoch != self._approval_epoch or recovery_attempt != self._recovery_attempt
                or not receipt_id or not contract_digest):
            raise InvalidTransitionError("approval receipt is stale for this recovery attempt")
        self._approval_receipt_id = receipt_id
        self._approval_contract_digest = contract_digest

    def approval_receipt_is_current(self, *, receipt_id: str, contract_digest: str) -> bool:
        return (receipt_id == self._approval_receipt_id
                and contract_digest == self._approval_contract_digest)

    @property
    def has_current_approval_binding(self) -> bool:
        return bool(self._approval_receipt_id and self._approval_contract_digest)

    def transition(
        self,
        target: LifecycleState | str,
        *,
        actor: str,
        reason: str = "",
        evidence: Iterable[Evidence | Mapping[str, Any]] = (),
        executor_capabilities: tuple[str, ...] | None = None,
    ) -> None:
        target_state = _state(target)
        if not actor or not actor.strip():
            raise ValueError("actor must be a non-empty string")

        # Check forward transitions
        allowed = _FORWARD_TRANSITIONS.get(self.state, frozenset())
        if target_state in allowed:
            valid = True
        # Check side transitions using explicit table
        elif target_state in _SIDE_TRANSITION_TABLE.get(self.state, frozenset()):
            valid = True
        else:
            valid = False

        if not valid:
            raise InvalidTransitionError(f"cannot transition from {self._state.value} to {target_state.value}")

        # Governance checks
        previous_actor = self._history[-1]["actor"] if self._history else None
        requires_approval, approval_error = validate_approval_requirement(
            self.contract.risk_class,
            self.contract.capabilities,
            self._governance.has_approval(),
            target_state.value,
            actor,
            previous_actor,
        )

        if requires_approval:
            raise InvalidTransitionError(approval_error or "Human approval required")

        # Capability ceiling enforcement at first APPROVED → EXECUTING gate
        if target_state is LifecycleState.EXECUTING and self.state is LifecycleState.APPROVED:
            if self.contract.capabilities:
                if executor_capabilities is None:
                    raise InvalidTransitionError("executor_capabilities required")

                from .governance import check_capabilities

                satisfied, missing = check_capabilities(
                    self.contract.capabilities,
                    executor_capabilities,
                )

                self._governance.add_capability_check(
                    required=self.contract.capabilities,
                    executor=executor_capabilities,
                    satisfied=satisfied,
                    missing=missing,
                )

                if not satisfied:
                    raise CapabilityMismatchError(
                        f"Executor lacks required capabilities: {', '.join(missing)}"
                    )

            # Approval defense-in-depth: check executor != approver for high-risk and always-ask
            if self.contract.risk_class == "high" or self._governance.requires_human_approval():
                # Find who approved this task (the actor in the APPROVED transition)
                approver_actor = None
                for h in self._history:
                    if h["to"] == LifecycleState.APPROVED.value:
                        approver_actor = h["actor"]
                        break

                # Block if same actor approved and executes
                if approver_actor is not None and actor == approver_actor:
                    raise InvalidTransitionError(
                        "executor must differ from approver for high-risk and always-ask tasks"
                    )

        # Record human approval when transitioning to APPROVED with approval metadata
        if target_state is LifecycleState.APPROVED:
            # Check if this is a human approval (not auto-approval)
            # We consider it an approval if the actor differs from previous state's actor
            # or if reason contains approval-related keywords
            if self._history and self._history[-1]["actor"] != actor:
                self._governance.add_approval(actor, reason or "Transition to APPROVED")
            elif self._governance.requires_human_approval():
                # For always-ask or high-risk, record approval
                self._governance.add_approval(actor, reason or "Human approval for high-risk/always-ask task")

        additions = [_evidence_item(item) for item in evidence]

        # Check rollback requirements for high-risk FAILED transitions
        if target_state is LifecycleState.FAILED and self.contract.risk_class == "high":
            rollback_keywords = ("rollback", "revert", "backout", "recovery")
            has_rollback = any(
                any(keyword in item.get("requirement", "").lower() for keyword in rollback_keywords)
                for item in self._evidence
            ) or any(
                any(keyword in item.requirement.lower() for keyword in rollback_keywords)
                for item in additions
            )
            if not has_rollback:
                raise MissingRollbackError(
                    "High-risk tasks that fail must provide rollback evidence"
                )

        # Track executor actor for verifier independence check
        executor_actor: str | None = None
        for h in self._history:
            if h["to"] == LifecycleState.EXECUTING.value:
                executor_actor = h["actor"]
                break

        if target_state is LifecycleState.VERIFIED:
            # Check verifier independence for medium/high risk
            if self.contract.risk_class in {"medium", "high"}:
                if executor_actor is not None and actor == executor_actor:
                    raise InvalidTransitionError("verifier must differ from executor for medium and high risk tasks")

            available = {
                item["requirement"]: item
                for item in self._evidence
                if item.get("passed", True)
            }
            available.update(
                (item.requirement, item.to_dict())
                for item in additions
                if item.passed
            )

            # Check required_evidence
            missing_evidence = [item for item in self.contract.required_evidence if item not in available]
            if missing_evidence:
                raise MissingEvidenceError("missing required evidence: " + ", ".join(missing_evidence))

            # Check acceptance_criteria (Issue 1)
            missing_criteria = [item for item in self.contract.acceptance_criteria if item not in available]
            if missing_criteria:
                raise MissingEvidenceError("missing acceptance criteria: " + ", ".join(missing_criteria))

        self._evidence.extend(item.to_dict() for item in additions)
        self._history.append({
            "from": self._state.value,
            "to": target_state.value,
            "actor": actor,
            "reason": reason,
            "timestamp": datetime.now(tz=None).astimezone().isoformat(),
        })
        self._state = target_state
        if target_state in {LifecycleState.BLOCKED, LifecycleState.FAILED}:
            # Side-state recovery starts a new authorization epoch. Prior
            # receipts and approvals are never valid for the next attempt.
            self._approval_epoch += 1
            self._recovery_attempt += 1
            self._approval_receipt_id = None
            self._approval_contract_digest = None
            self._governance.approvals.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "fieldbook.task-record.v1",
            "task_id": self.task_id,
            "contract": self.contract.to_dict(),
            "state": self._state.value,
            "history": [dict(item) for item in self._history],
            "evidence": [dict(item) for item in self._evidence],
            "governance": self._governance.to_dict(),
            "provenance": dict(self._provenance),
            "approval_epoch": self._approval_epoch,
            "recovery_attempt": self._recovery_attempt,
            "approval_receipt_id": self._approval_receipt_id,
            "approval_contract_digest": self._approval_contract_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalTaskRecord":
        """Reconstruct a record from its portable representation."""
        if data.get("schema") != "fieldbook.task-record.v1":
            raise ValueError("unsupported schema version")

        contract = TaskContract(
            contract_id=data["contract"]["contract_id"],
            objective=data["contract"]["objective"],
            scope=tuple(data["contract"]["scope"]),
            exclusions=tuple(data["contract"]["exclusions"]),
            risk_class=data["contract"]["risk_class"],
            capabilities=tuple(data["contract"]["capabilities"]),
            acceptance_criteria=tuple(data["contract"]["acceptance_criteria"]),
            required_evidence=tuple(data["contract"]["required_evidence"]),
            domain=data["contract"].get("domain", ""),
            revision=data["contract"].get("revision", 1),
        )

        record = cls.create(contract, task_id=data["task_id"])
        record._state = LifecycleState(data["state"])

        # Validate evidence through _evidence_item to ensure type safety
        validated_evidence = []
        for item in data.get("evidence", []):
            validated_evidence.append(_evidence_item(item).to_dict())
        record._evidence = validated_evidence

        record._history = [dict(item) for item in data.get("history", [])]

        # Restore governance state if present (backward compatible)
        if "governance" in data:
            record._governance = GovernanceState.from_dict(data["governance"])
        if "provenance" in data:
            if not isinstance(data["provenance"], dict):
                raise ValueError("provenance must be an object")
            record._provenance = dict(data["provenance"])
        for field_name in ("approval_epoch", "recovery_attempt"):
            value = data.get(field_name, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
            setattr(record, f"_{field_name}", value)
        receipt_id = data.get("approval_receipt_id")
        digest = data.get("approval_contract_digest")
        if receipt_id is not None and (not isinstance(receipt_id, str) or not receipt_id.strip()):
            raise ValueError("approval_receipt_id must be a non-empty string or null")
        if digest is not None and (not isinstance(digest, str)
                                   or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
            raise ValueError("approval_contract_digest must be a sha256:<64 hex characters> digest or null")
        if (receipt_id is None) != (digest is None):
            raise ValueError("approval receipt binding must contain both receipt_id and contract_digest")
        record._approval_receipt_id = receipt_id
        record._approval_contract_digest = digest

        return record


__all__ = [
    "CanonicalTaskRecord",
    "Evidence",
    "InvalidTransitionError",
    "LifecycleError",
    "LifecycleState",
    "MissingEvidenceError",
    "TaskContract",
]
