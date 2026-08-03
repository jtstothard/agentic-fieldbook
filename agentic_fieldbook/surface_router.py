"""Surface router: dispatch a light-gate request to the right transport (#78).

The router contains **routing logic only** — no decision logic.  It inspects
a :class:`LightGateRequest`, selects the appropriate transport adapter, and
dispatches.  The adapter owns transport-specific formatting; the *content*
always comes from :func:`render_gate_message` (#64).

Decision table (from issue #78)::

    Default   → Matrix
    Binary    (≤2 options) → HA actionable push
    G1 heavy  (always-ask) → Matrix + HA push

**HA adapter is deferred.**  The router has the routing logic and selects the
HA adapter when available, but no concrete HA adapter ships in this ticket.
Routing to HA logs a warning and falls back to Matrix so the gate is never
lost.

The router also fulfils the :class:`SurfaceRouter` protocol that
:class:`GateSubscriber` (#77) expects, so it can be injected directly into
the gate subscriber as the light-gate surface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .light_gate import (
    LightGateDecision,
    LightGateOutcome,
    LightGatePresentation,
    LightGateRequest,
    LightGateRevocation,
)

logger = logging.getLogger(__name__)

# Default validity window for light gates created via the router.
DEFAULT_VALIDITY_WINDOW = timedelta(minutes=5)

# Threshold for "binary" routing — ≤2 options is a yes/no (or binary) gate.
_BINARY_OPTION_THRESHOLD = 2


# --------------------------------------------------------------------------- #
# HA adapter protocol (deferred concrete implementation)
# --------------------------------------------------------------------------- #

@runtime_checkable
class HomeAssistantAdapter(Protocol):
    """Protocol for the HA actionable-push adapter (concrete impl deferred).

    The router selects this when binary/G1 gates would go to HA, but no
    concrete adapter ships in #78.  When ``ha_adapter`` is ``None`` the
    router logs and falls back to Matrix.
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
        ...

    def present(self, gate_id: str) -> LightGatePresentation:
        ...

    def record_decision(
        self, gate_id: str, chosen_option: str, subject_ref: str,
    ) -> LightGateDecision:
        ...

    def revoke(self, gate_id: str, reason: str) -> LightGateRevocation:
        ...


# --------------------------------------------------------------------------- #
# Routing classification
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SurfaceRoute:
    """Which adapter(s) a gate should be routed to.

    ``target`` is one of ``"matrix"``, ``"ha"``, or ``"both"``.
    ``reason`` explains the routing decision for logging/debugging.
    """

    target: str   # "matrix" | "ha" | "both"
    reason: str
    binary: bool = False
    g1_heavy: bool = False


def classify_route(request: LightGateRequest) -> SurfaceRoute:
    """Classify a request into its routing target (pure, no I/O).

    - G1 heavy (caller-supplied marker via ``g1_heavy`` is not on the
      request itself — G1 is determined by the gate evaluator, not the
      request shape; the caller passes ``force_both=True`` for G1).
    - Binary (≤2 options) → HA (actionable push).
    - Default → Matrix.
    """
    if len(request.options) <= _BINARY_OPTION_THRESHOLD:
        return SurfaceRoute(
            target="ha",
            reason=f"binary gate ({len(request.options)} options) → HA actionable push",
            binary=True,
        )
    return SurfaceRoute(
        target="matrix",
        reason=f"standard gate ({len(request.options)} options) → Matrix",
    )


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

@dataclass
class GateRouter:
    """Routes light-gate requests to Matrix (default) and HA (when available).

    The router wraps the concrete adapters and fulfils the
    :class:`~agentic_fieldbook.gate_subscriber.SurfaceRouter` protocol so it
    can be injected into :class:`GateSubscriber`.

    Parameters
    ----------
    matrix_adapter
        Required — the Matrix gate adapter (always available).
    ha_adapter
        Optional — the HA actionable-push adapter.  When ``None``, routing
        to HA logs and falls back to Matrix.
    validity_window
        Default expiry for requests created via ``create_request``.
    """

    matrix_adapter: "MatrixGateAdapterLike"
    ha_adapter: HomeAssistantAdapter | None = None
    validity_window: timedelta = DEFAULT_VALIDITY_WINDOW

    # Internal store: gate_id → route classification (for present/decision).
    _routes: dict[str, SurfaceRoute] = field(default_factory=dict, init=False)
    _requests: dict[str, LightGateRequest] = field(default_factory=dict, init=False)

    # -- SurfaceRouter protocol (create / present / await / revoke) ------- #

    def create_request(
        self,
        fork_description: str,
        recommended_option: str,
        options: list[str],
        trade_off: str,
        revert_path: str,
        expires_at: str,
        idempotency_key: str,
        *,
        force_both: bool = False,
    ) -> LightGateRequest:
        """Create a request on the appropriate adapter and remember the route.

        ``force_both=True`` marks the request as G1-heavy so the router
        targets both Matrix and HA (the caller — the gate subscriber —
        knows the evaluator's G1 disposition; the router does not infer it).
        """
        # Pre-build a provisional request to classify, using the Matrix
        # adapter's create_request (which validates + computes signature).
        # We always create on Matrix first because Matrix is the default
        # and the fallback for HA.  The Matrix adapter's create is
        # idempotent, so a later HA dispatch with the same key is a replay.
        request = self.matrix_adapter.create_request(
            fork_description=fork_description,
            recommended_option=recommended_option,
            options=options,
            trade_off=trade_off,
            revert_path=revert_path,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
        )

        if request.outcome is not LightGateOutcome.PENDING:
            # Not pending (idempotency conflict / malformed) — return as-is.
            return request

        # Classify the route.
        if force_both:
            route = SurfaceRoute(
                target="both",
                reason="G1 heavy (always-ask) → Matrix + HA push",
                g1_heavy=True,
            )
        else:
            route = classify_route(request)

        self._routes[request.gate_id] = route
        self._requests[request.gate_id] = request
        return request

    def present(self, gate_id: str) -> LightGatePresentation:
        """Present the gate via the routed adapter(s).

        Adapters wrap content; they don't re-render.  The Matrix adapter
        calls :func:`render_gate_message` internally.
        """
        route = self._routes.get(gate_id)
        if route is None:
            return self.matrix_adapter.present(gate_id)

        presentation = self.matrix_adapter.present(gate_id)

        if route.target in ("ha", "both"):
            self._maybe_dispatch_ha(gate_id, route)

        return presentation

    def await_decision(self, gate_id: str) -> LightGateDecision:
        """Block until a decision is recorded (delegates to Matrix adapter).

        In v1 the Matrix adapter's decision-arrives-via-reply model is the
        synchronous wait point.  The router delegates to the Matrix
        adapter's ``record_decision`` is driven externally; this method is
        a placeholder that polls the Matrix adapter's stored request for
        expiry.  Real async wiring is a follow-up.
        """
        # v1: the gate subscriber calls record_decision externally after
        # receiving the decision from process_reply.  await_decision here
        # is a no-op pass-through that returns the current state if already
        # decided, or constructs an EXPIRED decision if the window lapsed.
        request = self._requests.get(gate_id)
        now_iso = _now_utc_iso()
        if request is not None:
            try:
                from .light_gate import parse_timestamp
                if parse_timestamp(request.expires_at) <= datetime.now(timezone.utc):
                    return LightGateDecision(
                        gate_id, LightGateOutcome.EXPIRED, "", "system", now_iso,
                    )
            except ValueError:
                pass
        # Default: return a PENDING-flavoured decision (caller retries).
        return LightGateDecision(
            gate_id, LightGateOutcome.PENDING, "", "", now_iso,
        )

    def revoke(self, gate_id: str, reason: str) -> None:
        """Revoke the gate on the routed adapter(s)."""
        route = self._routes.get(gate_id)
        self.matrix_adapter.revoke(gate_id, reason)
        if route is not None and route.target in ("ha", "both") and self.ha_adapter is not None:
            self.ha_adapter.revoke(gate_id, reason)

    # -- HA fallback ------------------------------------------------------ #

    def _maybe_dispatch_ha(self, gate_id: str, route: SurfaceRoute) -> None:
        """Dispatch to HA when available; log + fall back when not."""
        if self.ha_adapter is None:
            logger.warning(
                "HA adapter not yet implemented; gate %s routed to HA (%s) "
                "falls back to Matrix",
                gate_id, route.reason,
            )
            return
        # HA adapter available — dispatch (create is idempotent on key).
        request = self._requests.get(gate_id)
        if request is None:
            return
        self.ha_adapter.create_request(
            fork_description=request.fork_description,
            recommended_option=request.recommended_option,
            options=list(request.options),
            trade_off=request.trade_off,
            revert_path=request.revert_path,
            expires_at=request.expires_at,
            idempotency_key=request.idempotency_key,
        )
        self.ha_adapter.present(gate_id)


# --------------------------------------------------------------------------- #
# Forward-ref protocol for the matrix adapter (avoids circular import at module
# load time; the real type is MatrixGateAdapter from matrix_gate_adapter).
# --------------------------------------------------------------------------- #

@runtime_checkable
class MatrixGateAdapterLike(Protocol):
    """Structural type the router requires of its matrix_adapter argument."""

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
        ...

    def present(self, gate_id: str) -> LightGatePresentation:
        ...

    def record_decision(
        self, gate_id: str, chosen_option: str, subject_ref: str,
    ) -> LightGateDecision:
        ...

    def revoke(self, gate_id: str, reason: str) -> LightGateRevocation:
        ...


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "GateRouter",
    "HomeAssistantAdapter",
    "MatrixGateAdapterLike",
    "SurfaceRoute",
    "classify_route",
    "DEFAULT_VALIDITY_WINDOW",
]
