"""Gate evaluator: classifies a planned task into a gate disposition.

Implements the genuine-decision test (G1-G5) and bureaucracy test (B1-B4)
from the HITL gate taxonomy v0.1.

The evaluator is pure: no side effects, no I/O. Classification only.
The caller supplies reversibility (the evaluator never infers it).
Side effects (recording decisions, pattern tracking) live in the learning model.

Design rules
------------
- G1 (always-ask capabilities) is ABSOLUTE: it routes to GATE_HEAVY regardless
  of reversibility, standing approval, or known preference.
- G2-G5 are suppressible: B4 (trivially reversible) suppresses them because
  reversibility is the master variable for the genuine-decision test.
- B1 (standing approval) and B2 (known preference) are checked before the
  genuine-decision test fires, via the caller-supplied learning-store booleans.
- G4 is LOCKED to third-party obligations only (new paid SaaS, vendor
  relationship, credential with external liability). Internal factory plumbing
  (cron, monitoring, internal integration, self-hosted service) is NOT G4.
- The evaluator fails closed: when it cannot classify a task, it returns
  GATE_LIGHT, never AUTONOMOUS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .governance import detect_always_ask_capabilities


class GateDisposition(str, Enum):
    """Classification of a planned task into a gate weight.

    - ``AUTONOMOUS``   — no gate; proceeds straight to execution.
    - ``REPORT_ONLY``  — no gate; notify per cadence.
    - ``GATE_LIGHT``   — recommendation-first dialogue gate (Matrix, HA, …).
    - ``GATE_HEAVY``   — existing cryptographic approval-gate path (G1).
    """

    AUTONOMOUS = "autonomous"
    REPORT_ONLY = "report_only"
    GATE_LIGHT = "gate_light"
    GATE_HEAVY = "gate_heavy"


class Reversibility(str, Enum):
    """Caller-supplied reversibility assessment.

    The evaluator does NOT infer reversibility; the caller supplies it.
    Reversibility is the master variable for G2-G5.
    """

    TRIVIAL = "trivial"          # B4: undo within the session, no external side effect
    REVERSIBLE = "reversible"    # can be undone, but with cost / external coordination
    IRREVERSIBLE = "irreversible"  # cannot be undone, or asymmetry is permanent


class ObligationScope(str, Enum):
    """Classification of an obligation boundary for G4.

    G4 is LOCKED to third-party obligations only. Internal factory plumbing is
    explicitly NOT G4.
    """

    INTERNAL = "internal"        # cron, monitoring, internal integration, self-hosted
    THIRD_PARTY = "third_party"  # new paid SaaS, vendor relationship, external liability
    UNKNOWN = "unknown"          # cannot tell — fail closed


@dataclass(frozen=True)
class GateTask:
    """Caller-built description of the task being classified.

    All fields are inputs the caller supplies. The evaluator never infers
    risk, reversibility, obligation scope, or approval status.
    """

    risk_class: str                                  # "low", "medium", "high"
    capabilities: tuple[str, ...] = ()               # e.g. ("delete", "secret-read")
    reversibility: Reversibility = Reversibility.IRREVERSIBLE
    # G2 — spec-fork: a decision between materially different futures
    is_spec_fork: bool = False
    # G3 — reversal-asymmetry: undo is materially costlier than doing
    has_reversal_asymmetry: bool = False
    # G4 — obligation boundary (INTERNAL plumbing vs THIRD_PARTY commitment)
    obligation_scope: ObligationScope = ObligationScope.UNKNOWN
    # G5 — ambiguous-intent with high blast radius
    has_ambiguous_intent: bool = False
    blast_radius: str = "low"                        # "low", "medium", "high"
    scope: str = "single"                            # "single", "multi", "global"

    # Bureaucracy-test inputs — caller answers these from its learning store
    standing_approval: bool = False                  # B1: an action class is pre-approved
    known_preference: bool = False                   # B2: ≥3 consistent prior choices


@dataclass(frozen=True)
class GateDecision:
    """Result of evaluating a task.

    The ``reason`` records which rule fired so callers and tests can audit
    WHY a disposition was chosen, not just what.
    """

    disposition: GateDisposition
    reason: str
    rule: str                                        # e.g. "G1", "B1", "G4-internal", "fail-closed"


# --- Internal predicates ---------------------------------------------------

def _is_trivially_reversible(task: GateTask) -> bool:
    """B4: trivially reversible within the session, no external side effect."""
    return task.reversibility is Reversibility.TRIVIAL


def _matches_genuine_decision(task: GateTask) -> Optional[str]:
    """Return the label of the first G2-G5 rule that fires, or None.

    G1 is handled separately (it is absolute). Reversibility gates these:
    a trivially reversible task never matches even if it has a fork/asymmetry,
    because the master variable suppresses the genuine-decision test.
    """
    if _is_trivially_reversible(task):
        return None

    if task.is_spec_fork:
        return "G2"
    if task.has_reversal_asymmetry:
        return "G3"
    # G4 is LOCKED to third-party obligations only
    if task.obligation_scope is ObligationScope.THIRD_PARTY:
        return "G4-third_party"
    if task.has_ambiguous_intent and task.blast_radius in ("medium", "high"):
        return "G5"
    return None


# --- Public entry point ----------------------------------------------------

def evaluate_gate(task: GateTask) -> GateDecision:
    """Classify a planned task into a gate disposition.

    Evaluation order (the bureaucracy test runs first; G1 is absolute and last):

    1. G1 (always-ask capabilities) → GATE_HEAVY. Absolute — nothing suppresses it.
    2. B1 (standing approval covers the action class) → AUTONOMOUS.
    3. B2 (known preference, ≥3 consistent prior choices) → AUTONOMOUS if the
       task is trivially reversible, else REPORT_ONLY.
    4. B4 (trivially reversible, no external side effect) → AUTONOMOUS, even
       if the task matches a G2-G5 category.
    5. G2-G5 genuine-decision test → GATE_LIGHT.
    6. Fail closed → GATE_LIGHT.

    Returns a :class:`GateDecision` naming the disposition, the rule that
    fired, and a human-readable reason.
    """
    # --- G1: always-ask capabilities are ABSOLUTE ---------------------------
    # Reuses detect_always_ask_capabilities() from governance.py — no duplication.
    # G1 cannot be suppressed by reversibility, standing approval, or known
    # preference: destructive/secret/billing/access/downtime always route heavy.
    always_ask = detect_always_ask_capabilities(task.capabilities)
    if always_ask:
        categories = ", ".join(sorted(c.value for c in always_ask))
        return GateDecision(
            disposition=GateDisposition.GATE_HEAVY,
            rule="G1",
            reason=f"Always-ask capabilities trigger heavy gate: {categories}",
        )

    # --- B1: standing approval covers the action class ----------------------
    if task.standing_approval:
        return GateDecision(
            disposition=GateDisposition.AUTONOMOUS,
            rule="B1",
            reason="Standing approval covers this action class",
        )

    # --- B2: known preference (≥3 consistent prior choices) -----------------
    if task.known_preference:
        if _is_trivially_reversible(task):
            return GateDecision(
                disposition=GateDisposition.AUTONOMOUS,
                rule="B2",
                reason="Known preference and trivially reversible",
            )
        return GateDecision(
            disposition=GateDisposition.REPORT_ONLY,
            rule="B2",
            reason="Known preference — report only, no gate",
        )

    # --- B4: trivially reversible suppresses the genuine-decision test -----
    # Reversibility is the master variable for G2-G5.
    if _is_trivially_reversible(task):
        return GateDecision(
            disposition=GateDisposition.AUTONOMOUS,
            rule="B4",
            reason="Trivially reversible within the session, no external side effect",
        )

    # --- G2-G5: genuine-decision test ---------------------------------------
    g_rule = _matches_genuine_decision(task)
    if g_rule is not None:
        return GateDecision(
            disposition=GateDisposition.GATE_LIGHT,
            rule=g_rule,
            reason=f"Genuine-decision category matched: {g_rule}",
        )

    # --- G4-internal: internal factory plumbing is NOT G4 -------------------
    # Internal plumbing (cron, monitoring, self-hosted) runs autonomous when it
    # has no other genuine-decision signal and is reversible, or report-only
    # if it touches a higher blast radius but is still reversible.
    if task.obligation_scope is ObligationScope.INTERNAL:
        if task.reversibility is Reversibility.REVERSIBLE:
            return GateDecision(
                disposition=GateDisposition.AUTONOMOUS,
                rule="G4-internal",
                reason="Internal factory plumbing is not a third-party obligation",
            )
        return GateDecision(
            disposition=GateDisposition.REPORT_ONLY,
            rule="G4-internal",
            reason="Internal factory plumbing — report only",
        )

    # --- Fail closed ---------------------------------------------------------
    # The evaluator could not classify the task. Never default to autonomous.
    return GateDecision(
        disposition=GateDisposition.GATE_LIGHT,
        rule="fail-closed",
        reason="Unable to classify — gating for human review",
    )


__all__ = [
    "GateDisposition",
    "Reversibility",
    "ObligationScope",
    "GateTask",
    "GateDecision",
    "evaluate_gate",
]
