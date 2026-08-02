"""Contract tests for the gate evaluator (#59).

Covers every acceptance criterion in the issue:
- G1-G5 positive cases (genuine-decision test)
- B1-B4 suppression cases (bureaucracy test)
- G4 internal-vs-third-party lock
- Fail-closed on unclassifiable input
- G1 is absolute (cannot be suppressed)
- Reversibility is the master variable for G2-G5
"""
from __future__ import annotations

import pytest

from agentic_fieldbook.gate_evaluator import (
    GateDecision,
    GateDisposition,
    GateTask,
    ObligationScope,
    Reversibility,
    evaluate_gate,
)


def _task(**overrides: object) -> GateTask:
    """Build a GateTask with low-risk irreversible defaults that fail closed."""
    fields: dict[str, object] = {
        "risk_class": "low",
        "reversibility": Reversibility.IRREVERSIBLE,
    }
    fields.update(overrides)
    return GateTask(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# G1: always-ask capabilities → GATE_HEAVY (absolute)
# ---------------------------------------------------------------------------

class TestG1AlwaysAsk:
    """G1 reuses detect_always_ask_capabilities() and routes to GATE_HEAVY."""

    @pytest.mark.parametrize("cap", [
        "delete", "drop", "truncate", "destroy",
    ])
    def test_destructive_capabilities_gate_heavy(self, cap):
        result = evaluate_gate(_task(capabilities=(cap,)))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    @pytest.mark.parametrize("cap", [
        "secret-read", "secret-write", "secret-rotate",
        "credential-read", "credential-write", "credential-rotate",
    ])
    def test_secret_capabilities_gate_heavy(self, cap):
        result = evaluate_gate(_task(capabilities=(cap,)))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_billing_capability_gates_heavy(self):
        result = evaluate_gate(_task(capabilities=("billing-change",)))
        assert result.disposition is GateDisposition.GATE_HEAVY

    def test_access_grant_gates_heavy(self):
        result = evaluate_gate(_task(capabilities=("permission-grant",)))
        assert result.disposition is GateDisposition.GATE_HEAVY

    def test_downtime_gates_heavy(self):
        result = evaluate_gate(_task(capabilities=("service-stop",)))
        assert result.disposition is GateDisposition.GATE_HEAVY

    def test_release_gates_heavy(self):
        result = evaluate_gate(_task(capabilities=("deploy",)))
        assert result.disposition is GateDisposition.GATE_HEAVY

    def test_g1_is_absolute_over_trivial_reversibility(self):
        """G1 cannot be suppressed even when trivially reversible."""
        result = evaluate_gate(_task(
            capabilities=("delete",),
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_g1_is_absolute_over_standing_approval(self):
        """G1 cannot be suppressed by standing approval (B1)."""
        result = evaluate_gate(_task(
            capabilities=("secret-read",),
            standing_approval=True,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_g1_is_absolute_over_known_preference(self):
        """G1 cannot be suppressed by known preference (B2)."""
        result = evaluate_gate(_task(
            capabilities=("billing-change",),
            known_preference=True,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_g1_lists_all_triggered_categories(self):
        result = evaluate_gate(_task(capabilities=("delete", "secret-read")))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert "destructive" in result.reason
        assert "secret-access" in result.reason


# ---------------------------------------------------------------------------
# G2-G5: genuine-decision test → GATE_LIGHT
# ---------------------------------------------------------------------------

class TestG2ThroughG5GenuineDecision:
    """G2-G5 route to GATE_LIGHT when NOT trivially reversible."""

    def test_g2_spec_fork_gates_light(self):
        result = evaluate_gate(_task(is_spec_fork=True, reversibility=Reversibility.REVERSIBLE))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G2"

    def test_g3_reversal_asymmetry_gates_light(self):
        result = evaluate_gate(_task(has_reversal_asymmetry=True, reversibility=Reversibility.REVERSIBLE))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G3"

    def test_g5_ambiguous_intent_high_blast_gates_light(self):
        result = evaluate_gate(_task(
            has_ambiguous_intent=True, blast_radius="high",
            reversibility=Reversibility.REVERSIBLE,
        ))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G5"

    def test_g5_ambiguous_intent_medium_blast_gates_light(self):
        result = evaluate_gate(_task(
            has_ambiguous_intent=True, blast_radius="medium",
            reversibility=Reversibility.REVERSIBLE,
        ))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G5"

    def test_g5_ambiguous_intent_low_blast_does_not_fire_g5(self):
        """Low blast-radius ambiguity is not a G5 genuine decision signal."""
        result = evaluate_gate(_task(
            has_ambiguous_intent=True, blast_radius="low",
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.rule != "G5"
        # Trivially reversible → autonomous (B4), not gated
        assert result.disposition is GateDisposition.AUTONOMOUS

    def test_g2_gates_when_irreversible(self):
        result = evaluate_gate(_task(is_spec_fork=True, reversibility=Reversibility.IRREVERSIBLE))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G2"


# ---------------------------------------------------------------------------
# G4: obligation lock — third-party only, internal plumbing is NOT G4
# ---------------------------------------------------------------------------

class TestG4ObligationLock:
    """G4 is LOCKED to third-party obligations only."""

    def test_g4_third_party_gates_light(self):
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.THIRD_PARTY,
            reversibility=Reversibility.REVERSIBLE,
        ))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G4-third_party"

    def test_g4_third_party_gates_when_irreversible(self):
        result = evaluate_gate(_task(obligation_scope=ObligationScope.THIRD_PARTY))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "G4-third_party"

    def test_g4_internal_plumbing_does_not_gate_light(self):
        """Internal factory plumbing (cron, monitoring) is NOT G4."""
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.INTERNAL,
            reversibility=Reversibility.REVERSIBLE,
        ))
        assert result.disposition is not GateDisposition.GATE_LIGHT
        assert result.rule == "G4-internal"
        assert result.disposition is GateDisposition.AUTONOMOUS

    def test_g4_internal_irreversible_reports(self):
        """Internal plumbing that is irreversible reports only (no gate)."""
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.INTERNAL,
            reversibility=Reversibility.IRREVERSIBLE,
        ))
        assert result.disposition is GateDisposition.REPORT_ONLY
        assert result.rule == "G4-internal"

    def test_g4_third_party_overrides_internal_signals(self):
        """Even a task that looks like internal integration gates if it's third-party."""
        result = evaluate_gate(_task(obligation_scope=ObligationScope.THIRD_PARTY))
        assert result.disposition is GateDisposition.GATE_LIGHT


# ---------------------------------------------------------------------------
# B1: standing approval → AUTONOMOUS
# ---------------------------------------------------------------------------

class TestB1StandingApproval:
    """B1: a pre-approved action class proceeds autonomously."""

    def test_b1_standing_approval_autonomous(self):
        result = evaluate_gate(_task(standing_approval=True, reversibility=Reversibility.REVERSIBLE))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B1"

    def test_b1_does_not_override_g1(self):
        result = evaluate_gate(_task(
            capabilities=("delete",), standing_approval=True,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"


# ---------------------------------------------------------------------------
# B2: known preference → AUTONOMOUS or REPORT_ONLY
# ---------------------------------------------------------------------------

class TestB2KnownPreference:
    """B2: ≥3 consistent prior choices on this fork signature."""

    def test_b2_trivially_reversible_is_autonomous(self):
        result = evaluate_gate(_task(
            known_preference=True, reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B2"

    def test_b2_non_trivial_is_report_only(self):
        result = evaluate_gate(_task(
            known_preference=True, reversibility=Reversibility.REVERSIBLE,
            is_spec_fork=True,
        ))
        assert result.disposition is GateDisposition.REPORT_ONLY
        assert result.rule == "B2"


# ---------------------------------------------------------------------------
# B4: trivially reversible → AUTONOMOUS (suppresses G2-G5)
# ---------------------------------------------------------------------------

class TestB4TrivialReversibility:
    """B4: trivially reversible tasks proceed without a gate."""

    def test_b4_suppresses_g2_spec_fork(self):
        result = evaluate_gate(_task(
            is_spec_fork=True, reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B4"

    def test_b4_suppresses_g3_asymmetry(self):
        result = evaluate_gate(_task(
            has_reversal_asymmetry=True, reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B4"

    def test_b4_suppresses_g4_third_party(self):
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.THIRD_PARTY,
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B4"

    def test_b4_suppresses_g5_ambiguous(self):
        result = evaluate_gate(_task(
            has_ambiguous_intent=True, blast_radius="high",
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B4"

    def test_b4_does_not_suppress_g1(self):
        """G1 is absolute: trivially reversible destructive still gates heavy."""
        result = evaluate_gate(_task(
            capabilities=("delete",), reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_b4_pure_trivial_task_is_autonomous(self):
        """A trivially reversible task with no other signals is autonomous."""
        result = evaluate_gate(_task(reversibility=Reversibility.TRIVIAL))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B4"


# ---------------------------------------------------------------------------
# Fail-closed: unclassifiable → GATE_LIGHT
# ---------------------------------------------------------------------------

class TestFailClosed:
    """The evaluator fails closed — never defaults to autonomous."""

    def test_unclassifiable_irreversible_no_signals_fails_closed(self):
        result = evaluate_gate(_task(reversibility=Reversibility.IRREVERSIBLE))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "fail-closed"

    def test_unknown_obligation_scope_irreversible_fails_closed(self):
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.UNKNOWN,
            reversibility=Reversibility.IRREVERSIBLE,
        ))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "fail-closed"

    def test_unknown_obligation_reversible_fails_closed(self):
        """Even reversible, unknown obligation + no approval signals fails closed."""
        result = evaluate_gate(_task(
            obligation_scope=ObligationScope.UNKNOWN,
            reversibility=Reversibility.REVERSIBLE,
        ))
        assert result.disposition is GateDisposition.GATE_LIGHT
        assert result.rule == "fail-closed"


# ---------------------------------------------------------------------------
# Evaluation order / precedence
# ---------------------------------------------------------------------------

class TestEvaluationOrder:
    """G1 is checked before B1/B2/B4. B1 before B2 before B4 before G2-G5."""

    def test_g1_beats_standing_approval_and_trivial_reversibility(self):
        result = evaluate_gate(_task(
            capabilities=("drop",),
            standing_approval=True,
            known_preference=True,
            reversibility=Reversibility.TRIVIAL,
            is_spec_fork=True,
        ))
        assert result.disposition is GateDisposition.GATE_HEAVY
        assert result.rule == "G1"

    def test_b1_beats_b2_and_b4(self):
        result = evaluate_gate(_task(
            standing_approval=True,
            known_preference=True,
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B1"

    def test_b2_beats_b4(self):
        result = evaluate_gate(_task(
            known_preference=True,
            reversibility=Reversibility.TRIVIAL,
        ))
        assert result.disposition is GateDisposition.AUTONOMOUS
        assert result.rule == "B2"


# ---------------------------------------------------------------------------
# Pure function contract
# ---------------------------------------------------------------------------

class TestPurity:
    """The evaluator must be pure: no side effects, deterministic."""

    def test_same_input_same_output(self):
        task = _task(capabilities=("delete",))
        first = evaluate_gate(task)
        second = evaluate_gate(task)
        assert first == second

    def test_gate_decision_is_frozen(self):
        task = _task(capabilities=("secret-read",))
        result = evaluate_gate(task)
        assert isinstance(result, GateDecision)
        # frozen dataclass — assignment should fail
        with pytest.raises(Exception):
            result.disposition = GateDisposition.AUTONOMOUS  # type: ignore[misc]

    def test_gate_task_is_frozen(self):
        task = _task()
        with pytest.raises(Exception):
            task.risk_class = "high"  # type: ignore[misc]
