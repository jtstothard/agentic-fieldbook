"""Gate evaluator: genuine-decision test (G1-G5) and bureaucracy test (B1-B4).

Classifies a planned task into one of four dispositions at the
PLANNED -> APPROVED lifecycle transition.  Pure function -- no side effects,
no I/O.  Classification only.

G1 reuses ``detect_always_ask_capabilities()`` from ``governance.py``.
G2-G5 use caller-supplied contract fields plus a reversibility flag.
B1 (standing approval) and B2 (known preference) are checked via an
injected ``GateLearningStore`` protocol before the genuine-decision test.
B4 (trivially reversible) is evaluated from the caller-supplied
reversibility flag -- the evaluator does not infer reversibility.

The evaluator fails closed (returns ``GATE_LIGHT``) when it cannot classify.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .governance import detect_always_ask_capabilities


class GateDisposition(str, Enum):
    """Four possible gate dispositions for a planned task."""

    AUTONOMOUS = "autonomous"
    REPORT_ONLY = "report_only"
    GATE_LIGHT = "gate_light"
    GATE_HEAVY = "gate_heavy"


class ObligationType(str, Enum):
    """Classification of an obligation for G4 evaluation.

    G4 fires ONLY for ``THIRD_PARTY`` obligations.  Internal factory plumbing
    (``INTERNAL``) does not gate -- a CEO does not approve every internal tool.
    """

    NONE = "none"
    INTERNAL = "internal"        # cron, monitoring, internal integration, self-hosted
    THIRD_PARTY = "third_party"  # new paid SaaS, vendor relationship, external credential


@dataclass(frozen=True)
class GateTask:
    """Pure input to the gate evaluator -- caller-supplied, no inference.

    The caller fills in every field; the evaluator never guesses.  This makes
    the evaluator deterministic and fully testable.
    """

    risk_class: str
    capabilities: tuple[str, ...]

    # Reversibility (caller-supplied -- evaluator does not infer)
    trivially_reversible: bool = False

    # Genuine-decision markers (caller-supplied)
    spec_fork: bool = False                         # G2
    reversal_asymmetry: bool = False                 # G3
    obligation_type: ObligationType = ObligationType.NONE  # G4
    ambiguous_intent_high_blast: bool = False        # G5

    # Optional override for learning-store matching (B1/B2).  When empty the
    # evaluator derives a canonical value from the other fields.
    action_class: str = ""
    fork_signature: str = ""


@dataclass(frozen=True)
class GateDecision:
    """Result of gate evaluation -- disposition plus traceable reason."""

    disposition: GateDisposition
    reason: str
    rules: tuple[str, ...] = ()


@runtime_checkable
class GateLearningStore(Protocol):
    """Protocol for the learning model consumed by B1/B2 checks.

    The evaluator calls this *before* the genuine-decision test.  The store is
    deployment-neutral; persistence is adapter-owned.
    """

    def check_standing_approval(self, action_class: str) -> bool:
        """True when a standing approval covers *action_class* (B1)."""
        ...

    def check_known_preference(self, fork_signature: str, threshold: int = 3) -> bool:
        """True when >=*threshold* consistent prior choices on *fork_signature* (B2)."""
        ...


_VALID_RISK_CLASSES = frozenset({"low", "medium", "high"})


# ---------------------------------------------------------------------------
# Canonical key derivation (pure helpers)
# ---------------------------------------------------------------------------

def _derive_action_class(task: GateTask) -> str:
    """Canonical action-class key for B1 standing-approval matching."""
    if task.action_class:
        return task.action_class
    caps = "|".join(sorted(cap.lower() for cap in task.capabilities))
    return f"{task.risk_class}:{caps}"


def _derive_fork_signature(task: GateTask) -> str:
    """Canonical fork-signature key for B2 known-preference matching."""
    if task.fork_signature:
        return task.fork_signature
    markers: list[str] = []
    if task.spec_fork:
        markers.append("G2")
    if task.reversal_asymmetry:
        markers.append("G3")
    if task.obligation_type is ObligationType.THIRD_PARTY:
        markers.append("G4")
    if task.ambiguous_intent_high_blast:
        markers.append("G5")
    return "|".join(markers)


def _genuine_decision_rules(task: GateTask) -> list[str]:
    """Return the G2-G5 rule names that fire for *task*.

    G4 only fires for ``THIRD_PARTY`` -- internal plumbing never appears here.
    """
    matched: list[str] = []
    if task.spec_fork:
        matched.append("G2")
    if task.reversal_asymmetry:
        matched.append("G3")
    if task.obligation_type is ObligationType.THIRD_PARTY:
        matched.append("G4")
    if task.ambiguous_intent_high_blast:
        matched.append("G5")
    return matched


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def evaluate_gate(
    task: GateTask,
    learning_store: GateLearningStore | None = None,
) -> GateDecision:
    """Evaluate a planned task and return its gate disposition.

    Decision flow (first match wins):

    1. **Fail-closed** -- invalid ``risk_class`` -> ``GATE_LIGHT``.
    2. **G1** (always-ask) -- absolute; always ``GATE_HEAVY``, nothing overrides.
    3. **B1** (standing approval) -> ``AUTONOMOUS``.
    4. **B2** (known preference, >=3 consistent) -> ``AUTONOMOUS``.
    5. **B4** (trivially reversible) -> ``AUTONOMOUS`` (suppresses G2-G5).
    6. **G2-G5** (genuine decision, not trivially reversible) -> ``GATE_LIGHT``.
    7. **Internal plumbing** -> ``REPORT_ONLY`` (visible, not gated).
    8. **Default** -- routine task -> ``AUTONOMOUS``.

    Reversibility is the master variable for G2-G5: a trivially reversible task
    never gates even if it matches a genuine-decision category (except G1,
    which is absolute).
    """
    # 1 -- Fail-closed on unclassifiable input
    if task.risk_class not in _VALID_RISK_CLASSES:
        return GateDecision(
            disposition=GateDisposition.GATE_LIGHT,
            reason=f"unclassifiable: invalid risk_class {task.risk_class!r}",
            rules=("fail-closed",),
        )

    # 2 -- G1: always-ask (absolute, nothing overrides)
    always_ask = detect_always_ask_capabilities(task.capabilities)
    if always_ask:
        cats = ", ".join(cat.value for cat in always_ask)
        return GateDecision(
            disposition=GateDisposition.GATE_HEAVY,
            reason=f"always-ask capabilities: {cats}",
            rules=("G1",),
        )

    action_class = _derive_action_class(task)
    fork_sig = _derive_fork_signature(task)

    # 3 -- B1: standing approval
    if learning_store is not None:
        if learning_store.check_standing_approval(action_class):
            return GateDecision(
                disposition=GateDisposition.AUTONOMOUS,
                reason=f"standing approval covers action class: {action_class}",
                rules=("B1",),
            )

    # 4 -- B2: known preference (only meaningful when a fork exists)
    if learning_store is not None and fork_sig:
        if learning_store.check_known_preference(fork_sig):
            return GateDecision(
                disposition=GateDisposition.AUTONOMOUS,
                reason=f"known preference (>=3) for fork signature: {fork_sig}",
                rules=("B2",),
            )

    # 5 -- B4: trivially reversible (master variable, suppresses G2-G5)
    if task.trivially_reversible:
        return GateDecision(
            disposition=GateDisposition.AUTONOMOUS,
            reason="trivially reversible within session, no external side effect",
            rules=("B4",),
        )

    # 6 -- G2-G5: genuine decision (not trivially reversible)
    genuine_rules = _genuine_decision_rules(task)
    if genuine_rules:
        return GateDecision(
            disposition=GateDisposition.GATE_LIGHT,
            reason=f"genuine-decision markers: {', '.join(genuine_rules)}",
            rules=tuple(genuine_rules),
        )

    # 7 -- Internal plumbing: visible but not gated
    if task.obligation_type is ObligationType.INTERNAL:
        return GateDecision(
            disposition=GateDisposition.REPORT_ONLY,
            reason="internal factory plumbing (not a third-party obligation)",
            rules=("not-G4",),
        )

    # 8 -- Default: routine task, no gate
    return GateDecision(
        disposition=GateDisposition.AUTONOMOUS,
        reason="no gate criteria matched -- routine task",
        rules=(),
    )


__all__ = [
    "GateDecision",
    "GateDisposition",
    "GateLearningStore",
    "GateTask",
    "ObligationType",
    "evaluate_gate",
]
