"""E2E integration test: PLANNED->APPROVED gate to Matrix decision and resume (#79).

Proves the full chain with real components::

    CanonicalTaskRecord
      -> GateSubscriber (lifecycle pre-transition hook)
      -> evaluate_gate  (GATE_LIGHT disposition)
      -> GateRouter     (SurfaceRouter routing)
      -> MatrixGateAdapter (render + send)
      -> FakeTransport  (captured message)
      -> /gate command  (process_reply -> record_decision)
      -> transition resumes

No new production code.  The ``DecisionBridge`` is test-local infrastructure
that wires ``GateRouter`` routing to ``MatrixGateAdapter.process_reply`` for
decision recording.  ``GateRouter.await_decision`` is a polling placeholder
(#82); the bridge provides the working seam that proves the ``process_reply``
path end-to-end.

Test cases (issue #79):
  1. Happy path:  GATE_LIGHT -> recommendation-first message -> /gate approve -> APPROVED
  2. Rejection:   /gate reject -> InvalidTransitionError, state stays PLANNED
  3. Expiry:      short validity window -> expired -> blocked + revoke path exercised
  4. Autonomous:  no gate request/message, immediate transition
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

import pytest

from agentic_fieldbook.gate_learning import InMemoryLearningStore
from agentic_fieldbook.gate_subscriber import GateSubscriber
from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    InvalidTransitionError,
    LifecycleState,
    TaskContract,
)
from agentic_fieldbook.light_gate import LightGateOutcome
from agentic_fieldbook.matrix_gate_adapter import (
    MatrixGateAdapter,
    MatrixMessage,
)
from agentic_fieldbook.surface_router import GateRouter


# --------------------------------------------------------------------------- #
# Test infrastructure
# --------------------------------------------------------------------------- #

ROOM = "!control:matrix.org"


class FakeTransport:
    """In-memory MatrixTransport: records sent messages, yields event IDs."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._counter = 0

    def send(self, room_id: str, message: str) -> str:
        self._counter += 1
        self.sent.append((room_id, message))
        return f"$evt-{self._counter:04d}"

    def receive(self) -> tuple[MatrixMessage, ...]:
        return ()


class DecisionBridge:
    """Test-local SurfaceRouter bridging GateRouter to process_reply.

    Uses the **real** ``GateRouter`` for routing (create_request / present /
    revoke) and the **real** ``MatrixGateAdapter`` for decision recording.

    When a gate is created, ``auto_reply`` (if set) generates the queued
    reply text.  When ``await_decision`` is called, the bridge processes
    the queued reply through ``MatrixGateAdapter.process_reply`` -- proving
    the ``/gate`` command -> ``record_decision`` path works end-to-end.

    When no reply is queued (expiry scenario), the bridge falls through to
    ``GateRouter.await_decision`` which checks the validity window.
    """

    def __init__(
        self,
        router: GateRouter,
        adapter: MatrixGateAdapter,
        *,
        auto_reply: Callable[[str], tuple[str, str] | None] | None = None,
    ) -> None:
        self._router = router
        self._adapter = adapter
        self._auto_reply = auto_reply
        self._pending: dict[str, tuple[str, str]] = {}
        self.created_gate_ids: list[str] = []
        self.presented_gate_ids: list[str] = []

    # -- SurfaceRouter protocol -------------------------------------------- #

    def create_request(
        self,
        fork_description: str,
        recommended_option: str,
        options: list[str],
        trade_off: str,
        revert_path: str,
        expires_at: str,
        idempotency_key: str,
    ):
        request = self._router.create_request(
            fork_description=fork_description,
            recommended_option=recommended_option,
            options=options,
            trade_off=trade_off,
            revert_path=revert_path,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )
        if request.gate_id and request.outcome is LightGateOutcome.PENDING:
            self.created_gate_ids.append(request.gate_id)
            if self._auto_reply is not None:
                reply = self._auto_reply(request.gate_id)
                if reply is not None:
                    self._pending[request.gate_id] = reply
        return request

    def present(self, gate_id: str) -> None:
        self.presented_gate_ids.append(gate_id)
        self._router.present(gate_id)

    def await_decision(self, gate_id: str):
        reply = self._pending.pop(gate_id, None)
        if reply is not None:
            text, sender = reply
            decision = self._adapter.process_reply(text, sender)
            if decision is not None:
                return decision
        # No queued reply -- fall through to router (handles expiry).
        return self._router.await_decision(gate_id)

    def revoke(self, gate_id: str, reason: str) -> None:
        self._router.revoke(gate_id, reason)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _contract(
    risk: str = "low", caps: tuple[str, ...] = ("read",),
) -> TaskContract:
    return TaskContract(
        contract_id="FB-E2E-79",
        objective="Deploy v2 to production",
        scope=("deploy",),
        exclusions=(),
        risk_class=risk,
        capabilities=caps,
        acceptance_criteria=("tests",),
        required_evidence=("tests",),
    )


def _record(
    risk: str = "low", caps: tuple[str, ...] = ("read",),
) -> CanonicalTaskRecord:
    r = CanonicalTaskRecord.create(
        _contract(risk, caps), task_id="e2e-task-79",
    )
    r.transition(LifecycleState.PLANNED, actor="planner")
    return r


def _wire(
    *,
    gate_task_kwargs: dict | None = None,
    auto_reply: Callable[[str], tuple[str, str] | None] | None = None,
    learning_store: InMemoryLearningStore | None = None,
) -> tuple[DecisionBridge, MatrixGateAdapter, FakeTransport, GateSubscriber]:
    """Wire the full chain with real components; return (bridge, adapter, transport, subscriber)."""
    transport = FakeTransport()
    adapter = MatrixGateAdapter(transport, ROOM, allowed_senders={"@jay:example"})
    router = GateRouter(matrix_adapter=adapter)
    bridge = DecisionBridge(router, adapter, auto_reply=auto_reply)
    subscriber = GateSubscriber(
        learning_store=learning_store or InMemoryLearningStore(),
        surface_router=bridge,
        gate_task_kwargs=gate_task_kwargs or {},
    )
    return bridge, adapter, transport, subscriber


# =========================================================================== #
# Case 1: Happy path -- GATE_LIGHT -> recommendation-first -> /gate approve
# =========================================================================== #

class TestHappyPath:
    """GATE_LIGHT disposition -> message captured and recommendation-first
    -> /gate approve injected -> transition reaches APPROVED."""

    def test_approve_reaches_approved(self):
        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},          # G2 -> GATE_LIGHT
            auto_reply=lambda gid: (f"/gate approve {gid}", "jay"),
        )
        record = _record()
        record.register_hook(subscriber)

        # Single synchronous call exercises the full chain:
        # hook -> evaluate_gate(GATE_LIGHT) -> create -> present -> await
        # -> process_reply("/gate approve") -> PROCEED -> APPROVED.
        record.transition(LifecycleState.APPROVED, actor="approver")

        assert record.state is LifecycleState.APPROVED

    def test_gate_message_sent_and_recommendation_first(self):
        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
            auto_reply=lambda gid: (f"/gate approve {gid}", "jay"),
        )
        record = _record()
        record.register_hook(subscriber)
        record.transition(LifecycleState.APPROVED, actor="approver")

        # A gate message was sent to the control room.
        assert len(transport.sent) >= 1
        _room, message = transport.sent[0]

        # Recommendation leads (first line).
        first_line = message.splitlines()[0]
        assert first_line == "Recommendation: approve"

        # All four canonical labels are present.
        assert "Recommendation:" in message
        assert "Fork:" in message
        assert "Trade-off:" in message
        assert "Revert:" in message

    def test_gate_was_presented(self):
        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
            auto_reply=lambda gid: (f"/gate approve {gid}", "jay"),
        )
        record = _record()
        record.register_hook(subscriber)
        record.transition(LifecycleState.APPROVED, actor="approver")

        # present() was called exactly once for the gate.
        assert len(bridge.presented_gate_ids) == 1
        assert len(bridge.created_gate_ids) == 1


# =========================================================================== #
# Case 2: Rejection -- /gate reject -> InvalidTransitionError
# =========================================================================== #

class TestRejection:
    """/gate reject -> transition blocked (InvalidTransitionError), state unchanged."""

    def test_reject_blocks_transition(self):
        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
            auto_reply=lambda gid: (f"/gate reject {gid}", "jay"),
        )
        record = _record()
        record.register_hook(subscriber)

        with pytest.raises(InvalidTransitionError, match="light-gate rejected"):
            record.transition(LifecycleState.APPROVED, actor="approver")

        # State unchanged -- still PLANNED.
        assert record.state is LifecycleState.PLANNED

    def test_reject_message_was_presented(self):
        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
            auto_reply=lambda gid: (f"/gate reject {gid}", "jay"),
        )
        record = _record()
        record.register_hook(subscriber)

        with pytest.raises(InvalidTransitionError):
            record.transition(LifecycleState.APPROVED, actor="approver")

        # The gate message was still rendered and sent before the rejection.
        assert len(transport.sent) >= 1


# =========================================================================== #
# Case 3: Expiry -- short validity window -> expired -> blocked + revoke
# =========================================================================== #

class TestExpiry:
    """Short validity window -> gate expired -> transition blocked.
    Revoke path exercised after the block."""

    def test_expired_gate_blocks_transition(self, monkeypatch):
        # Force a zero-second validity window so the gate is immediately
        # expired by the time present/await_decision runs.
        monkeypatch.setattr(
            "agentic_fieldbook.gate_subscriber.timedelta",
            lambda *a, **kw: dt.timedelta(seconds=0),
        )

        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
            # No auto_reply -- gate expires before any reply arrives.
        )
        record = _record()
        record.register_hook(subscriber)

        with pytest.raises(InvalidTransitionError, match="light-gate"):
            record.transition(LifecycleState.APPROVED, actor="approver")

        assert record.state is LifecycleState.PLANNED

    def test_revoke_path_exercised_after_expiry(self, monkeypatch):
        monkeypatch.setattr(
            "agentic_fieldbook.gate_subscriber.timedelta",
            lambda *a, **kw: dt.timedelta(seconds=0),
        )

        bridge, adapter, transport, subscriber = _wire(
            gate_task_kwargs={"spec_fork": True},
        )
        record = _record()
        record.register_hook(subscriber)

        with pytest.raises(InvalidTransitionError):
            record.transition(LifecycleState.APPROVED, actor="approver")

        # Exercise the revoke path on the expired gate.
        gate_id = bridge.created_gate_ids[-1]
        bridge.revoke(gate_id, "validity window expired")

        # Revoke sends a follow-up Matrix message.
        revoke_msgs = [
            msg for _room, msg in transport.sent
            if "revoked" in msg.lower()
        ]
        assert len(revoke_msgs) >= 1


# =========================================================================== #
# Case 4: Autonomous passthrough -- no gate request/message, immediate
# =========================================================================== #

class TestAutonomousPassthrough:
    """No genuine-decision markers -> AUTONOMOUS -> immediate transition.
    No gate request created, no message sent."""

    def test_autonomous_immediate_transition(self):
        # No gate_task_kwargs -- no genuine-decision markers, no always-ask
        # capabilities -> evaluator returns AUTONOMOUS (default path).
        bridge, adapter, transport, subscriber = _wire()
        record = _record()
        record.register_hook(subscriber)

        record.transition(LifecycleState.APPROVED, actor="approver")

        assert record.state is LifecycleState.APPROVED

    def test_no_gate_message_sent(self):
        bridge, adapter, transport, subscriber = _wire()
        record = _record()
        record.register_hook(subscriber)
        record.transition(LifecycleState.APPROVED, actor="approver")

        # No gate request created, no message sent.
        assert len(transport.sent) == 0
        assert len(bridge.created_gate_ids) == 0
        assert len(bridge.presented_gate_ids) == 0
