"""Contract tests for the surface router (issue #78).

Covers every acceptance criterion:
- surface_router.py routes a LightGateRequest to Matrix by default
- Binary gates (≤2 options) are routed to HA (routing logic present; HA
  adapter falls back to Matrix with a log)
- G1 heavy gates are routed to Matrix + HA (both targeted; HA falls back
  with log)
- The router calls render_gate_message() for content; adapters wrap, they
  don't re-render
"""
from __future__ import annotations

import logging

import pytest

from agentic_fieldbook.light_gate import (
    LightGateOutcome,
    LightGatePresentation,
    LightGateRequest,
)
from agentic_fieldbook.matrix_gate_adapter import (
    MatrixGateAdapter,
    MatrixMessage,
    render_gate_control_message,
)
from agentic_fieldbook.surface_router import (
    GateRouter,
    SurfaceRoute,
    classify_route,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

EXPIRES_FUTURE = "2099-01-01T00:00:00Z"
ROOM = "!gate:matrix.org"


class FakeTransport:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self._counter = 0

    def send(self, room_id: str, message: str) -> str:
        self._counter += 1
        self.sent.append((room_id, message))
        return f"$evt-{self._counter:04d}"

    def receive(self) -> tuple[MatrixMessage, ...]:
        return ()


class FakeHAAdapter:
    """Fake HA adapter to verify routing dispatch."""

    def __init__(self):
        self.created: list[str] = []
        self.presented: list[str] = []
        self.revoked: list[tuple[str, str]] = []

    def create_request(self, fork_description, recommended_option, options,
                       trade_off, revert_path, expires_at, idempotency_key):
        self.created.append(idempotency_key)
        return LightGateRequest(
            gate_id=f"ha-gate-{len(self.created)}",
            fork_description=fork_description,
            recommended_option=recommended_option,
            options=tuple(options),
            trade_off=trade_off,
            revert_path=revert_path,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            fork_signature="sha256:fake",
        )

    def present(self, gate_id: str) -> LightGatePresentation:
        self.presented.append(gate_id)
        return LightGatePresentation(
            LightGateOutcome.PRESENTED, gate_id, "", "", (), "", "",
        )

    def record_decision(self, gate_id, chosen_option, subject_ref):
        from agentic_fieldbook.light_gate import LightGateDecision
        return LightGateDecision(
            gate_id, LightGateOutcome.APPROVED, chosen_option, subject_ref,
            "2099-01-01T00:00:00Z",
        )

    def revoke(self, gate_id: str, reason: str):
        from agentic_fieldbook.light_gate import LightGateRevocation
        self.revoked.append((gate_id, reason))
        return LightGateRevocation(gate_id, LightGateOutcome.REVOKED, reason)


def make_matrix_adapter() -> tuple[MatrixGateAdapter, FakeTransport]:
    transport = FakeTransport()
    return MatrixGateAdapter(transport, ROOM), transport


def make_router(
    *, ha_adapter=None,
) -> tuple[GateRouter, MatrixGateAdapter, FakeTransport]:
    matrix_adapter, transport = make_matrix_adapter()
    router = GateRouter(
        matrix_adapter=matrix_adapter,
        ha_adapter=ha_adapter,
    )
    return router, matrix_adapter, transport


def standard_inputs(**changes: str) -> dict:
    base = dict(
        fork_description="deploy v2 to prod",
        recommended_option="blue-green",
        options=["blue-green", "rolling", "halt"],
        trade_off="blue-green needs capacity headroom",
        revert_path="rollback to v1 via deploy button",
        expires_at=EXPIRES_FUTURE,
        idempotency_key="gate-1",
    )
    base.update(changes)
    return base


def binary_inputs(**changes: str) -> dict:
    base = dict(
        fork_description="apply config change",
        recommended_option="apply",
        options=["apply", "skip"],
        trade_off="apply is irreversible without manual revert",
        revert_path="manual revert of the config",
        expires_at=EXPIRES_FUTURE,
        idempotency_key="gate-binary",
    )
    base.update(changes)
    return base


# =========================================================================== #
# AC: classify_route (pure routing logic)
# =========================================================================== #

class TestClassifyRoute:

    def test_standard_gate_routes_to_matrix(self):
        request = LightGateRequest(
            gate_id="g1", fork_description="d", recommended_option="a",
            options=("a", "b", "c"), trade_off="t", revert_path="r",
            expires_at=EXPIRES_FUTURE, idempotency_key="k",
            fork_signature="sha256:x",
        )
        route = classify_route(request)
        assert route.target == "matrix"
        assert not route.binary

    def test_binary_gate_routes_to_ha(self):
        request = LightGateRequest(
            gate_id="g1", fork_description="d", recommended_option="a",
            options=("a", "b"), trade_off="t", revert_path="r",
            expires_at=EXPIRES_FUTURE, idempotency_key="k",
            fork_signature="sha256:x",
        )
        route = classify_route(request)
        assert route.target == "ha"
        assert route.binary

    def test_single_option_routes_to_ha(self):
        """A single-option gate is ≤2 → binary → HA."""
        request = LightGateRequest(
            gate_id="g1", fork_description="d", recommended_option="a",
            options=("a",), trade_off="t", revert_path="r",
            expires_at=EXPIRES_FUTURE, idempotency_key="k",
            fork_signature="sha256:x",
        )
        route = classify_route(request)
        assert route.target == "ha"


# =========================================================================== #
# AC: default routing to Matrix
# =========================================================================== #

class TestDefaultRouting:

    def test_standard_gate_routed_to_matrix(self):
        router, matrix_adapter, transport = make_router()
        request = router.create_request(**standard_inputs())
        assert request.outcome is LightGateOutcome.PENDING

        presentation = router.present(request.gate_id)
        assert presentation.outcome is LightGateOutcome.PRESENTED
        # Message was sent to the Matrix room
        assert len(transport.sent) == 1
        assert transport.sent[0][0] == ROOM

    def test_router_calls_render_gate_message_for_content(self):
        """Adapters wrap, they don't re-render — content = render_gate_message."""
        router, matrix_adapter, transport = make_router()
        request = router.create_request(**standard_inputs())
        router.present(request.gate_id)

        sent_body = transport.sent[0][1]
        expected = render_gate_control_message(request)
        assert sent_body == expected

    def test_router_fulfils_surface_router_protocol(self):
        """The router can be injected into GateSubscriber as the surface."""
        from agentic_fieldbook.gate_subscriber import SurfaceRouter
        router, _, _ = make_router()
        assert isinstance(router, SurfaceRouter)


# =========================================================================== #
# AC: binary routing to HA (with fallback to Matrix)
# =========================================================================== #

class TestBinaryRouting:

    def test_binary_gate_marked_ha_route(self):
        router, _, _ = make_router()
        request = router.create_request(**binary_inputs())
        route = router._routes[request.gate_id]
        assert route.target == "ha"
        assert route.binary

    def test_binary_falls_back_to_matrix_when_no_ha(self, caplog):
        """HA adapter not yet implemented → log + fall back to Matrix."""
        router, matrix_adapter, transport = make_router(ha_adapter=None)
        request = router.create_request(**binary_inputs())
        router.present(request.gate_id)

        # Gate is still presented via Matrix (never lost)
        assert len(transport.sent) == 1
        assert any(
            "HA adapter not yet implemented" in rec.message
            for rec in caplog.records
        )

    def test_binary_dispatches_to_ha_when_available(self):
        """When an HA adapter is injected, binary gates dispatch to it."""
        ha = FakeHAAdapter()
        router, matrix_adapter, transport = make_router(ha_adapter=ha)
        request = router.create_request(**binary_inputs())
        router.present(request.gate_id)

        # HA adapter received create + present
        assert len(ha.created) == 1
        assert len(ha.presented) == 1


# =========================================================================== #
# AC: G1 heavy routing to Matrix + HA
# =========================================================================== #

class TestG1HeavyRouting:

    def test_g1_heavy_routes_to_both(self):
        router, _, _ = make_router()
        request = router.create_request(
            **standard_inputs(), force_both=True,
        )
        route = router._routes[request.gate_id]
        assert route.target == "both"
        assert route.g1_heavy

    def test_g1_heavy_present_dispatches_matrix_and_ha(self):
        ha = FakeHAAdapter()
        router, matrix_adapter, transport = make_router(ha_adapter=ha)
        request = router.create_request(
            **standard_inputs(), force_both=True,
        )
        presentation = router.present(request.gate_id)

        assert presentation.outcome is LightGateOutcome.PRESENTED
        # Matrix got the message
        assert len(transport.sent) == 1
        # HA got create + present
        assert len(ha.created) == 1
        assert len(ha.presented) == 1

    def test_g1_heavy_falls_back_to_matrix_when_no_ha(self, caplog):
        router, matrix_adapter, transport = make_router(ha_adapter=None)
        request = router.create_request(
            **standard_inputs(), force_both=True,
        )
        router.present(request.gate_id)
        # Matrix still gets it
        assert len(transport.sent) == 1
        assert any(
            "HA adapter not yet implemented" in rec.message
            for rec in caplog.records
        )


# =========================================================================== #
# AC: revoke propagates to both adapters
# =========================================================================== #

class TestRouterRevoke:

    def test_revoke_propagates_to_matrix(self):
        router, matrix_adapter, transport = make_router()
        request = router.create_request(**standard_inputs())
        router.present(request.gate_id)
        router.revoke(request.gate_id, "superseded")
        # Matrix adapter recorded the revoke (follow-up message sent)
        assert len(transport.sent) == 2

    def test_revoke_propagates_to_ha_when_available(self):
        ha = FakeHAAdapter()
        router, _, _ = make_router(ha_adapter=ha)
        request = router.create_request(**binary_inputs())
        router.present(request.gate_id)
        router.revoke(request.gate_id, "superseded")
        assert len(ha.revoked) == 1
        assert ha.revoked[0][0] == request.gate_id


# =========================================================================== #
# AC: idempotency — create_request replay
# =========================================================================== #

class TestRouterIdempotency:

    def test_replay_same_key_returns_same_gate(self):
        router, _, _ = make_router()
        first = router.create_request(**standard_inputs())
        second = router.create_request(**standard_inputs())
        assert second.gate_id == first.gate_id

    def test_conflict_on_mutated_fork(self):
        router, _, _ = make_router()
        first = router.create_request(**standard_inputs())
        mutated = router.create_request(
            **standard_inputs(fork_description="deploy v3"),
        )
        assert mutated.outcome is LightGateOutcome.IDEMPOTENCY_CONFLICT
