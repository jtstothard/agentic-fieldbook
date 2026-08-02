"""Deployment-neutral, fail-closed light-gate adapter contract.

Light gates (G2-G5) need a recorded human decision but NOT the cryptographic
broker/lease/receipt machinery of the heavy gate (:class:`ApprovalGateAdapter`).
This contract preserves the safety properties that matter for light gates —
idempotency, expiry, revocation, and idempotency-conflict detection — while
deliberately omitting brokers, leases, receipts, and signatures.

The presentation channel is adapter-owned: the contract defines the data
shape, not transport.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

from .receipt import canonical_digest


class LightGateOutcome(str, Enum):
    """Outcome states for the light-gate lifecycle.

    APPROVED / REJECTED / EXPIRED / REVOKED are the terminal decision states
    listed in the spec.  PENDING is the initial state of a freshly created
    request.  PRESENTED signals a successful :meth:`present` call.  MALFORMED
    and IDEMPOTENCY_CONFLICT are fail-closed signals for bad inputs and fork
    mutation respectively.
    """
    PENDING = "pending"
    PRESENTED = "presented"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MALFORMED = "malformed"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


def parse_timestamp(value: str) -> datetime:
    """Parse a timezone-bearing ISO-8601 timestamp, or raise ``ValueError``.

    Mirrors the approval-gate timestamp parser so adapters share the same
    normalisation rules (trailing ``Z`` accepted, naive timestamps rejected).
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def now_utc_iso() -> str:
    """Current UTC time as an ISO-8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class LightGateRequest:
    """Recommendation-first dialogue gate request for G2-G5.

    Fields mirror a decision fork: the situation, the agent's recommendation,
    the alternatives, the key trade-off, how to undo, and when the gate
    lapses.  ``fork_signature`` is the idempotency-comparison digest; the
    adapter computes it via :func:`compute_fork_signature`.  ``outcome``
    tracks the request lifecycle (PENDING on success, IDEMPOTENCY_CONFLICT
    on fork mutation).
    """
    gate_id: str
    fork_description: str
    recommended_option: str
    options: tuple[str, ...]
    trade_off: str
    revert_path: str
    expires_at: str
    idempotency_key: str
    fork_signature: str
    outcome: LightGateOutcome = LightGateOutcome.PENDING


@dataclass(frozen=True)
class LightGatePresentation:
    """Immutable request data for rendering by an adapter-owned channel.

    Contains exactly the fields a presentation surface needs: fork, recommendation,
    trade-off, revert path, and the option list.  No transport or credential data.
    """
    outcome: LightGateOutcome
    gate_id: str
    fork_description: str
    recommended_option: str
    options: tuple[str, ...]
    trade_off: str
    revert_path: str
    reason: str = ""


@dataclass(frozen=True)
class LightGateDecision:
    """Recorded human decision for a light gate.

    Deliberately lighter than the heavy gate's ``DecisionResult``: no receipt,
    no lease, no signature.  ``outcome`` is APPROVED or REJECTED on a successful
    decision; EXPIRED or REVOKED if the gate was in a terminal state; MALFORMED
    for invalid inputs.  ``chosen_option`` is the option the human selected
    (empty string on rejection).
    """
    gate_id: str
    outcome: LightGateOutcome
    chosen_option: str
    subject_ref: str
    timestamp: str


@dataclass(frozen=True)
class LightGateRevocation:
    """Result of revoking a light gate."""
    gate_id: str
    outcome: LightGateOutcome
    reason: str


def compute_fork_signature(
    fork_description: str,
    recommended_option: str,
    options: Sequence[str],
    trade_off: str,
    revert_path: str,
    expires_at: str,
) -> str:
    """Canonical digest of the fork-relevant fields for idempotency.

    Two requests with the same idempotency key must produce the same fork
    signature.  A different signature means the fork was mutated and the old
    approval cannot be reused.  The signature domain excludes ``gate_id`` and
    ``idempotency_key`` (request metadata, not fork content).
    """
    return canonical_digest({
        "fork_description": fork_description,
        "recommended_option": recommended_option,
        "options": list(options),
        "trade_off": trade_off,
        "revert_path": revert_path,
        "expires_at": expires_at,
    })


def validate_light_gate_fields(
    fork_description: str,
    recommended_option: str,
    options: Sequence[str],
    trade_off: str,
    revert_path: str,
    expires_at: str,
    idempotency_key: str,
) -> list[str]:
    """Return validation errors for gate fields; empty list means valid.

    Fails closed: every field is type-checked before the gate is created.
    ``recommended_option`` must appear in ``options`` so the human always sees
    the recommendation as a selectable choice.
    """
    errors: list[str] = []
    if not isinstance(fork_description, str) or not fork_description.strip():
        errors.append("fork_description must be a non-empty string")
    if not isinstance(recommended_option, str) or not recommended_option.strip():
        errors.append("recommended_option must be a non-empty string")
    if not isinstance(options, (list, tuple)) or len(options) < 1:
        errors.append("options must be a non-empty sequence")
    elif not all(isinstance(o, str) and o.strip() for o in options):
        errors.append("all options must be non-empty strings")
    if (
        isinstance(recommended_option, str) and recommended_option.strip()
        and isinstance(options, (list, tuple))
        and recommended_option not in options
    ):
        errors.append("recommended_option must appear in options")
    if not isinstance(trade_off, str) or not trade_off.strip():
        errors.append("trade_off must be a non-empty string")
    if not isinstance(revert_path, str) or not revert_path.strip():
        errors.append("revert_path must be a non-empty string")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        errors.append("idempotency_key must be a non-empty string")
    try:
        parse_timestamp(expires_at)
    except (TypeError, ValueError):
        errors.append("expires_at must be a timezone-aware ISO-8601 timestamp")
    return errors


def render_gate_message(request: LightGateRequest) -> str:
    """Render a ``LightGateRequest`` into a recommendation-first message string.

    Canonical format (one line per field, recommendation leads, context second)::

        Recommendation: <recommended_option>
        Fork: <fork_description>
        Trade-off: <trade_off>
        Revert: <revert_path>

    The recommendation always appears first so Jay can decide quickly without
    reading context.  The fork (the situation) is second — the context that
    the recommendation resolves.  The one material trade-off and the
    revert/abort path follow.  Adapters render this string verbatim; the
    renderer defines the shape, the adapter owns transport.

    The request must be valid: ``recommended_option`` is enforced non-empty at
    request creation by :func:`validate_light_gate_fields`, so this function
    never receives a request without a recommendation.  An empty
    ``recommended_option`` or any empty required field raises ``ValueError``
    defensively.
    """
    required = {
        "recommended_option": request.recommended_option,
        "fork_description": request.fork_description,
        "trade_off": request.trade_off,
        "revert_path": request.revert_path,
    }
    # Validate types first (defends against None or non-str adapter bugs).
    for name, value in required.items():
        if not isinstance(value, str):
            raise ValueError(
                f"cannot render gate message: field {name!r} must be str, "
                f"got {type(value).__name__}"
            )
    # Empty fields are rejected (request creation should prevent this, but
    # defend in depth).
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise ValueError(
            "cannot render gate message with empty field(s): "
            + ", ".join(missing)
        )
    # Reject embedded newlines/carriage returns: a gate message is strictly
    # one line per field.  Allowing embedded newlines would let a malicious or
    # buggy caller inject fake labels (e.g. "\n[Recommendation] ...") and break
    # the canonical one-line-per-field contract.  Reject is safer than sanitize
    # for a gate message.
    multiline = [name for name, value in required.items()
                 if "\n" in value or "\r" in value]
    if multiline:
        raise ValueError(
            "cannot render gate message: field(s) contain embedded newlines "
            "(gate messages must be one line per field): " + ", ".join(multiline)
        )
    lines = [
        f"Recommendation: {request.recommended_option}",
        f"Fork: {request.fork_description}",
        f"Trade-off: {request.trade_off}",
        f"Revert: {request.revert_path}",
    ]
    return "\n".join(lines)


class LightGateAdapter(ABC):
    """Deployment-neutral light-gate seam.

    Implementations MUST use an atomic store transaction.  The idempotency
    key is scoped per adapter instance.  Existing key + same fork signature
    returns the original request; existing key + different fork signature
    returns ``IDEMPOTENCY_CONFLICT``.  An expired or revoked gate cannot be
    decided.

    ``record_decision`` accepts a ``subject_ref`` string identifying the
    authenticated human; authentication itself is the adapter's responsibility
    (presentation-channel-specific), not this contract's.  The contract
    defines data shape, not transport.
    """
    @abstractmethod
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
        """Create or replay a gate request. Same key + same fork = replay;
        same key + mutated fork = ``IDEMPOTENCY_CONFLICT``."""
        ...

    @abstractmethod
    def present(self, gate_id: str) -> LightGatePresentation:
        """Return immutable request data for rendering."""
        ...

    @abstractmethod
    def record_decision(
        self, gate_id: str, chosen_option: str, subject_ref: str,
    ) -> LightGateDecision:
        """Record a human decision. Non-empty ``chosen_option`` in the option
        list → APPROVED; empty → REJECTED; invalid → MALFORMED. Expired or
        revoked gates return their terminal outcome and cannot be decided."""
        ...

    @abstractmethod
    def revoke(self, gate_id: str, reason: str) -> LightGateRevocation:
        """Revoke a gate so it can no longer be decided."""
        ...
