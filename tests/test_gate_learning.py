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
    InMemoryLearningStore,
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
