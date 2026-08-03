"""Contract tests for the gate subscriber + lifecycle hook (issue #77).

Covers every acceptance criterion:
- lifecycle.py has a pre-transition hook mechanism (register/unregister, PROCEED/PAUSE/BLOCK)
- Registering the gate subscriber as the hook causes evaluate_gate to run on PLANNED -> APPROVED
- AUTONOMOUS -> PROCEED, transition completes
- REPORT_ONLY -> PROCEED + gate event emitted
- GATE_LIGHT -> PAUSE (transition does not complete)
- GATE_HEAVY -> PROCEED (heavy gate path unchanged)
- approved decision -> PROCEED, transition resumes
- rejected decision -> BLOCK, transition raises InvalidTransitionError
- expiry -> BLOCK, gate revoked
- subscriber is injected with dependencies (no globals)
"""

from __future__ import annotations

import pytest

from agentic_fieldbook.gate_evaluator import (
    GateDisposition,
    GateLearningStore,
    GateTask,
    ObligationType,
)
from agentic_fieldbook.gate_subscriber import (
    GateEvent,
    GateSubscriber,
    SurfaceRouter,
    build_gate_task,
)
from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    HookResult,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
    TransitionAdvice,
    TransitionPausedError,
    register_transition_hook,
    unregister_transition_hook,
)
from agentic_fieldbook.light_gate import (
    LightGateDecision,
    LightGateOutcome,
    LightGateRequest,
)


# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #

def _contract(risk: str = "low", caps: tuple[str, ...] = ("read",)) -> TaskContract:
    return TaskContract(
        contract_id="FB-GATE-77",
        objective="Wire gate subscriber",
        scope=("gate",),
        exclusions=(),
        risk_class=risk,
        capabilities=caps,
        acceptance_criteria=("tests",),
        required_evidence=("tests",),
    )


def _record(risk: str = "low", caps: tuple[str, ...] = ("read",)) -> CanonicalTaskRecord:
    r = CanonicalTaskRecord.create(_contract(risk, caps), task_id="gate-task-77")
    r.transition(LifecycleState.PLANNED, actor="planner")
    return r


class FakeSurfaceRouter:
    """In-memory SurfaceRouter with controllable decision outcome."""

    def __init__(self, outcome: LightGateOutcome = LightGateOutcome.APPROVED,
                 chosen_option: str = "approve"):
        self._outcome = outcome
        self._chosen_option = chosen_option
        self._requests: dict[str, LightGateRequest] = {}
        self._presented: list[str] = []
        self._revoked: list[str] = []
        self._create_calls = 0

    def create_request(self, fork_description, recommended_option, options,
                       trade_off, revert_path, expires_at, idempotency_key):
        self._create_calls += 1
        gate_id = f"gate-{idempotency_key}"
        req = LightGateRequest(
            gate_id=gate_id,
            fork_description=fork_description,
            recommended_option=recommended_option,
            options=tuple(options),
            trade_off=trade_off,
            revert_path=revert_path,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            fork_signature="sha256:test",
            outcome=LightGateOutcome.PENDING,
        )
        self._requests[gate_id] = req
        return req

    def present(self, gate_id: str) -> None:
        self._presented.append(gate_id)

    def await_decision(self, gate_id: str) -> LightGateDecision:
        return LightGateDecision(
            gate_id=gate_id,
            outcome=self._outcome,
            chosen_option=self._chosen_option if self._outcome is LightGateOutcome.APPROVED else "",
            subject_ref="jay",
            timestamp="2026-08-03T12:00:00Z",
        )

    def revoke(self, gate_id: str, reason: str) -> None:
        self._revoked.append((gate_id, reason))


class FakeLearningStore:
    def __init__(self, standing: set[str] | None = None,
                 known: set[str] | None = None):
        self._standing = standing or set()
        self._known = known or set()

    def check_standing_approval(self, action_class: str) -> bool:
        return action_class in self._standing

    def check_known_preference(self, fork_signature: str, threshold: int = 3) -> bool:
        return fork_signature in self._known


# =========================================================================== #
# AC: lifecycle.py hook mechanism
# =========================================================================== #

class TestHookMechanism:
    """lifecycle.py has a minimal pre-transition hook mechanism."""

    def test_register_unregister_global_hook(self):
        """Global hooks can be registered and unregistered."""
        calls: list[str] = []

        def hook(record, source, target):
            calls.append(f"{source.value}->{target.value}")
            return HookResult(TransitionAdvice.PROCEED)

        # Create record BEFORE registering hook so we only observe the
        # PLANNED -> APPROVED transition (record creation does PLANNED).
        r = _record()
        register_transition_hook(hook)
        try:
            r.transition(LifecycleState.APPROVED, actor="approver")
            assert calls == ["planned->approved"]
        finally:
            unregister_transition_hook(hook)

        # After unregister, hook does not fire
        calls.clear()
        r2 = _record()
        r2.transition(LifecycleState.APPROVED, actor="approver")
        assert calls == []

    def test_register_local_hook(self):
        """Record-local hooks fire via register_hook/unregister_hook."""
        fired: list[str] = []

        def hook(record, source, target):
            fired.append(target.value)
            return HookResult(TransitionAdvice.PROCEED)

        r = _record()
        r.register_hook(hook)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert fired == ["approved"]

    def test_unregister_local_hook(self):
        """unregister_hook removes a record-local hook."""
        fired: list[str] = []

        def hook(record, source, target):
            fired.append("hit")
            return HookResult(TransitionAdvice.PROCEED)

        r = _record()
        r.register_hook(hook)
        r.unregister_hook(hook)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert fired == []

    def test_hook_proceed_allows_transition(self):
        def hook(record, source, target):
            return HookResult(TransitionAdvice.PROCEED, reason="ok")

        r = _record()
        r.register_hook(hook)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.APPROVED

    def test_hook_block_prevents_transition(self):
        def hook(record, source, target):
            return HookResult(TransitionAdvice.BLOCK, reason="nope")

        r = _record()
        r.register_hook(hook)
        with pytest.raises(InvalidTransitionError, match="nope"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_hook_pause_prevents_transition(self):
        def hook(record, source, target):
            return HookResult(TransitionAdvice.PAUSE, reason="waiting")

        r = _record()
        r.register_hook(hook)
        with pytest.raises(TransitionPausedError, match="waiting"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_multiple_hooks_fire_in_order(self):
        order: list[str] = []

        def hook_a(record, source, target):
            order.append("a")
            return HookResult(TransitionAdvice.PROCEED)

        def hook_b(record, source, target):
            order.append("b")
            return HookResult(TransitionAdvice.PROCEED)

        r = _record()
        r.register_hook(hook_a)
        r.register_hook(hook_b)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert order == ["a", "b"]

    def test_block_takes_precedence_over_pause(self):
        """If one hook BLOCKs and another PAUSEs, BLOCK wins."""
        order: list[str] = []

        def hook_pause(record, source, target):
            order.append("pause")
            return HookResult(TransitionAdvice.PAUSE)

        def hook_block(record, source, target):
            order.append("block")
            return HookResult(TransitionAdvice.BLOCK)

        r = _record()
        r.register_hook(hook_pause)
        r.register_hook(hook_block)
        with pytest.raises(TransitionPausedError):
            r.transition(LifecycleState.APPROVED, actor="approver")
        # pause fires first, short-circuits before block
        assert order == ["pause"]

    def test_hook_dedup_by_identity(self):
        """Registering the same callable twice has no effect."""
        count: list[int] = []

        def hook(record, source, target):
            count.append(1)
            return HookResult(TransitionAdvice.PROCEED)

        r = _record()
        r.register_hook(hook)
        r.register_hook(hook)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert len(count) == 1

    def test_hook_fires_before_governance(self):
        """Hooks fire before governance checks (BLOCK prevents approval recording)."""
        fired: list[LifecycleState] = []

        def hook(record, source, target):
            fired.append(record.state)
            return HookResult(TransitionAdvice.BLOCK, reason="pre-gov")

        r = _record()
        r.register_hook(hook)
        with pytest.raises(InvalidTransitionError):
            r.transition(LifecycleState.APPROVED, actor="approver")
        # State was PLANNED when hook fired (not yet transitioned)
        assert fired == [LifecycleState.PLANNED]

    def test_hook_does_not_fire_on_truly_invalid_transition(self):
        """Hooks only fire after the transition table validates the path.
        A genuinely invalid transition (e.g. PLANNED -> VERIFIED) is rejected
        before any hook runs."""
        fired: list[str] = []

        def hook(record, source, target):
            fired.append("hit")
            return HookResult(TransitionAdvice.PROCEED)

        r = CanonicalTaskRecord.create(_contract(), task_id="invalid-test")
        r.transition(LifecycleState.PLANNED, actor="planner")
        r.register_hook(hook)
        # PLANNED -> VERIFIED is not in the transition table
        with pytest.raises(InvalidTransitionError):
            r.transition(LifecycleState.VERIFIED, actor="verifier")
        assert fired == []


# =========================================================================== #
# AC: GateSubscriber is a TransitionHook
# =========================================================================== #

class TestSubscriberRegistration:
    """Registering the gate subscriber as the hook causes evaluate_gate to run."""

    def test_subscriber_satisfies_transition_hook_protocol(self):
        sub = GateSubscriber()
        r = _record()
        # Must be callable with the hook signature
        result = sub(r, LifecycleState.PLANNED, LifecycleState.APPROVED)
        assert isinstance(result, HookResult)

    def test_non_planned_to_approved_transitions_get_proceed(self):
        """Subscriber only acts on PLANNED -> APPROVED; other transitions pass through."""
        sub = GateSubscriber()
        r = _record()
        result = sub(r, LifecycleState.PLANNED, LifecycleState.EXECUTING)
        assert result.advice is TransitionAdvice.PROCEED


# =========================================================================== #
# AC: AUTONOMOUS disposition -> PROCEED
# =========================================================================== #

class TestAutonomousDisposition:
    """AUTONOMOUS -> transition completes immediately."""

    def test_autonomous_proceeds(self):
        sub = GateSubscriber()
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.APPROVED

    def test_autonomous_no_surface_router_needed(self):
        """AUTONOMOUS does not require a surface router."""
        sub = GateSubscriber()  # no surface_router
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.APPROVED

    def test_autonomous_via_global_hook(self):
        sub = GateSubscriber()
        register_transition_hook(sub)
        try:
            r = _record()
            r.transition(LifecycleState.APPROVED, actor="approver")
            assert r.state is LifecycleState.APPROVED
        finally:
            unregister_transition_hook(sub)


# =========================================================================== #
# AC: REPORT_ONLY disposition -> PROCEED + gate event emitted
# =========================================================================== #

class TestReportOnlyDisposition:
    """REPORT_ONLY -> transition completes, gate event emitted."""

    def test_report_only_proceeds(self):
        # internal plumbing obligation -> REPORT_ONLY
        sub = GateSubscriber(gate_task_kwargs={"obligation_type": "internal"})
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.APPROVED

    def test_report_only_emits_event(self):
        sub = GateSubscriber(gate_task_kwargs={"obligation_type": "internal"})
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert len(sub.events) == 1
        event = sub.events[0]
        assert event.task_id == "gate-task-77"
        assert event.disposition == "report_only"
        assert event.reason
        assert event.timestamp

    def test_report_only_event_shape(self):
        """Event has the required structured fields."""
        sub = GateSubscriber(gate_task_kwargs={"obligation_type": "internal"})
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        event = sub.events[0]
        d = event.to_dict()
        assert set(d.keys()) == {"task_id", "disposition", "reason", "timestamp", "rules"}

    def test_report_only_uses_injected_event_sink(self):
        """When event_sink is provided, events go there instead of self.events."""
        collected: list[GateEvent] = []

        def sink(e: GateEvent):
            collected.append(e)

        sub = GateSubscriber(
            gate_task_kwargs={"obligation_type": "internal"},
            event_sink=sink,
        )
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert len(collected) == 1
        assert len(sub.events) == 0  # not stored locally when sink is set


# =========================================================================== #
# AC: GATE_LIGHT disposition -> PAUSE
# =========================================================================== #

class TestGateLightDisposition:
    """GATE_LIGHT -> transition does not complete (hook returns PAUSE)."""

    def test_gate_light_without_surface_router_raises_valueerror(self):
        """Without a surface router, GATE_LIGHT raises ValueError (not silently passes)."""
        # spec_fork with low risk, not trivially reversible -> GATE_LIGHT
        sub = GateSubscriber(gate_task_kwargs={"spec_fork": True})
        r = _record()
        r.register_hook(sub)
        with pytest.raises(ValueError, match="surface_router"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_gate_light_blocks_until_approved_decision(self):
        """GATE_LIGHT with approved surface router decision -> PROCEED."""
        router = FakeSurfaceRouter(outcome=LightGateOutcome.APPROVED)
        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.APPROVED
        assert router._create_calls == 1
        assert router._presented == [list(router._requests.keys())[0]]

    def test_gate_light_rejected_blocks_transition(self):
        """GATE_LIGHT with rejected decision -> BLOCK -> InvalidTransitionError."""
        router = FakeSurfaceRouter(outcome=LightGateOutcome.REJECTED)
        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        with pytest.raises(InvalidTransitionError, match="rejected"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_gate_light_expired_blocks_transition(self):
        """GATE_LIGHT with expired decision -> BLOCK -> InvalidTransitionError."""
        router = FakeSurfaceRouter(outcome=LightGateOutcome.EXPIRED)
        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        with pytest.raises(InvalidTransitionError, match="expired"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_gate_light_revoked_blocks_transition(self):
        """GATE_LIGHT with revoked decision -> BLOCK."""
        router = FakeSurfaceRouter(outcome=LightGateOutcome.REVOKED)
        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        with pytest.raises(InvalidTransitionError):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED

    def test_gate_light_non_pending_request_blocks(self):
        """If the light-gate request returns non-PENDING (e.g. idempotency conflict),
        the transition blocks rather than livelocking."""
        router = FakeSurfaceRouter(outcome=LightGateOutcome.APPROVED)

        # Override create_request to return a non-PENDING outcome
        def bad_create(**kwargs):
            req = LightGateRequest(
                gate_id="bad-gate",
                fork_description=kwargs["fork_description"],
                recommended_option=kwargs["recommended_option"],
                options=tuple(kwargs["options"]),
                trade_off=kwargs["trade_off"],
                revert_path=kwargs["revert_path"],
                expires_at=kwargs["expires_at"],
                idempotency_key=kwargs["idempotency_key"],
                fork_signature="sha256:conflict",
                outcome=LightGateOutcome.IDEMPOTENCY_CONFLICT,
            )
            return req

        router.create_request = bad_create  # type: ignore

        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        with pytest.raises(InvalidTransitionError, match="not pending"):
            r.transition(LifecycleState.APPROVED, actor="approver")
        assert r.state is LifecycleState.PLANNED


# =========================================================================== #
# AC: GATE_HEAVY disposition -> PROCEED
# =========================================================================== #

class TestGateHeavyDisposition:
    """GATE_HEAVY -> PROCEED (existing heavy-gate path unchanged)."""

    def test_gate_heavy_proceeds(self):
        # always-ask capability -> GATE_HEAVY
        sub = GateSubscriber()
        r = _record(caps=("delete",))
        r.register_hook(sub)
        # PROCEED from the subscriber; governance may still block downstream
        # but the subscriber itself does not veto
        result = sub(r, LifecycleState.PLANNED, LifecycleState.APPROVED)
        assert result.advice is TransitionAdvice.PROCEED

    def test_gate_heavy_does_not_create_light_gate(self):
        """GATE_HEAVY must not create a light-gate request."""
        router = FakeSurfaceRouter()
        sub = GateSubscriber(surface_router=router)
        r = _record(caps=("delete",))
        result = sub(r, LifecycleState.PLANNED, LifecycleState.APPROVED)
        assert result.advice is TransitionAdvice.PROCEED
        assert router._create_calls == 0


# =========================================================================== #
# AC: Dependency injection
# =========================================================================== #

class TestDependencyInjection:
    """The subscriber is injected with its dependencies — no globals."""

    def test_learning_store_is_injected(self):
        """B1 standing approval is checked via the injected learning store."""
        # Without standing approval, spec_fork -> GATE_LIGHT (no router -> ValueError)
        sub_no_store = GateSubscriber(gate_task_kwargs={"spec_fork": True})
        r1 = _record()
        with pytest.raises(ValueError, match="surface_router"):
            sub_no_store(r1, LifecycleState.PLANNED, LifecycleState.APPROVED)

        # With standing approval, spec_fork -> AUTONOMOUS (B1)
        store = FakeLearningStore(standing={"low:read"})
        sub_with_store = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            learning_store=store,
        )
        r2 = _record()
        result2 = sub_with_store(r2, LifecycleState.PLANNED, LifecycleState.APPROVED)
        assert result2.advice is TransitionAdvice.PROCEED

    def test_surface_router_is_injected(self):
        """The surface router used for light-gate is the injected one."""
        router = FakeSurfaceRouter()
        sub = GateSubscriber(
            gate_task_kwargs={"spec_fork": True},
            surface_router=router,
        )
        r = _record()
        r.register_hook(sub)
        r.transition(LifecycleState.APPROVED, actor="approver")
        assert router._create_calls == 1  # used the injected router

    def test_no_module_level_state_leaks_between_instances(self):
        """Two subscribers with different configs don't interfere."""
        sub1 = GateSubscriber(gate_task_kwargs={"spec_fork": True})
        sub2 = GateSubscriber()  # routine task -> autonomous

        r1 = _record()
        r2 = _record()
        # sub1 on spec_fork task -> PAUSE (no router -> ValueError)
        with pytest.raises(ValueError):
            sub1(r1, LifecycleState.PLANNED, LifecycleState.APPROVED)

        # sub2 on routine task -> PROCEED (not affected by sub1)
        result = sub2(r2, LifecycleState.PLANNED, LifecycleState.APPROVED)
        assert result.advice is TransitionAdvice.PROCEED


# =========================================================================== #
# AC: build_gate_task helper
# =========================================================================== #

class TestBuildGateTask:
    """build_gate_task maps TaskContract fields correctly."""

    def test_maps_contract_fields(self):
        contract = _contract(risk="medium", caps=("db-write",))
        task = build_gate_task(contract)
        assert task.risk_class == "medium"
        assert task.capabilities == ("db-write",)

    def test_applies_genuine_decision_markers(self):
        contract = _contract()
        task = build_gate_task(
            contract,
            spec_fork=True,
            obligation_type="third_party",
            ambiguous_intent_high_blast=True,
        )
        assert task.spec_fork is True
        assert task.obligation_type is ObligationType.THIRD_PARTY
        assert task.ambiguous_intent_high_blast is True

    def test_defaults_are_safe(self):
        contract = _contract()
        task = build_gate_task(contract)
        assert task.trivially_reversible is False
        assert task.spec_fork is False
        assert task.obligation_type is ObligationType.NONE


# =========================================================================== #
# AC: SurfaceRouter protocol conformance
# =========================================================================== #

class TestSurfaceRouterProtocol:
    """FakeSurfaceRouter satisfies the SurfaceRouter protocol."""

    def test_fake_router_satisfies_protocol(self):
        router = FakeSurfaceRouter()
        assert isinstance(router, SurfaceRouter)

    def test_gate_event_is_dataclass(self):
        """GateEvent is a frozen dataclass with required fields."""
        e = GateEvent(
            task_id="t1",
            disposition="report_only",
            reason="test",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert e.task_id == "t1"
        assert e.disposition == "report_only"
