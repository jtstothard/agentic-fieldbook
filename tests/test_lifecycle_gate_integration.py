"""Integration tests: gate evaluator + light-gate wired into PLANNED -> APPROVED.

Covers all four dispositions at the transition (issue #61 acceptance criteria):

- ``autonomous``: proceeds PLANNED -> APPROVED -> EXECUTING, no gate request.
- ``gate_heavy``: routes to the existing ApprovalGateAdapter + broker path
  (verified as an unchanged existing test).
- ``gate_light``: enters BLOCKED after a LightGateRequest is created, cannot
  reach APPROVED until an approved LightGateDecision is recorded.
- ``gate_light`` rejected: stays BLOCKED with rejection recorded.
- ``gate_light`` expired: stays BLOCKED, cannot auto-approve.
- ``report_only``: proceeds without a gate request.
- Separation: the lifecycle record does not call the evaluator; the coordinator
  supplies the disposition, the record only enforces transitions.
"""

from __future__ import annotations

import pytest

from agentic_fieldbook.gate_evaluator import (
    GateDisposition,
    GateTask,
    ObligationType,
)
from agentic_fieldbook.gate_integration import (
    GateLifecycleCoordinator,
    GateRouteAction,
    LightGateRequestInputs,
)
from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    LifecycleState,
    TaskContract,
)
from agentic_fieldbook.light_gate import LightGateOutcome

# Reuse the contract-conformant fake adapter from the light-gate suite.
from tests.test_light_gate import (
    ObservableAdapter,
    EXPIRES_FUTURE,
    make_inputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(**overrides) -> TaskContract:
    """Build a valid TaskContract with sensible defaults."""
    defaults = dict(
        contract_id="FB-001",
        objective="test objective",
        scope=("scope-item",),
        exclusions=(),
        risk_class="low",
        capabilities=("read",),
        acceptance_criteria=(),
        required_evidence=(),
    )
    defaults.update(overrides)
    return TaskContract(**defaults)


def _make_planned_record(**contract_overrides) -> CanonicalTaskRecord:
    """Create a record already at PLANNED state."""
    record = CanonicalTaskRecord.create(
        _make_contract(**contract_overrides), task_id="task-1"
    )
    record.transition(LifecycleState.PLANNED, actor="planner")
    return record


def _light_gate_inputs(**changes) -> LightGateRequestInputs:
    """Build light-gate request inputs from the test_light_gate helper."""
    base = make_inputs()
    base.update(changes)
    return LightGateRequestInputs(
        fork_description=base["fork_description"],
        recommended_option=base["recommended_option"],
        options=tuple(base["options"]),
        trade_off=base["trade_off"],
        revert_path=base["revert_path"],
        expires_at=base["expires_at"],
        idempotency_key=base["idempotency_key"],
    )


# ===========================================================================
# AC1: autonomous disposition proceeds without a gate request
# ===========================================================================

class TestAutonomousDisposition:
    """A task with disposition autonomous proceeds PLANNED -> APPROVED -> EXECUTING."""

    def test_autonomous_reaches_approved_without_gate(self):
        record = _make_planned_record(capabilities=("read",))
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("read",))

        result = coord.attempt_transition(record, task, actor="planner")

        assert result.action is GateRouteAction.PROCEED_TO_APPROVED
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert record.state is LifecycleState.APPROVED
        # No gate request created.
        assert result.light_gate_request is None

    def test_autonomous_can_continue_to_executing(self):
        """autonomous task reaches APPROVED then EXECUTING — full lifecycle."""
        record = _make_planned_record(capabilities=("read",))
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("read",))

        coord.attempt_transition(record, task, actor="planner")
        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=("read",),
        )
        assert record.state is LifecycleState.EXECUTING


# ===========================================================================
# AC2: gate_heavy uses existing ApprovalGateAdapter path (unchanged)
# ===========================================================================

class TestGateHeavyDisposition:
    """A task with disposition gate_heavy signals USE_HEAVY_GATE (broker path).

    The existing approval_gate/broker tests verify the heavy-gate path itself;
    here we confirm the coordinator routes to the heavy path without attempting
    the transition, preserving the separation.
    """

    def test_gate_heavy_returns_use_heavy_gate(self):
        # G1 always-ask (destructive) -> gate_heavy
        record = _make_planned_record(capabilities=("delete",))
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("delete",))

        result = coord.attempt_transition(record, task, actor="planner")

        assert result.action is GateRouteAction.USE_HEAVY_GATE
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert "G1" in result.rules
        # Record is still at PLANNED — coordinator did not transition it.
        assert record.state is LifecycleState.PLANNED

    def test_gate_heavy_does_not_create_light_gate_request(self):
        record = _make_planned_record(capabilities=("delete",))
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("delete",))

        result = coord.attempt_transition(record, task, actor="planner")

        assert result.light_gate_request is None


# ===========================================================================
# AC3: gate_light enters BLOCKED after LightGateRequest is created
# ===========================================================================

class TestGateLightBlockedTransition:
    """A gate_light task enters BLOCKED after a LightGateRequest is created."""

    def test_gate_light_blocks_after_request(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        # G2 spec-fork, not trivially reversible -> gate_light
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        result = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )

        assert result.action is GateRouteAction.BLOCKED_FOR_LIGHT_GATE
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.light_gate_request is not None
        assert result.light_gate_request.outcome is LightGateOutcome.PENDING
        assert record.state is LifecycleState.BLOCKED

    def test_blocked_record_provenance_records_gate_id(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        result = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )

        assert record._provenance["light_gate_id"] == result.light_gate_request.gate_id
        assert record._provenance["light_gate_disposition"] == "gate_light"

    def test_gate_light_cannot_reach_approved_without_decision(self):
        """A BLOCKED gate_light task cannot directly transition to APPROVED."""
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )
        assert record.state is LifecycleState.BLOCKED

        # Direct BLOCKED -> APPROVED is not a valid transition in the lifecycle.
        with pytest.raises(Exception):
            record.transition(LifecycleState.APPROVED, actor="anyone")

    def test_gate_light_approved_decision_resumes_to_approved(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        route = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )
        gate_id = route.light_gate_request.gate_id

        # Human approves via the light-gate adapter.
        decision = adapter.record_decision(gate_id, "blue-green", "human-jay")
        resolution = coord.resolve_light_gate(record, decision, actor="orchestrator")

        assert resolution.outcome is LightGateOutcome.APPROVED
        assert resolution.final_state is LifecycleState.APPROVED
        assert record.state is LifecycleState.APPROVED

    def test_gate_light_approved_can_continue_to_executing(self):
        """After light-gate approval, task can proceed to EXECUTING."""
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        route = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )
        decision = adapter.record_decision(
            route.light_gate_request.gate_id, "blue-green", "human-jay"
        )
        coord.resolve_light_gate(record, decision, actor="orchestrator")

        record.transition(
            LifecycleState.EXECUTING,
            actor="executor",
            executor_capabilities=("read",),
        )
        assert record.state is LifecycleState.EXECUTING


# ===========================================================================
# AC4: gate_light rejected stays BLOCKED with rejection recorded
# ===========================================================================

class TestGateLightRejected:
    """A gate_light task whose decision is rejected stays BLOCKED."""

    def test_rejected_decision_stays_blocked(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        route = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )
        decision = adapter.record_decision(
            route.light_gate_request.gate_id, "", "human-jay"
        )

        resolution = coord.resolve_light_gate(record, decision, actor="orchestrator")

        assert resolution.outcome is LightGateOutcome.REJECTED
        assert resolution.final_state is LifecycleState.BLOCKED
        assert record.state is LifecycleState.BLOCKED
        assert record._provenance["light_gate_resolution"] == "rejected"

    def test_rejected_cannot_auto_reach_approved(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        route = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )
        decision = adapter.record_decision(
            route.light_gate_request.gate_id, "", "human-jay"
        )
        coord.resolve_light_gate(record, decision, actor="orchestrator")

        with pytest.raises(Exception):
            record.transition(LifecycleState.APPROVED, actor="anyone")


# ===========================================================================
# AC5: gate_light expired stays BLOCKED, cannot auto-approve
# ===========================================================================

class TestGateLightExpired:
    """A gate_light task that expires while blocked stays BLOCKED."""

    def test_expired_decision_stays_blocked(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        # Create a request with a past expiry.
        route = coord.attempt_transition(
            record, task, actor="planner",
            light_gate_inputs=_light_gate_inputs(expires_at="2000-01-01T00:00:00Z"),
        )
        gate_id = route.light_gate_request.gate_id

        # The adapter returns EXPIRED for a past-expiry gate.
        decision = adapter.record_decision(gate_id, "blue-green", "human-jay")
        assert decision.outcome is LightGateOutcome.EXPIRED

        resolution = coord.resolve_light_gate(record, decision, actor="orchestrator")

        assert resolution.final_state is LifecycleState.BLOCKED
        assert record.state is LifecycleState.BLOCKED
        assert record._provenance["light_gate_resolution"] == "expired"

    def test_expired_cannot_auto_approve(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        route = coord.attempt_transition(
            record, task, actor="planner",
            light_gate_inputs=_light_gate_inputs(expires_at="2000-01-01T00:00:00Z"),
        )
        decision = adapter.record_decision(
            route.light_gate_request.gate_id, "blue-green", "human-jay"
        )
        coord.resolve_light_gate(record, decision, actor="orchestrator")

        with pytest.raises(Exception):
            record.transition(LifecycleState.APPROVED, actor="anyone")


# ===========================================================================
# AC6: report_only proceeds without a gate request
# ===========================================================================

class TestReportOnlyDisposition:
    """A report_only task proceeds PLANNED -> APPROVED without a gate request."""

    def test_report_only_proceeds_to_approved(self):
        # Internal obligation -> report_only
        record = _make_planned_record()
        coord = GateLifecycleCoordinator()
        task = GateTask(
            risk_class="low",
            capabilities=("read",),
            obligation_type=ObligationType.INTERNAL,
        )

        result = coord.attempt_transition(record, task, actor="planner")

        assert result.action is GateRouteAction.PROCEED_TO_APPROVED
        assert result.disposition is GateDisposition.REPORT_ONLY
        assert record.state is LifecycleState.APPROVED
        assert result.light_gate_request is None


# ===========================================================================
# AC7: architectural separation — record does not call evaluator
# ===========================================================================

class TestArchitecturalSeparation:
    """The lifecycle record does not call the evaluator; the coordinator does."""

    def test_record_has_no_gate_evaluator_dependency(self):
        """CanonicalTaskRecord must not import or call the gate evaluator."""
        import agentic_fieldbook.lifecycle as lifecycle_mod
        import inspect

        source = inspect.getsource(lifecycle_mod)
        assert "gate_evaluator" not in source
        assert "evaluate_gate" not in source
        assert "GateTask" not in source
        assert "LightGate" not in source

    def test_coordinator_supplies_disposition(self):
        """The coordinator decides the route; the record only enforces rules."""
        record = _make_planned_record()
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("read",))

        # The record has no knowledge of the disposition; the coordinator
        # evaluates and calls transition with the right target.
        result = coord.attempt_transition(record, task, actor="planner")

        assert record.state is LifecycleState.APPROVED
        # The record's history shows a normal PLANNED -> APPROVED transition.
        assert record.history[-1]["from"] == "planned"
        assert record.history[-1]["to"] == "approved"


# ===========================================================================
# Coordinator guard clauses
# ===========================================================================

class TestCoordinatorGuards:
    """Guard clauses on the coordinator's public API."""

    def test_attempt_transition_requires_planned_state(self):
        record = CanonicalTaskRecord.create(
            _make_contract(), task_id="task-1"
        )
        coord = GateLifecycleCoordinator()
        task = GateTask(risk_class="low", capabilities=("read",))

        with pytest.raises(ValueError, match="PLANNED"):
            coord.attempt_transition(record, task, actor="planner")

    def test_gate_light_without_adapter_raises(self):
        record = _make_planned_record()
        coord = GateLifecycleCoordinator()  # no adapter
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        with pytest.raises(ValueError, match="light_gate_adapter"):
            coord.attempt_transition(record, task, actor="planner")

    def test_gate_light_without_inputs_raises(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), spec_fork=True)

        with pytest.raises(ValueError, match="light_gate_inputs"):
            coord.attempt_transition(record, task, actor="planner")

    def test_resolve_light_gate_requires_blocked_state(self):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()

        decision = adapter.record_decision("nope", "opt", "human")
        with pytest.raises(ValueError, match="BLOCKED"):
            coord.resolve_light_gate(record, decision, actor="orchestrator")


# ===========================================================================
# G3 / G5 dispositions also route to gate_light (additional coverage)
# ===========================================================================

class TestGateLightMultipleMarkers:
    """Multiple genuine-decision markers route to gate_light."""

    @pytest.mark.parametrize(
        "kwargs, marker",
        [
            (dict(spec_fork=True), "G2"),
            (dict(reversal_asymmetry=True), "G3"),
            (dict(obligation_type=ObligationType.THIRD_PARTY), "G4"),
            (dict(ambiguous_intent_high_blast=True), "G5"),
        ],
    )
    def test_each_marker_routes_to_gate_light(self, kwargs, marker):
        adapter = ObservableAdapter()
        coord = GateLifecycleCoordinator(light_gate_adapter=adapter)
        record = _make_planned_record()
        task = GateTask(risk_class="low", capabilities=("read",), **kwargs)

        result = coord.attempt_transition(
            record, task, actor="planner", light_gate_inputs=_light_gate_inputs()
        )

        assert result.action is GateRouteAction.BLOCKED_FOR_LIGHT_GATE
        assert marker in result.rules
        assert record.state is LifecycleState.BLOCKED
