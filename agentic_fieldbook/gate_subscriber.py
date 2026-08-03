"""Gate subscriber: registers as the lifecycle pre-transition hook.

The subscriber sits at the ``PLANNED -> APPROVED`` lifecycle seam.  When a
:class:`CanonicalTaskRecord` attempts that transition, the hook fires
(before governance checks), the subscriber builds a :class:`GateTask`,
calls :func:`evaluate_gate`, and acts on the disposition:

- ``AUTONOMOUS``  -> advice ``PROCEED``.
- ``REPORT_ONLY``  -> advice ``PROCEED``, emit a gate event (structured
  record, not a notification).
- ``GATE_LIGHT``   -> advice ``PAUSE``, create a :class:`LightGateRequest`
  via the injected surface router, present it, wait for the decision.
  Approval -> ``PROCEED``; rejection/expiry -> ``BLOCK``.
- ``GATE_HEAVY``   -> advice ``PROCEED`` (the existing
  :class:`ApprovalGateAdapter` path handles G1 enforcement downstream).

The subscriber is synchronous in v1 within a single process.  "Wait for
decision" means the hook blocks the transition call until the decision
arrives or the validity window expires.  Async/event-driven wiring is a
follow-up.

Dependencies (learning store, surface router) are injected -- no globals,
testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from .gate_evaluator import (
    GateDecision,
    GateLearningStore,
    GateTask,
    evaluate_gate,
)
from .lifecycle import (
    CanonicalTaskRecord,
    HookResult,
    LifecycleState,
    TaskContract,
    TransitionAdvice,
)
from .light_gate import LightGateOutcome, LightGateRequest, LightGateDecision


# --------------------------------------------------------------------------- #
# Gate event
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GateEvent:
    """Structured record emitted on REPORT_ONLY (and optionally other paths).

    This is a structured record, not a notification.  The notification layer
    (adapter-owned) may consume it, but the subscriber itself does not send
    messages.  Shape: ``{task_id, disposition, reason, timestamp}``.
    """

    task_id: str
    disposition: str
    reason: str
    timestamp: str
    rules: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "disposition": self.disposition,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "rules": list(self.rules),
        }


# --------------------------------------------------------------------------- #
# Surface router protocol
# --------------------------------------------------------------------------- #

@runtime_checkable
class SurfaceRouter(Protocol):
    """Protocol for the light-gate presentation surface.

    The subscriber uses this to create, present, and await a light-gate
    decision.  The adapter owns transport (Telegram, CLI, web, etc.).
    Implementations MUST be synchronous in v1: ``await_decision`` blocks
    until a decision is recorded or the validity window expires.
    """

    def create_request(
        self,
        fork_description: str,
        recommended_option: str,
        options: list[str],
        trade_off: str,
        revert_path: str,
        expires_at: str,
        idempotency_key: str,
    ) -> LightGateRequest:
        """Create or replay a light-gate request."""
        ...

    def present(self, gate_id: str) -> None:
        """Present the gate to the human via the adapter's channel."""
        ...

    def await_decision(self, gate_id: str) -> LightGateDecision:
        """Block until a decision is recorded or the gate expires/revoke.

        Returns the :class:`LightGateDecision`.  The outcome may be
        ``APPROVED``, ``REJECTED``, ``EXPIRED``, or ``REVOKED``.
        """
        ...

    def revoke(self, gate_id: str, reason: str) -> None:
        """Revoke a gate so it can no longer be decided."""
        ...


# --------------------------------------------------------------------------- #
# GateTask builder
# --------------------------------------------------------------------------- #

def build_gate_task(
    contract: TaskContract,
    *,
    trivially_reversible: bool = False,
    spec_fork: bool = False,
    reversal_asymmetry: bool = False,
    obligation_type: str = "none",
    ambiguous_intent_high_blast: bool = False,
    action_class: str = "",
    fork_signature: str = "",
) -> GateTask:
    """Build a :class:`GateTask` from a :class:`TaskContract`.

    Maps the fields already on the contract (risk_class, capabilities) and
    accepts caller-supplied genuine-decision markers that are NOT on the
    contract.  The evaluator never infers these -- the caller must supply
    them explicitly.
    """
    from .gate_evaluator import ObligationType

    return GateTask(
        risk_class=contract.risk_class,
        capabilities=contract.capabilities,
        trivially_reversible=trivially_reversible,
        spec_fork=spec_fork,
        reversal_asymmetry=reversal_asymmetry,
        obligation_type=ObligationType(obligation_type),
        ambiguous_intent_high_blast=ambiguous_intent_high_blast,
        action_class=action_class,
        fork_signature=fork_signature,
    )


# --------------------------------------------------------------------------- #
# Gate subscriber
# --------------------------------------------------------------------------- #

@dataclass
class GateSubscriber:
    """Pre-transition hook that runs the gate evaluator at PLANNED -> APPROVED.

    Register via :func:`register_transition_hook` (module-level) or
    :meth:`CanonicalTaskRecord.register_hook` (per-record).  The subscriber
    only acts on ``PLANNED -> APPROVED`` transitions; all other transitions
    receive ``PROCEED`` unconditionally.

    Dependencies are injected via the constructor:

    - ``learning_store``: optional :class:`GateLearningStore` for B1/B2.
    - ``surface_router``: optional :class:`SurfaceRouter` for light-gate
      creation/presentation/await.  Required when a ``GATE_LIGHT``
      disposition is possible; if missing, GATE_LIGHT raises ``ValueError``.
    - ``gate_task_kwargs``: optional caller-supplied genuine-decision
      markers (spec_fork, obligation_type, etc.) applied to every
      evaluation.  Per-transition overrides are not supported in v1.
    - ``event_sink``: optional callable that receives emitted
      :class:`GateEvent` instances (for testing/inspection).  When ``None``,
      events are recorded in ``self.events``.
    """

    learning_store: GateLearningStore | None = None
    surface_router: SurfaceRouter | None = None
    gate_task_kwargs: dict[str, Any] = field(default_factory=dict)
    event_sink: Callable[[GateEvent], None] | None = None

    # Internal: collected events when no sink is provided
    events: list[GateEvent] = field(default_factory=list, init=False)

    def __call__(
        self,
        record: CanonicalTaskRecord,
        source: LifecycleState,
        target: LifecycleState,
    ) -> HookResult:
        """Pre-transition hook entry point.

        Only acts on ``PLANNED -> APPROVED``.  All other transitions get
        unconditional ``PROCEED``.
        """
        if source is not LifecycleState.PLANNED or target is not LifecycleState.APPROVED:
            return HookResult(TransitionAdvice.PROCEED)

        return self._evaluate_and_route(record)

    # -- Internal routing --------------------------------------------------

    def _evaluate_and_route(self, record: CanonicalTaskRecord) -> HookResult:
        """Build GateTask, evaluate, route based on disposition."""
        gate_task = build_gate_task(
            record.contract, **self.gate_task_kwargs
        )
        decision = evaluate_gate(gate_task, learning_store=self.learning_store)

        if decision.disposition.value == "autonomous":
            return HookResult(TransitionAdvice.PROCEED, reason=decision.reason)

        if decision.disposition.value == "report_only":
            self._emit_event(record, decision)
            return HookResult(TransitionAdvice.PROCEED, reason=decision.reason)

        if decision.disposition.value == "gate_heavy":
            # Existing ApprovalGateAdapter path handles G1 downstream.
            return HookResult(TransitionAdvice.PROCEED, reason=decision.reason)

        if decision.disposition.value == "gate_light":
            return self._handle_gate_light(record, decision)

        # Should never reach here (evaluator is exhaustive), fail-closed.
        return HookResult(
            TransitionAdvice.BLOCK,
            reason=f"unknown disposition: {decision.disposition.value}",
        )

    def _handle_gate_light(
        self, record: CanonicalTaskRecord, decision: GateDecision
    ) -> HookResult:
        """Create light-gate request, present, await decision."""
        if self.surface_router is None:
            raise ValueError(
                "GATE_LIGHT disposition requires a surface_router; "
                "none was injected into GateSubscriber"
            )

        task_id = record.task_id
        idempotency_key = f"gate:{task_id}"

        # Default expiry: 5 minutes from now (UTC, ISO-8601 with Z).
        # The surface router's create_request validates the timestamp.
        expires_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        request = self.surface_router.create_request(
            fork_description=record.contract.objective,
            recommended_option="approve",
            options=["approve", "reject"],
            trade_off=decision.reason,
            revert_path="discard the transition and revise the plan",
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )

        # Fail-closed: if the request is not PENDING (idempotency conflict,
        # already decided, etc.), block the transition.
        if request.outcome is not LightGateOutcome.PENDING:
            return HookResult(
                TransitionAdvice.BLOCK,
                reason=(
                    f"light-gate request not pending "
                    f"(outcome={request.outcome.value}): {decision.reason}"
                ),
            )

        self.surface_router.present(request.gate_id)
        gate_decision = self.surface_router.await_decision(request.gate_id)

        if gate_decision.outcome is LightGateOutcome.APPROVED:
            return HookResult(
                TransitionAdvice.PROCEED,
                reason=f"light-gate approved: {gate_decision.chosen_option}",
            )

        # rejected / expired / revoked -> BLOCK
        return HookResult(
            TransitionAdvice.BLOCK,
            reason=(
                f"light-gate {gate_decision.outcome.value}: "
                f"{gate_decision.chosen_option or decision.reason}"
            ),
        )

    def _emit_event(
        self, record: CanonicalTaskRecord, decision: GateDecision
    ) -> None:
        """Emit a structured gate event (REPORT_ONLY path)."""
        event = GateEvent(
            task_id=record.task_id,
            disposition=decision.disposition.value,
            reason=decision.reason,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            rules=decision.rules,
        )
        if self.event_sink is not None:
            self.event_sink(event)
        else:
            self.events.append(event)


__all__ = [
    "GateEvent",
    "GateSubscriber",
    "SurfaceRouter",
    "build_gate_task",
]
