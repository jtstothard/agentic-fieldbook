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

Persistence is adapter-owned: the ABC makes no I/O assumptions.  The
in-memory implementation is the reference that contract tests exercise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass


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
    """

    gate_class: str
    fork_signature: str
    decision: str
    context_hash: str


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
    """

    # -- B2: known preference ---------------------------------------------

    @abstractmethod
    def record_resolution(
        self,
        gate_class: str,
        fork_signature: str,
        decision: str,
        context_hash: str,
    ) -> None:
        """Append a resolution record to the store.

        Each record counts toward the known-preference tally (B2) for its
        ``fork_signature``.  A preference is "known" when >= *threshold*
        records share the same ``decision`` value.
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


class InMemoryLearningStore(GateLearningStore):
    """Reference in-memory implementation of :class:`GateLearningStore`.

    Thread-unsafe by design — persistence adapters handle concurrency.
    All state lives in plain Python data structures so contract tests
    can exercise every AC without I/O.
    """

    def __init__(self) -> None:
        self._resolutions: list[ResolutionRecord] = []
        self._standing: set[str] = set()

    # -- B2: known preference ---------------------------------------------

    def record_resolution(
        self,
        gate_class: str,
        fork_signature: str,
        decision: str,
        context_hash: str,
    ) -> None:
        self._resolutions.append(
            ResolutionRecord(
                gate_class=gate_class,
                fork_signature=fork_signature,
                decision=decision,
                context_hash=context_hash,
            )
        )

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


__all__ = [
    "GateLearningStore",
    "InMemoryLearningStore",
    "ResolutionRecord",
]
