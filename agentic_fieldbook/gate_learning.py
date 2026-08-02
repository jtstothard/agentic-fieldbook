"""Gate learning store: deployment-neutral protocol for recording gate
resolutions and answering the bureaucracy questions B1 and B2.

The gate evaluator (``gate_evaluator.py``) calls this store *before* the
genuine-decision test:

- **B1** — ``check_standing_approval(action_class)``: does a standing
  approval cover this entire class of action?  If yes, the task runs
  autonomously without re-gating.
- **B2** — ``check_known_preference(fork_signature, threshold=3)``: have
  we seen >= *threshold* consistent human choices on this same fork?  If
  yes, the preference is learned and the task runs autonomously.

This module defines the full management interface (record, grant, revoke,
check) plus a reference in-memory implementation.  The read-side methods
(``check_standing_approval``, ``check_known_preference``) align with the
``GateLearningStore`` Protocol already defined in ``gate_evaluator.py``;
any concrete store implementing this ABC satisfies the evaluator's
protocol.

The promotion layer (issue #63) adds the two remaining learning-model
mechanisms from the HITL taxonomy:

- **Pattern promotion** — after >= *threshold* consistent resolutions on a
  fork, :meth:`propose_promotion` surfaces a one-time proposal.  On
  acceptance the class becomes autonomous via standing approval; on
  rejection it stays gated.  Promotion is opt-out, never silent.
- **Scope-change re-gate** — once a fork is promoted under a recorded
  :class:`GateScope`, :meth:`check_material_scope_change` returns ``True``
  if the current scope (target, blast radius, or permission surface)
  differs from the established scope, which re-opens the gate even for a
  promoted class.

Persistence is adapter-owned: the ABC makes no I/O assumptions.  The
in-memory implementation is the reference that contract tests exercise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ResolutionRecord:
    """A single recorded gate resolution.

    Attributes:
        gate_class: The action-class key under which the resolution was
            recorded (maps to ``action_class`` in the evaluator).
        fork_signature: Canonical fork-signature key for B2 matching.
        decision: The human decision string (e.g. ``"approved"``,
            ``"rejected"``).  Consistency is measured by exact string
            equality.
        context_hash: Digest of the surrounding context for audit/dedup.
        scope: Optional :class:`GateScope` captured at resolution time.
            When present it is the baseline against which later scope
            changes are measured.  ``None`` means the scope was not
            recorded (legacy resolutions from issue #62).
    """

    gate_class: str
    fork_signature: str
    decision: str
    context_hash: str
    scope: Optional["GateScope"] = None


@dataclass(frozen=True)
class GateScope:
    """The scope under which a pattern (fork signature) was established.

    A material change in *any* field triggers re-gate for a promoted
    class.  Fields are free-form strings so different deployment contexts
    can encode their own vocabulary; equality is exact string comparison.

    Attributes:
        target: What the action operates on (e.g. ``"prod-cluster"``,
            ``"repo:jtstothard/x"``).
        blast_radius: Worst-case impact descriptor (e.g. ``"single-node"``,
            ``"region-wide"``).
        permission_surface: The access surface exercised (e.g.
            ``"deploy-token"``, ``"admin-api"``).
    """

    target: str
    blast_radius: str
    permission_surface: str


@dataclass(frozen=True)
class PromotionProposal:
    """A one-time proposal to promote a fork signature to autonomous.

    Attributes:
        fork_signature: The canonical fork key whose consistent
            resolutions triggered the proposal.
        gate_class: The action-class key the promotion would cover.
        evidence: The prior :class:`ResolutionRecord` instances that
            established the consistent pattern.  Never empty for a real
            proposal.
        proposed_action: Always ``"auto-approve"``; explicit so the
            proposal is self-describing.
    """

    fork_signature: str
    gate_class: str
    evidence: tuple[ResolutionRecord, ...]
    proposed_action: str = "auto-approve"


class GateLearningStore(ABC):
    """Deployment-neutral learning-store seam.

    Subclasses implement persistence (SQLite, file, remote service, etc.).
    The in-memory :class:`InMemoryLearningStore` is the reference
    implementation.

    Read-side contract (consumed by the gate evaluator):

    - :meth:`check_standing_approval` — B1
    - :meth:`check_known_preference` — B2

    Write-side contract (management):

    - :meth:`record_resolution` — append a resolution (feeds B2)
    - :meth:`grant_standing_approval` — pre-authorise an action class (feeds B1)
    - :meth:`revoke_standing_approval` — withdraw a standing approval

    Promotion contract (issue #63):

    - :meth:`propose_promotion` — one-time promotion proposal (or ``None``)
    - :meth:`accept_promotion` — promote via standing approval + scope snapshot
    - :meth:`reject_promotion` — decline; class stays gated
    - :meth:`check_material_scope_change` — re-gate test for promoted forks
    """

    # -- B2: known preference ---------------------------------------------

    @abstractmethod
    def record_resolution(
        self,
        gate_class: str,
        fork_signature: str,
        decision: str,
        context_hash: str,
        scope: Optional[GateScope] = None,
    ) -> None:
        """Append a resolution record to the store.

        Each record counts toward the known-preference tally (B2) for its
        ``fork_signature``.  A preference is "known" when >= *threshold*
        records share the same ``decision`` value.

        *scope*, if given, is stored on the record and becomes the
        baseline for :meth:`check_material_scope_change` once the fork is
        promoted.  Omitting it preserves issue-#62 behaviour.
        """
        ...

    @abstractmethod
    def check_known_preference(
        self, fork_signature: str, threshold: int = 3,
    ) -> bool:
        """True when >= *threshold* consistent decisions exist for
        *fork_signature* (B2).

        Consistency is exact: the most common ``decision`` value must
        appear at least *threshold* times.
        """
        ...

    # -- B1: standing approval --------------------------------------------

    @abstractmethod
    def grant_standing_approval(self, action_class: str) -> None:
        """Grant a standing approval for *action_class* (B1).

        After this call, :meth:`check_standing_approval` returns ``True``
        for *action_class* until it is revoked.
        """
        ...

    @abstractmethod
    def revoke_standing_approval(self, action_class: str) -> None:
        """Revoke a standing approval for *action_class*.

        After this call (or if no approval was ever granted),
        :meth:`check_standing_approval` returns ``False``.
        """
        ...

    @abstractmethod
    def check_standing_approval(self, action_class: str) -> bool:
        """True when an active standing approval covers *action_class* (B1).

        A revoked or never-granted approval returns ``False``.
        """
        ...

    # -- Promotion: pattern autonomy + scope-change re-gate (#63) ---------

    @abstractmethod
    def propose_promotion(
        self,
        fork_signature: str,
        threshold: int = 3,
    ) -> Optional[PromotionProposal]:
        """Return a one-time promotion proposal for *fork_signature*.

        Returns a :class:`PromotionProposal` when the fork has >=
        *threshold* consistent resolutions AND no proposal has been
        surfaced or decided for it yet.  After the first call that
        returns a proposal (and regardless of subsequent accept/reject),
        subsequent calls return ``None`` — the proposal is seen once.

        Returns ``None`` when the consistency threshold is not met, or
        when a proposal has already been surfaced/decided for this fork.
        """
        ...

    @abstractmethod
    def accept_promotion(self, proposal: PromotionProposal) -> None:
        """Accept *proposal*: the class becomes autonomous.

        Grants a standing approval for the proposal's ``gate_class`` and
        records the scope snapshot established by the evidence, so that
        later :meth:`check_material_scope_change` calls have a baseline.
        A previously-rejected fork may be promoted by a later proposal.
        """
        ...

    @abstractmethod
    def reject_promotion(self, proposal: PromotionProposal) -> None:
        """Reject *proposal*: the class stays gated.

        Records the rejection so :meth:`propose_promotion` does not
        re-surface the same fork until a fresh threshold of consistent
        resolutions accumulates.  Decay is one-directional: rejection
        never auto-demotes an already-promoted class, and promotion never
        auto-demotes without a scope change.
        """
        ...

    @abstractmethod
    def check_material_scope_change(
        self,
        fork_signature: str,
        current_scope: GateScope,
    ) -> bool:
        """True when *current_scope* differs materially from the scope
        recorded when *fork_signature* was promoted.

        Material means any of target, blast radius, or permission surface
        differ by exact string equality.  Returns ``False`` when:

        - the fork was never promoted (no baseline scope), or
        - the fork was promoted but no scope was recorded, or
        - *current_scope* equals the recorded baseline exactly.

        A ``True`` result tells the evaluator to re-gate the instance,
        even if the fork signature was previously promoted.
        """
        ...


class InMemoryLearningStore(GateLearningStore):
    """Reference in-memory implementation of :class:`GateLearningStore`.

    Thread-unsafe by design — persistence adapters handle concurrency.
    All state lives in plain Python data structures so contract tests
    can exercise every AC without I/O.
    """

    def __init__(self) -> None:
        self._resolutions: list[ResolutionRecord] = []
        self._standing: set[str] = set()
        # Forks for which a promotion proposal has already been surfaced.
        self._promoted: set[str] = set()
        # Forks whose proposal was rejected; re-eligible only after a
        # fresh batch of consistent resolutions crosses threshold again.
        self._rejected: set[str] = set()
        # Scope baseline recorded at promotion time, keyed by fork.
        self._promotion_scopes: dict[str, GateScope] = {}
        # Maps a promoted fork to the action_class it granted, so
        # scope-change re-gate can revoke the right standing approval.
        self._promotion_classes: dict[str, str] = {}

    # -- B2: known preference ---------------------------------------------

    def record_resolution(
        self,
        gate_class: str,
        fork_signature: str,
        decision: str,
        context_hash: str,
        scope: Optional[GateScope] = None,
    ) -> None:
        self._resolutions.append(
            ResolutionRecord(
                gate_class=gate_class,
                fork_signature=fork_signature,
                decision=decision,
                context_hash=context_hash,
                scope=scope,
            )
        )
        # A fresh resolution after a rejection means the human is engaging
        # again; clear the rejection so a new proposal can surface once
        # the consistency threshold is met anew.
        self._rejected.discard(fork_signature)

    def check_known_preference(
        self, fork_signature: str, threshold: int = 3,
    ) -> bool:
        if threshold <= 0:
            return True
        counts: Counter[str] = Counter()
        for rec in self._resolutions:
            if rec.fork_signature == fork_signature:
                counts[rec.decision] += 1
        return any(count >= threshold for count in counts.values())

    # -- B1: standing approval --------------------------------------------

    def grant_standing_approval(self, action_class: str) -> None:
        self._standing.add(action_class)

    def revoke_standing_approval(self, action_class: str) -> None:
        self._standing.discard(action_class)

    def check_standing_approval(self, action_class: str) -> bool:
        return action_class in self._standing

    # -- Promotion: pattern autonomy + scope-change re-gate (#63) ---------

    def _consistent_evidence(
        self, fork_signature: str, threshold: int,
    ) -> list[ResolutionRecord]:
        """Return the evidence for the dominant decision if it meets
        *threshold*; otherwise an empty list."""
        by_decision: defaultdict[str, list[ResolutionRecord]] = defaultdict(list)
        for rec in self._resolutions:
            if rec.fork_signature == fork_signature:
                by_decision[rec.decision].append(rec)
        # Pick the decision with the most records; ties resolve arbitrarily
        # but only matter when both are below threshold.
        if not by_decision:
            return []
        dominant = max(by_decision.values(), key=len)
        return list(dominant) if len(dominant) >= threshold else []

    def propose_promotion(
        self,
        fork_signature: str,
        threshold: int = 3,
    ) -> Optional[PromotionProposal]:
        # One-time signal: already surfaced, accepted, or rejected -> None.
        if fork_signature in self._promoted:
            return None
        if fork_signature in self._rejected:
            return None
        evidence = self._consistent_evidence(fork_signature, threshold)
        if not evidence:
            return None
        gate_class = evidence[-1].gate_class
        proposal = PromotionProposal(
            fork_signature=fork_signature,
            gate_class=gate_class,
            evidence=tuple(evidence),
        )
        # Mark as surfaced so the proposal is seen exactly once.
        self._promoted.add(fork_signature)
        return proposal

    def accept_promotion(self, proposal: PromotionProposal) -> None:
        fork = proposal.fork_signature
        gate_class = proposal.gate_class
        self._promoted.add(fork)
        self._rejected.discard(fork)
        self.grant_standing_approval(gate_class)
        self._promotion_classes[fork] = gate_class
        # Record the scope baseline from the most recent evidence record
        # that carried a scope; if none did, no baseline is set (re-gate
        # cannot fire for this fork — matching the "promoted but no scope"
        # clause in check_material_scope_change).
        for rec in reversed(proposal.evidence):
            if rec.scope is not None:
                self._promotion_scopes[fork] = rec.scope
                break

    def reject_promotion(self, proposal: PromotionProposal) -> None:
        fork = proposal.fork_signature
        # Mark rejected so the same evidence does not re-propose.  A
        # future batch of consistent resolutions (record_resolution clears
        # the rejection) can earn a fresh proposal.
        self._rejected.add(fork)
        # Rejection does not revoke an existing standing approval: the
        # proposal may have been superseded by an earlier acceptance, and
        # one-directional decay means we never auto-demote.
        self._promoted.discard(fork)

    def check_material_scope_change(
        self,
        fork_signature: str,
        current_scope: GateScope,
    ) -> bool:
        baseline = self._promotion_scopes.get(fork_signature)
        if baseline is None:
            return False
        return baseline != current_scope


__all__ = [
    "GateLearningStore",
    "InMemoryLearningStore",
    "ResolutionRecord",
    "GateScope",
    "PromotionProposal",
]
