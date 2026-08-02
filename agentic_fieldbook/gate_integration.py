"""Lifecycle gate integration: wire gate evaluator + light-gate into PLANNED -> APPROVED.

This module is the orchestrator seam that calls the gate evaluator (issue #59)
before attempting the PLANNED -> APPROVED transition, then routes based on the
evaluated disposition:

- ``autonomous`` / ``report_only``: proceed directly (existing logic, unchanged).
- ``gate_heavy``: signal the caller to use the existing ``ApprovalGateAdapter``
  + broker path (issue #57, unchanged).
- ``gate_light``: create a ``LightGateRequest``, block the task until a
  ``LightGateDecision`` is recorded, then resume to APPROVED or CANCELLED.

The evaluator is called HERE, not inside ``CanonicalTaskRecord``.  The record
only enforces transition rules; this coordinator decides which transition to
attempt.  This preserves the architectural separation described in issue #58.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .gate_evaluator import (
    GateDecision,
    GateDisposition,
    GateLearningStore,
    GateTask,
    evaluate_gate,
)
from .lifecycle import CanonicalTaskRecord, LifecycleState
from .light_gate import (
    LightGateAdapter,
    LightGateDecision,
    LightGateOutcome,
    LightGateRequest,
)


class GateRouteAction(str, Enum):
    """What the orchestrator should do after evaluating the disposition."""

    PROCEED_TO_APPROVED = "proceed"      # autonomous / report_only
    USE_HEAVY_GATE = "heavy"             # gate_heavy -- existing broker path
    BLOCKED_FOR_LIGHT_GATE = "light"     # gate_light -- blocked, awaiting decision


@dataclass(frozen=True)
class LightGateRequestInputs:
    """Caller-supplied inputs for creating a light-gate request at block time."""

    fork_description: str
    recommended_option: str
    options: tuple[str, ...]
    trade_off: str
    revert_path: str
    expires_at: str
    idempotency_key: str


@dataclass(frozen=True)
class GateRouteResult:
    """Outcome of evaluating a task's disposition and routing the transition."""

    action: GateRouteAction
    disposition: GateDisposition
    reason: str
    rules: tuple[str, ...]
    light_gate_request: LightGateRequest | None = None


@dataclass(frozen=True)
class LightGateResolution:
    """Result of resolving a light-gate decision."""

    final_state: LifecycleState
    outcome: LightGateOutcome
    gate_id: str


class GateLifecycleCoordinator:
    """Orchestrate the PLANNED -> APPROVED transition respecting gate disposition.

    The coordinator calls :func:`evaluate_gate` to classify the task, then
    routes based on the disposition.  The lifecycle record only enforces
    transitions; this coordinator decides which transitions to attempt.

    For ``gate_light``: the task enters ``BLOCKED`` (gate-pending) until a
    :class:`LightGateDecision` with outcome ``approved`` is recorded, then
    resumes to ``APPROVED``.  A ``rejected`` decision stays ``BLOCKED`` with
    rejection recorded in provenance.  An expired gate leaves the task
    ``BLOCKED`` -- it cannot be auto-approved.

    The evaluator is NOT embedded in the lifecycle record.  The orchestrator
    supplies the disposition by calling :meth:`attempt_transition`; the record
    only enforces the transition rules it already knows.
    """

    def __init__(
        self,
        light_gate_adapter: LightGateAdapter | None = None,
        learning_store: GateLearningStore | None = None,
    ) -> None:
        self._light_gate = light_gate_adapter
        self._learning_store = learning_store

    # -- Public API --------------------------------------------------------

    def evaluate(self, gate_task: GateTask) -> GateDecision:
        """Evaluate a task's gate disposition (pure classification, no side effects)."""
        return evaluate_gate(gate_task, learning_store=self._learning_store)

    def attempt_transition(
        self,
        record: CanonicalTaskRecord,
        gate_task: GateTask,
        *,
        actor: str,
        light_gate_inputs: LightGateRequestInputs | None = None,
    ) -> GateRouteResult:
        """Evaluate disposition and route the PLANNED -> APPROVED transition.

        For ``autonomous`` / ``report_only``: transitions directly to APPROVED.
        For ``gate_heavy``: returns ``USE_HEAVY_GATE`` so the caller invokes the
        existing broker path.
        For ``gate_light``: creates a request via the light-gate adapter, blocks
        the task, and returns the request for presentation.  The task cannot
        reach APPROVED until :meth:`resolve_light_gate` is called with an
        approved decision.

        Raises:
            ValueError: record is not at PLANNED, or gate_light disposition
                lacks a light-gate adapter or request inputs.
        """
        if record.state is not LifecycleState.PLANNED:
            raise ValueError(
                f"attempt_transition requires PLANNED state, got {record.state.value}"
            )

        decision = self.evaluate(gate_task)

        if decision.disposition in (
            GateDisposition.AUTONOMOUS,
            GateDisposition.REPORT_ONLY,
        ):
            record.transition(
                LifecycleState.APPROVED, actor=actor, reason=decision.reason
            )
            return GateRouteResult(
                action=GateRouteAction.PROCEED_TO_APPROVED,
                disposition=decision.disposition,
                reason=decision.reason,
                rules=decision.rules,
            )

        if decision.disposition is GateDisposition.GATE_HEAVY:
            return GateRouteResult(
                action=GateRouteAction.USE_HEAVY_GATE,
                disposition=decision.disposition,
                reason=decision.reason,
                rules=decision.rules,
            )

        # -- gate_light: block + create light-gate request -----------------
        if self._light_gate is None:
            raise ValueError("gate_light disposition requires a light_gate_adapter")
        if light_gate_inputs is None:
            raise ValueError("gate_light disposition requires light_gate_inputs")

        request = self._light_gate.create_request(
            fork_description=light_gate_inputs.fork_description,
            recommended_option=light_gate_inputs.recommended_option,
            options=list(light_gate_inputs.options),
            trade_off=light_gate_inputs.trade_off,
            revert_path=light_gate_inputs.revert_path,
            expires_at=light_gate_inputs.expires_at,
            idempotency_key=light_gate_inputs.idempotency_key,
        )

        record.transition(
            LifecycleState.BLOCKED,
            actor=actor,
            reason=f"gate_light pending: {decision.reason}",
        )
        record._provenance["light_gate_id"] = request.gate_id
        record._provenance["light_gate_disposition"] = decision.disposition.value
        record._provenance["light_gate_rules"] = list(decision.rules)

        return GateRouteResult(
            action=GateRouteAction.BLOCKED_FOR_LIGHT_GATE,
            disposition=decision.disposition,
            reason=decision.reason,
            rules=decision.rules,
            light_gate_request=request,
        )

    def resolve_light_gate(
        self,
        record: CanonicalTaskRecord,
        decision: LightGateDecision,
        *,
        actor: str,
    ) -> LightGateResolution:
        """Resolve a pending light-gate decision.

        - ``approved``: BLOCKED -> PLANNED -> APPROVED.
        - ``rejected``: stays BLOCKED with rejection recorded in provenance.
        - ``expired`` / other: stays BLOCKED (fail-closed, cannot auto-approve).

        The ``actor`` parameter identifies the orchestrator performing the
        recovery transition; ``decision.subject_ref`` identifies the human who
        made the gate decision and is used as the approver for the APPROVED
        transition.

        Raises:
            ValueError: record is not at BLOCKED.
        """
        if record.state is not LifecycleState.BLOCKED:
            raise ValueError(
                f"resolve_light_gate requires BLOCKED state, got {record.state.value}"
            )

        outcome = decision.outcome

        if outcome is LightGateOutcome.APPROVED:
            # BLOCKED -> PLANNED (recovery) -> APPROVED (human approval)
            record.transition(
                LifecycleState.PLANNED, actor=actor, reason="light-gate recovery"
            )
            record.transition(
                LifecycleState.APPROVED,
                actor=decision.subject_ref,
                reason=f"light-gate approved: {decision.chosen_option}",
            )
            record._provenance["light_gate_resolution"] = "approved"
            record._provenance["light_gate_chosen_option"] = decision.chosen_option
            return LightGateResolution(
                final_state=LifecycleState.APPROVED,
                outcome=outcome,
                gate_id=decision.gate_id,
            )

        # rejected / expired / revoked / malformed -- stay BLOCKED, fail-closed
        record._provenance["light_gate_resolution"] = outcome.value
        if outcome is LightGateOutcome.REJECTED:
            record._provenance["light_gate_subject"] = decision.subject_ref
        return LightGateResolution(
            final_state=LifecycleState.BLOCKED,
            outcome=outcome,
            gate_id=decision.gate_id,
        )


__all__ = [
    "GateLifecycleCoordinator",
    "GateRouteAction",
    "GateRouteResult",
    "LightGateRequestInputs",
    "LightGateResolution",
]
