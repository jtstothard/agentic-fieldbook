"""Contract tests for the gate evaluator (issue #59).

Covers every acceptance criterion from issue #59:
- G1-G5 positive cases (genuine-decision test)
- B1-B4 suppression cases (bureaucracy test)
- fail-closed (unclassifiable -> GATE_LIGHT)
- G1 absolute (nothing overrides always-ask)
- reversibility as master variable (B4 suppresses G2-G5)
- G4 lock to third-party obligations only
"""

from __future__ import annotations

import pytest

from agentic_fieldbook.gate_evaluator import (
    GateDecision,
    GateDisposition,
    GateLearningStore,
    GateTask,
    ObligationType,
    evaluate_gate,
)


# ---------------------------------------------------------------------------
# Fake learning store for B1/B2 tests
# ---------------------------------------------------------------------------

class FakeLearningStore:
    """Minimal in-memory GateLearningStore for tests."""

    def __init__(
        self,
        standing: set[str] | None = None,
        known: set[str] | None = None,
        threshold: int = 3,
    ):
        self._standing = standing or set()
        self._known = known or set()
        self._threshold = threshold

    def check_standing_approval(self, action_class: str) -> bool:
        return action_class in self._standing

    def check_known_preference(self, fork_signature: str, threshold: int = 3) -> bool:
        return fork_signature in self._known


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _routine_task(**kwargs) -> GateTask:
    """A baseline autonomous task with overrides applied."""
    defaults: dict = dict(
        risk_class="low",
        capabilities=("read",),
    )
    defaults.update(kwargs)
    return GateTask(**defaults)


# ===========================================================================
# G1 — always-ask (absolute, routes to GATE_HEAVY)
# ===========================================================================

class TestG1AlwaysAsk:
    """G1: always-ask capabilities -> GATE_HEAVY, regardless of other inputs."""

    @pytest.mark.parametrize("capability", ["delete", "drop", "truncate", "destroy"])
    def test_destructive_routes_heavy(self, capability):
        task = _routine_task(capabilities=(capability,))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY
        assert "G1" in decision.rules

    @pytest.mark.parametrize("capability", ["secret-read", "credential-rotate"])
    def test_secret_access_routes_heavy(self, capability):
        task = _routine_task(capabilities=(capability,))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_billing_routes_heavy(self):
        task = _routine_task(capabilities=("billing-change",))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_access_grant_routes_heavy(self):
        task = _routine_task(capabilities=("access-grant",))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    @pytest.mark.parametrize("capability", ["service-stop", "deployment"])
    def test_downtime_routes_heavy(self, capability):
        task = _routine_task(capabilities=(capability,))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_release_routes_heavy(self):
        task = _routine_task(capabilities=("deploy",))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_g1_absolute_overrides_trivially_reversible(self):
        """G1 fires even when task is trivially reversible."""
        task = _routine_task(
            capabilities=("delete",),
            trivially_reversible=True,
        )
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_g1_absolute_overrides_standing_approval(self):
        """G1 fires even with a standing approval."""
        store = FakeLearningStore(standing={"low:delete"})
        task = _routine_task(capabilities=("delete",))
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.GATE_HEAVY

    def test_g1_absolute_overrides_known_preference(self):
        """G1 fires even with a known preference."""
        store = FakeLearningStore(known={"G2"})
        task = _routine_task(capabilities=("delete",), spec_fork=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.GATE_HEAVY


# ===========================================================================
# G2-G5 genuine-decision positive cases (-> GATE_LIGHT)
# ===========================================================================

class TestG2ToG5GenuineDecision:
    """G2-G5 that are NOT trivially reversible -> GATE_LIGHT."""

    def test_g2_spec_fork(self):
        task = _routine_task(spec_fork=True)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert "G2" in decision.rules

    def test_g3_reversal_asymmetry(self):
        task = _routine_task(reversal_asymmetry=True)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert "G3" in decision.rules

    def test_g4_third_party_obligation(self):
        task = _routine_task(obligation_type=ObligationType.THIRD_PARTY)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert "G4" in decision.rules

    def test_g5_ambiguous_intent_high_blast(self):
        task = _routine_task(ambiguous_intent_high_blast=True)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert "G5" in decision.rules

    def test_multiple_genuine_decision_markers(self):
        """Multiple G2-G5 markers all surface in rules."""
        task = _routine_task(
            spec_fork=True,
            reversal_asymmetry=True,
            obligation_type=ObligationType.THIRD_PARTY,
            ambiguous_intent_high_blast=True,
        )
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert set(decision.rules) == {"G2", "G3", "G4", "G5"}


# ===========================================================================
# G4 lock — internal plumbing does NOT gate
# ===========================================================================

class TestG4Lock:
    """G4 fires only for third-party obligations; internal plumbing is exempt."""

    def test_internal_plumbing_is_report_only(self):
        task = _routine_task(obligation_type=ObligationType.INTERNAL)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.REPORT_ONLY
        assert "not-G4" in decision.rules

    def test_internal_plumbing_not_gate_light(self):
        task = _routine_task(obligation_type=ObligationType.INTERNAL)
        decision = evaluate_gate(task)
        assert decision.disposition is not GateDisposition.GATE_LIGHT

    def test_third_party_obligation_is_gate_light(self):
        task = _routine_task(obligation_type=ObligationType.THIRD_PARTY)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT

    def test_none_obligation_does_not_g4(self):
        task = _routine_task(obligation_type=ObligationType.NONE)
        decision = evaluate_gate(task)
        assert "G4" not in decision.rules


# ===========================================================================
# B1 — standing approval suppression
# ===========================================================================

class TestB1StandingApproval:
    """B1: standing approval -> AUTONOMOUS."""

    def test_standing_approval_yields_autonomous(self):
        store = FakeLearningStore(standing={"low:read"})
        task = _routine_task(capabilities=("read",))
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B1" in decision.rules

    def test_standing_approval_suppresses_genuine_decision(self):
        """B1 wins over G2 spec-fork."""
        store = FakeLearningStore(standing={"low:read"})
        task = _routine_task(capabilities=("read",), spec_fork=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B1" in decision.rules

    def test_no_standing_approval_proceeds_to_gate(self):
        store = FakeLearningStore(standing=set())
        task = _routine_task(spec_fork=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.GATE_LIGHT

    def test_no_store_skips_b1(self):
        """Without a learning store, B1 is simply skipped."""
        task = _routine_task(spec_fork=True)
        decision = evaluate_gate(task)  # no store
        assert decision.disposition is GateDisposition.GATE_LIGHT


# ===========================================================================
# B2 — known preference suppression
# ===========================================================================

class TestB2KnownPreference:
    """B2: known preference (>=3 consistent) -> AUTONOMOUS."""

    def test_known_preference_yields_autonomous(self):
        store = FakeLearningStore(known={"G2"})
        task = _routine_task(spec_fork=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B2" in decision.rules

    def test_known_preference_suppresses_genuine_decision(self):
        """B2 wins over G3 reversal-asymmetry."""
        store = FakeLearningStore(known={"G3"})
        task = _routine_task(reversal_asymmetry=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS

    def test_b2_skipped_when_no_fork_signature(self):
        """B2 is only meaningful when a fork exists."""
        store = FakeLearningStore(known={""})
        task = _routine_task()  # no markers -> empty fork signature
        decision = evaluate_gate(task, learning_store=store)
        # Routine task -> autonomous via default, not via B2
        assert "B2" not in decision.rules

    def test_b2_fires_after_b1_miss(self):
        """B2 evaluated when B1 does not match."""
        store = FakeLearningStore(standing=set(), known={"G4"})
        task = _routine_task(obligation_type=ObligationType.THIRD_PARTY)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B2" in decision.rules


# ===========================================================================
# B4 — trivially reversible suppression
# ===========================================================================

class TestB4TriviallyReversible:
    """B4: trivially reversible -> AUTONOMOUS (master variable for G2-G5)."""

    def test_trivially_reversible_yields_autonomous(self):
        task = _routine_task(trivially_reversible=True)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B4" in decision.rules

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(spec_fork=True),
            dict(reversal_asymmetry=True),
            dict(obligation_type=ObligationType.THIRD_PARTY),
            dict(ambiguous_intent_high_blast=True),
        ],
    )
    def test_b4_suppresses_each_genuine_decision(self, kwargs):
        """B4 suppresses G2-G5 even when the marker is set."""
        task = _routine_task(trivially_reversible=True, **kwargs)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B4" in decision.rules

    def test_b4_suppresses_all_markers_combined(self):
        task = _routine_task(
            trivially_reversible=True,
            spec_fork=True,
            reversal_asymmetry=True,
            obligation_type=ObligationType.THIRD_PARTY,
            ambiguous_intent_high_blast=True,
        )
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS

    def test_b4_does_not_override_g1(self):
        """G1 is absolute — even trivially reversible destructive gates heavy."""
        task = _routine_task(
            capabilities=("delete",),
            trivially_reversible=True,
        )
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_HEAVY


# ===========================================================================
# Fail-closed
# ===========================================================================

class TestFailClosed:
    """Evaluator fails closed (returns GATE_LIGHT) when it cannot classify."""

    def test_invalid_risk_class_fails_closed(self):
        task = _routine_task(risk_class="critical")
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT
        assert "fail-closed" in decision.rules

    def test_empty_risk_class_fails_closed(self):
        task = _routine_task(risk_class="")
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.GATE_LIGHT

    def test_fail_closed_not_autonomous(self):
        task = _routine_task(risk_class="unknown")
        decision = evaluate_gate(task)
        assert decision.disposition is not GateDisposition.AUTONOMOUS


# ===========================================================================
# Default / routine
# ===========================================================================

class TestRoutineTask:
    """A task with no markers and no always-ask caps -> AUTONOMOUS."""

    def test_routine_task_autonomous(self):
        task = _routine_task()
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS

    def test_routine_task_medium_risk_autonomous(self):
        task = _routine_task(risk_class="medium", capabilities=("db-write",))
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS


# ===========================================================================
# Precedence / ordering
# ===========================================================================

class TestPrecedence:
    """Verify the decision-flow ordering is correct."""

    def test_g1_beats_b1(self):
        store = FakeLearningStore(standing={"low:delete"})
        task = _routine_task(capabilities=("delete",))
        assert evaluate_gate(task, learning_store=store).disposition is GateDisposition.GATE_HEAVY

    def test_b1_beats_b4(self):
        """B1 (standing approval) is checked before B4 (trivially reversible).

        Both yield autonomous, but the reason should be B1.
        """
        store = FakeLearningStore(standing={"low:read"})
        task = _routine_task(capabilities=("read",), trivially_reversible=True)
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B1" in decision.rules

    def test_b4_beats_g2(self):
        """B4 (trivially reversible) suppresses G2."""
        task = _routine_task(spec_fork=True, trivially_reversible=True)
        decision = evaluate_gate(task)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B4" in decision.rules


# ===========================================================================
# Protocol conformance
# ===========================================================================

class TestProtocolConformance:
    def test_fake_store_satisfies_protocol(self):
        store = FakeLearningStore()
        assert isinstance(store, GateLearningStore)

    def test_evaluate_gate_accepts_none_store(self):
        task = _routine_task()
        decision = evaluate_gate(task, learning_store=None)
        assert isinstance(decision, GateDecision)
