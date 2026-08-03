"""Contract tests for the gate learning store (issue #62).

Covers every acceptance criterion:
- record_resolution appends a resolution record
- check_standing_approval True for active, False otherwise
- check_known_preference at/above threshold (default 3), False below
- configurable threshold exercised below and at threshold
- revoked standing approval returns False
- no persistence assumptions — pure in-memory implementation passes
- protocol read-side satisfies the gate_evaluator GateLearningStore Protocol
"""

from __future__ import annotations

import pytest

from agentic_fieldbook.gate_evaluator import GateLearningStore as _EvaProtocol
from agentic_fieldbook.gate_learning import (
    GateLearningStore,
    GateScope,
    InMemoryLearningStore,
    PromotionProposal,
    ResolutionRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record(store, gate_class="deploy", fork="G2", decision="approved",
            ctx="sha256:abc"):
    store.record_resolution(gate_class, fork, decision, ctx)


# ===========================================================================
# record_resolution — appends a resolution record
# ===========================================================================

class TestRecordResolution:
    """record_resolution stores the full record and feeds B2."""

    def test_appends_record(self):
        store = InMemoryLearningStore()
        store.record_resolution("deploy", "G2", "approved", "sha256:1")
        records = store._resolutions
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, ResolutionRecord)
        assert rec.gate_class == "deploy"
        assert rec.fork_signature == "G2"
        assert rec.decision == "approved"
        assert rec.context_hash == "sha256:1"

    def test_appends_multiple_records(self):
        store = InMemoryLearningStore()
        for i in range(5):
            store.record_resolution("deploy", "G2", "approved", f"sha256:{i}")
        assert len(store._resolutions) == 5

    def test_record_feeds_known_preference(self):
        store = InMemoryLearningStore()
        for _ in range(3):
            _record(store, fork="G2|G3", decision="approved")
        assert store.check_known_preference("G2|G3") is True

    def test_empty_store_no_preference(self):
        store = InMemoryLearningStore()
        assert store.check_known_preference("G2") is False


# ===========================================================================
# check_standing_approval — B1
# ===========================================================================

class TestCheckStandingApproval:
    """check_standing_approval returns True for active approvals only."""

    def test_false_when_never_granted(self):
        store = InMemoryLearningStore()
        assert store.check_standing_approval("deploy") is False

    def test_true_after_grant(self):
        store = InMemoryLearningStore()
        store.grant_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is True

    def test_false_for_unrelated_action_class(self):
        store = InMemoryLearningStore()
        store.grant_standing_approval("deploy")
        assert store.check_standing_approval("rollback") is False


# ===========================================================================
# revoke_standing_approval — revoked returns False
# ===========================================================================

class TestRevokeStandingApproval:
    """A revoked standing approval returns False from check_standing_approval."""

    def test_false_after_revoke(self):
        store = InMemoryLearningStore()
        store.grant_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is True
        store.revoke_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is False

    def test_revoke_without_grant_is_noop(self):
        store = InMemoryLearningStore()
        store.revoke_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is False

    def test_revoke_isolated(self):
        store = InMemoryLearningStore()
        store.grant_standing_approval("deploy")
        store.grant_standing_approval("rollback")
        store.revoke_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is False
        assert store.check_standing_approval("rollback") is True

    def test_re_grant_after_revoke(self):
        store = InMemoryLearningStore()
        store.grant_standing_approval("deploy")
        store.revoke_standing_approval("deploy")
        store.grant_standing_approval("deploy")
        assert store.check_standing_approval("deploy") is True


# ===========================================================================
# check_known_preference — B2, configurable threshold
# ===========================================================================

class TestCheckKnownPreference:
    """check_known_preference at/above and below threshold."""

    def test_false_below_default_threshold(self):
        store = InMemoryLearningStore()
        for _ in range(2):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2") is False

    def test_true_at_default_threshold(self):
        store = InMemoryLearningStore()
        for _ in range(3):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2") is True

    def test_true_above_default_threshold(self):
        store = InMemoryLearningStore()
        for _ in range(5):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2") is True

    def test_configurable_threshold_below(self):
        store = InMemoryLearningStore()
        for _ in range(4):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2", threshold=5) is False

    def test_configurable_threshold_at(self):
        store = InMemoryLearningStore()
        for _ in range(4):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2", threshold=4) is True

    def test_configurable_threshold_one(self):
        store = InMemoryLearningStore()
        _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2", threshold=1) is True

    def test_threshold_zero_always_true(self):
        store = InMemoryLearningStore()
        assert store.check_known_preference("unseen", threshold=0) is True

    def test_negative_threshold_always_true(self):
        store = InMemoryLearningStore()
        assert store.check_known_preference("unseen", threshold=-1) is True

    def test_consistency_required_mixed_decisions(self):
        """Two approvals + two rejections on same fork: not consistent at 3."""
        store = InMemoryLearningStore()
        _record(store, fork="G2", decision="approved")
        _record(store, fork="G2", decision="approved")
        _record(store, fork="G2", decision="rejected")
        _record(store, fork="G2", decision="rejected")
        # no single decision reaches 3
        assert store.check_known_preference("G2", threshold=3) is False

    def test_consistency_at_threshold_with_noise(self):
        """Three approvals + two rejections: preference is approved."""
        store = InMemoryLearningStore()
        for _ in range(3):
            _record(store, fork="G2", decision="approved")
        for _ in range(2):
            _record(store, fork="G2", decision="rejected")
        assert store.check_known_preference("G2", threshold=3) is True

    def test_isolated_per_fork_signature(self):
        store = InMemoryLearningStore()
        for _ in range(3):
            _record(store, fork="G2", decision="approved")
        assert store.check_known_preference("G2") is True
        assert store.check_known_preference("G3") is False


# ===========================================================================
# Protocol alignment — satisfies the evaluator's GateLearningStore
# ===========================================================================

class TestProtocolAlignment:
    """The concrete store satisfies the gate_evaluator Protocol."""

    def test_isinstance_evaluator_protocol(self):
        store = InMemoryLearningStore()
        # runtime_checkable Protocol — structural isinstance check
        assert isinstance(store, _EvaProtocol)

    def test_evaluator_consumes_store_b1(self):
        """evaluate_gate routes AUTONOMOUS when B1 standing approval exists.

        Uses ``provision`` (not an always-ask capability) so G1 does not
        short-circuit.  ``action_class`` is set explicitly so the derived
        B1 key matches the granted approval.
        """
        from agentic_fieldbook.gate_evaluator import (
            GateDisposition,
            GateTask,
            ObligationType,
            evaluate_gate,
        )

        store = InMemoryLearningStore()
        store.grant_standing_approval("provision-vm")

        task = GateTask(
            risk_class="high",
            capabilities=("provision",),
            action_class="provision-vm",
            spec_fork=True,
            obligation_type=ObligationType.THIRD_PARTY,
        )
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B1" in decision.rules

    def test_evaluator_consumes_store_b2(self):
        """evaluate_gate routes AUTONOMOUS when B2 known preference exists.

        Uses ``provision`` (not always-ask) and records three consistent
        resolutions on the fork signature the evaluator will derive.
        """
        from agentic_fieldbook.gate_evaluator import (
            GateDisposition,
            GateTask,
            ObligationType,
            evaluate_gate,
        )

        store = InMemoryLearningStore()
        # fork signature derived from markers: G2|G4
        for _ in range(3):
            store.record_resolution("provision", "G2|G4", "approved", "sha256:x")

        task = GateTask(
            risk_class="high",
            capabilities=("provision",),
            spec_fork=True,
            obligation_type=ObligationType.THIRD_PARTY,
        )
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS
        assert "B2" in decision.rules


# ===========================================================================
# Subclassing — persistence adapters implement the ABC
# ===========================================================================

class TestABCContract:
    """GateLearningStore is an abstract base; subclasses must implement all."""

    def test_cannot_instantiate_abc_directly(self):
        with pytest.raises(TypeError):
            GateLearningStore()  # type: ignore[abstract]

    def test_subclass_must_implement_all_methods(self):
        # Missing methods -> TypeError on instantiation
        with pytest.raises(TypeError):

            class Partial(GateLearningStore):  # type: ignore[abstract]
                def check_standing_approval(self, action_class: str) -> bool:
                    return False

            Partial()


# ===========================================================================
# Issue #63 — Pattern promotion + scope-change re-gate
# ===========================================================================

_SCOPE_A = GateScope(
    target="prod-cluster", blast_radius="single-node", permission_surface="deploy-token",
)
_SCOPE_B_TARGET = GateScope(
    target="staging-cluster", blast_radius="single-node", permission_surface="deploy-token",
)
_SCOPE_B_BLAST = GateScope(
    target="prod-cluster", blast_radius="region-wide", permission_surface="deploy-token",
)
_SCOPE_B_PERM = GateScope(
    target="prod-cluster", blast_radius="single-node", permission_surface="admin-api",
)


def _seed(store, fork="G2", decision="approved", gate_class="deploy",
          n=3, scope=None):
    """Record *n* consistent resolutions on *fork*."""
    for i in range(n):
        store.record_resolution(gate_class, fork, decision, f"sha256:{i}", scope=scope)


# ---------------------------------------------------------------------------
# propose_promotion — threshold behaviour
# ---------------------------------------------------------------------------

class TestProposePromotion:
    """propose_promotion returns a proposal at threshold, None below."""

    def test_propose_below_threshold_returns_none(self):
        store = InMemoryLearningStore()
        _seed(store, n=2)
        assert store.propose_promotion("G2") is None

    def test_propose_at_threshold_returns_proposal(self):
        store = InMemoryLearningStore()
        _seed(store, n=3)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        assert isinstance(proposal, PromotionProposal)
        assert proposal.fork_signature == "G2"
        assert proposal.gate_class == "deploy"
        assert proposal.proposed_action == "auto-approve"

    def test_propose_above_threshold_returns_proposal(self):
        store = InMemoryLearningStore()
        _seed(store, n=5)
        proposal = store.propose_promotion("G2")
        assert proposal is not None

    def test_proposal_carries_evidence(self):
        """The proposal's evidence is the consistent prior decisions."""
        store = InMemoryLearningStore()
        _seed(store, n=3)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        assert len(proposal.evidence) == 3
        assert all(isinstance(r, ResolutionRecord) for r in proposal.evidence)
        assert all(r.decision == "approved" for r in proposal.evidence)

    def test_propose_configurable_threshold(self):
        store = InMemoryLearningStore()
        _seed(store, n=2)
        assert store.propose_promotion("G2", threshold=2) is not None

    def test_propose_no_consistency_no_proposal(self):
        """Mixed decisions below threshold do not produce a proposal."""
        store = InMemoryLearningStore()
        _record(store, fork="G2", decision="approved")
        _record(store, fork="G2", decision="rejected")
        assert store.propose_promotion("G2") is None


# ---------------------------------------------------------------------------
# One-time signal — Jay sees the proposal once
# ---------------------------------------------------------------------------

class TestPromotionOneTime:
    """A promotion proposal is a one-time signal."""

    def test_second_call_returns_none_after_first_proposal(self):
        store = InMemoryLearningStore()
        _seed(store, n=3)
        first = store.propose_promotion("G2")
        assert first is not None
        second = store.propose_promotion("G2")
        assert second is None

    def test_seen_once_even_if_not_decided(self):
        """Surfacing the proposal consumes it, with or without a decision."""
        store = InMemoryLearningStore()
        _seed(store, n=3)
        p = store.propose_promotion("G2")
        assert p is not None
        # No accept/reject — still gone.
        assert store.propose_promotion("G2") is None


# ---------------------------------------------------------------------------
# accept_promotion — class becomes autonomous via standing approval
# ---------------------------------------------------------------------------

class TestAcceptPromotion:
    """accept_promotion makes the class autonomous and records scope."""

    def test_accept_grants_standing_approval(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, gate_class="deploy")
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        assert store.check_standing_approval("deploy") is False
        store.accept_promotion(proposal)
        assert store.check_standing_approval("deploy") is True

    def test_accept_records_scope_baseline(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        # Same scope -> no material change.
        assert store.check_material_scope_change("G2", _SCOPE_A) is False

    def test_accept_with_no_scope_no_baseline(self):
        """If evidence carried no scope, re-gate cannot fire."""
        store = InMemoryLearningStore()
        _seed(store, n=3)  # no scope
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_material_scope_change("G2", _SCOPE_A) is False

    def test_accept_makes_evaluator_route_autonomous(self):
        """After acceptance, B1 standing approval short-circuits the gate."""
        from agentic_fieldbook.gate_evaluator import (
            GateDisposition,
            GateTask,
            ObligationType,
            evaluate_gate,
        )

        store = InMemoryLearningStore()
        # fork signature the evaluator derives for this task is G2|G4
        for _ in range(3):
            store.record_resolution(
                "provision", "G2|G4", "approved", "sha256:x",
            )
        proposal = store.propose_promotion("G2|G4")
        assert proposal is not None
        store.accept_promotion(proposal)

        task = GateTask(
            risk_class="high",
            capabilities=("provision",),
            action_class="provision",
            spec_fork=True,
            obligation_type=ObligationType.THIRD_PARTY,
        )
        decision = evaluate_gate(task, learning_store=store)
        assert decision.disposition is GateDisposition.AUTONOMOUS


# ---------------------------------------------------------------------------
# reject_promotion — class stays gated, one-directional decay
# ---------------------------------------------------------------------------

class TestRejectPromotion:
    """reject_promotion keeps the class gated; no auto-demotion."""

    def test_reject_does_not_grant_approval(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, gate_class="deploy")
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.reject_promotion(proposal)
        assert store.check_standing_approval("deploy") is False

    def test_reject_suppresses_re_proposal(self):
        store = InMemoryLearningStore()
        _seed(store, n=3)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.reject_promotion(proposal)
        assert store.propose_promotion("G2") is None

    def test_re_proposal_after_fresh_consistent_run(self):
        """After rejection, a fresh batch of resolutions can re-propose."""
        store = InMemoryLearningStore()
        _seed(store, n=3)
        p1 = store.propose_promotion("G2")
        assert p1 is not None
        store.reject_promotion(p1)
        # Fresh engagement clears the rejection and crosses threshold again.
        _seed(store, n=3)
        p2 = store.propose_promotion("G2")
        assert p2 is not None
        assert len(p2.evidence) >= 3

    def test_reject_does_not_demote_promoted_class(self):
        """One-directional decay: rejecting a different fork never revokes
        an existing promotion."""
        store = InMemoryLearningStore()
        _seed(store, fork="G2", n=3, gate_class="deploy")
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_standing_approval("deploy") is True
        # A rejection on a different fork must not touch G2's approval.
        _seed(store, fork="G3", n=3, gate_class="rollback")
        p3 = store.propose_promotion("G3")
        assert p3 is not None
        store.reject_promotion(p3)
        assert store.check_standing_approval("deploy") is True


# ---------------------------------------------------------------------------
# check_material_scope_change — re-gate on material change
# ---------------------------------------------------------------------------

class TestMaterialScopeChange:
    """check_material_scope_change True on material change, False otherwise."""

    def test_target_change_is_material(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_material_scope_change("G2", _SCOPE_B_TARGET) is True

    def test_blast_radius_change_is_material(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_material_scope_change("G2", _SCOPE_B_BLAST) is True

    def test_permission_surface_change_is_material(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_material_scope_change("G2", _SCOPE_B_PERM) is True

    def test_unchanged_scope_not_material(self):
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A)
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        assert store.check_material_scope_change("G2", _SCOPE_A) is False

    def test_no_baseline_no_material_change(self):
        """Never-promoted fork or no scope recorded -> False (no re-gate)."""
        store = InMemoryLearningStore()
        assert store.check_material_scope_change("G2", _SCOPE_A) is False

    def test_scope_change_re_gates_even_if_promoted(self):
        """AC: a material scope change causes re-gate even for a promoted
        fork.  The evaluator sees the standing approval but the caller
        must consult check_material_scope_change to re-open."""
        store = InMemoryLearningStore()
        _seed(store, n=3, scope=_SCOPE_A, gate_class="deploy")
        proposal = store.propose_promotion("G2")
        assert proposal is not None
        store.accept_promotion(proposal)
        # Standing approval is active...
        assert store.check_standing_approval("deploy") is True
        # ...but scope changed -> caller re-gates.
        assert store.check_material_scope_change("G2", _SCOPE_B_TARGET) is True


# ---------------------------------------------------------------------------
# Scope recorded on ResolutionRecord
# ---------------------------------------------------------------------------

class TestResolutionScopeField:
    """record_resolution stores the scope on the record for audit/baseline."""

    def test_scope_stored_on_record(self):
        store = InMemoryLearningStore()
        store.record_resolution(
            "deploy", "G2", "approved", "sha256:1", scope=_SCOPE_A,
        )
        assert store._resolutions[0].scope == _SCOPE_A

    def test_scope_defaults_none(self):
        store = InMemoryLearningStore()
        store.record_resolution("deploy", "G2", "approved", "sha256:1")
        assert store._resolutions[0].scope is None
