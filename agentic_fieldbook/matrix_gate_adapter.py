"""Matrix transport adapter for the light-gate dialogue (#78).

Concrete :class:`LightGateAdapter` implementation for the Matrix transport.
The adapter owns the gate-request store and the Matrix-specific presentation
formatting; the *content* always comes from :func:`render_gate_message` (#64)
so the renderer remains the single source of truth.

The adapter is deployment-neutral: it takes a :class:`MatrixTransport`
protocol (send/receive) rather than importing the Hermes gateway directly.
Any object with compatible ``send``/``receive`` methods satisfies the
protocol, which keeps the Fieldbook testable without a live Matrix server.

Command parsing
---------------
Jay resolves gates via structured commands in the control room:

    /gate approve <id>                → approved (recommended option chosen)
    /gate reject  <id>                → rejected
    /gate pick <option> <id>          → approved with a specific option

Free-text replies are ignored for decision purposes (``process_reply``
returns ``None``).  Only messages that start with ``/gate`` are parsed.
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .light_gate import (
    LightGateAdapter,
    LightGateDecision,
    LightGateOutcome,
    LightGatePresentation,
    LightGateRequest,
    LightGateRevocation,
    compute_fork_signature,
    parse_timestamp,
    render_gate_message,
    validate_light_gate_fields,
    validate_gate_id,
)


def render_gate_control_message(request: LightGateRequest) -> str:
    """Render the control-room body with an addressable gate identity."""
    if not validate_gate_id(request.gate_id):
        raise ValueError("cannot render gate control message without gate_id")
    body = render_gate_message(request)
    gate_id = request.gate_id
    option_lines = "\n".join(
        f"{index}: {option}" for index, option in enumerate(request.options, 1)
    )
    return (
        f"{body}\n"
        f"Gate ID: {gate_id}\n"
        "Commands:\n"
        f"/gate approve {gate_id}\n"
        f"/gate reject {gate_id}\n"
        f"/gate pick <index> {gate_id}\n"
        "Options:\n"
        f"{option_lines}"
    )

# --------------------------------------------------------------------------- #
# Transport protocol (deployment-neutral)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MatrixMessage:
    """A single incoming Matrix message relevant to gate decisions."""

    event_id: str
    sender: str
    text: str
    room_id: str = ""
    event_type: str = "m.room.message"
    relates_to: dict[str, str] | None = None
    context_namespace: str = ""


@runtime_checkable
class MatrixTransport(Protocol):
    """Minimal send/receive protocol that the Hermes Matrix gateway satisfies.

    Keeping the Fieldbook free of a direct gateway import means the adapter
    can be tested with a trivial in-memory transport and deployed against
    any Matrix client library without code changes.
    """

    def send(self, room_id: str, message: str) -> str:
        """Send *message* to *room_id*; return the Matrix event ID."""
        ...

    def receive(self) -> tuple[MatrixMessage, ...]:
        """Return pending incoming messages (polled by the adapter)."""
        ...


# --------------------------------------------------------------------------- #
# Command parsing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ParsedGateCommand:
    """Result of parsing a ``/gate`` command from a Matrix message.

    ``verb`` is ``"approve"``, ``"reject"``, or ``"pick"``.
    ``picked_option`` is only meaningful for ``"pick"``; empty otherwise.
    """

    verb: str
    gate_id: str
    picked_option: str


# Match the leading ``/gate <verb>`` prefix (case-sensitive on the slash
# command, matching the issue spec exactly).
_GATE_PREFIX_RE = re.compile(r"^/gate\s+(approve|reject|pick)\s+(.+)$")


def parse_gate_command(text: str) -> ParsedGateCommand | None:
    """Parse a Matrix message into a structured gate command.

    Returns ``None`` for free text, non-string input, or a malformed
    command.  This is a pure function — no adapter state required.
    """
    if not isinstance(text, str):
        return None
    match = _GATE_PREFIX_RE.match(text.strip())
    if match is None:
        return None
    verb = match.group(1)
    remainder = match.group(2).strip()
    tokens = remainder.split()

    if verb in ("approve", "reject"):
        # /gate approve <id>   or   /gate reject <id>
        if len(tokens) != 1 or not validate_gate_id(tokens[0]):
            return None
        return ParsedGateCommand(
            verb=verb, gate_id=tokens[0], picked_option="",
        )

    # verb == "pick":  /gate pick <option> <id>
    if (
        len(tokens) != 2
        or not validate_gate_id(tokens[0])
        or not validate_gate_id(tokens[1])
    ):
        return None
    return ParsedGateCommand(
        verb="pick", gate_id=tokens[1], picked_option=tokens[0],
    )


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #

class MatrixGateAdapter(LightGateAdapter):
    """Light-gate adapter that presents gates in a Matrix control room.

    Lifecycle::

        create_request(...)  → LightGateRequest   (idempotent store)
        present(gate_id)     → LightGatePresentation  (renders + sends)
        record_decision(...) → LightGateDecision       (stores decision)
        revoke(gate_id, ...) → LightGateRevocation     (sends follow-up)

    Matrix-specific extras::

        parse_gate_command(text)    → ParsedGateCommand | None  (pure)
        process_reply(text, sender) → LightGateDecision | None  (parse + record)
        get_matrix_event_id(gate_id) → str   (event ID from present)

    The adapter is thread-safe (internal lock on create/record/revoke).
    """

    def __init__(
        self,
        transport: MatrixTransport,
        control_room: str,
        *,
        validity_window: timedelta = timedelta(minutes=5),
    ) -> None:
        self._transport = transport
        self._room = control_room
        self._validity_window = validity_window

        self._requests: dict[str, LightGateRequest] = {}
        self._by_key: dict[str, str] = {}              # idempotency_key → gate_id
        self._event_ids: dict[str, str] = {}           # gate_id → matrix event_id
        self._revoked: set[str] = set()
        self._reaction_events: set[str] = set()
        self._namespace = uuid.uuid4().hex[:12]
        self._counter = 0
        self._lock = threading.Lock()

    # -- LightGateAdapter ABC --------------------------------------------- #

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
        """Create or replay a gate request (idempotent on key + fork)."""
        errors = validate_light_gate_fields(
            fork_description, recommended_option, options,
            trade_off, revert_path, expires_at, idempotency_key,
        )
        if errors:
            return _malformed_request()

        sig = compute_fork_signature(
            fork_description, recommended_option, options,
            trade_off, revert_path, expires_at,
        )

        with self._lock:
            if idempotency_key in self._by_key:
                old = self._requests[self._by_key[idempotency_key]]
                if old.fork_signature != sig:
                    return _with_outcome(old, LightGateOutcome.IDEMPOTENCY_CONFLICT)
                return old

            self._counter += 1
            gate_id = f"matrix-gate-{self._namespace}-{self._counter}"
            request = LightGateRequest(
                gate_id=gate_id,
                fork_description=fork_description,
                recommended_option=recommended_option,
                options=tuple(options),
                trade_off=trade_off,
                revert_path=revert_path,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                fork_signature=sig,
            )
            self._requests[gate_id] = request
            self._by_key[idempotency_key] = gate_id
            return request

    def present(self, gate_id: str) -> LightGatePresentation:
        """Render the gate message and send it to the control room."""
        request = self._requests.get(gate_id)
        if request is None:
            return LightGatePresentation(
                LightGateOutcome.MALFORMED, gate_id, "", "", (), "", "",
                reason="unknown gate",
            )
        if gate_id in self._revoked:
            return LightGatePresentation(
                LightGateOutcome.REVOKED, gate_id, "", "", (), "", "",
                reason="revoked",
            )
        try:
            if parse_timestamp(request.expires_at) <= datetime.now(timezone.utc):
                return LightGatePresentation(
                    LightGateOutcome.EXPIRED, gate_id, "", "", (), "", "",
                    reason="expired",
                )
        except ValueError:
            return LightGatePresentation(
                LightGateOutcome.MALFORMED, gate_id, "", "", (), "", "",
                reason="bad timestamp",
            )

        # Matrix control rooms need an addressable gate identity and commands.
        body = render_gate_control_message(request)
        event_id = self._transport.send(self._room, body)
        self._event_ids[gate_id] = event_id

        return LightGatePresentation(
            LightGateOutcome.PRESENTED,
            gate_id,
            request.fork_description,
            request.recommended_option,
            request.options,
            request.trade_off,
            request.revert_path,
        )

    def record_decision(
        self, gate_id: str, chosen_option: str, subject_ref: str,
    ) -> LightGateDecision:
        """Record a human decision (ABC method — direct recording)."""
        request = self._requests.get(gate_id)
        now_iso = _now_utc_iso()
        if request is None:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", "", now_iso,
            )
        if gate_id in self._revoked:
            return LightGateDecision(
                gate_id, LightGateOutcome.REVOKED, "", subject_ref, now_iso,
            )
        try:
            if parse_timestamp(request.expires_at) <= datetime.now(timezone.utc):
                return LightGateDecision(
                    gate_id, LightGateOutcome.EXPIRED, "", subject_ref, now_iso,
                )
        except ValueError:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", subject_ref, now_iso,
            )
        if not isinstance(chosen_option, str):
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", subject_ref, now_iso,
            )
        if chosen_option == "":
            return LightGateDecision(
                gate_id, LightGateOutcome.REJECTED, "", subject_ref, now_iso,
            )
        if chosen_option not in request.options:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, chosen_option, subject_ref, now_iso,
            )
        return LightGateDecision(
            gate_id, LightGateOutcome.APPROVED, chosen_option, subject_ref, now_iso,
        )

    def revoke(self, gate_id: str, reason: str) -> LightGateRevocation:
        """Revoke a gate and send a follow-up Matrix message."""
        if gate_id not in self._requests:
            return LightGateRevocation(
                gate_id, LightGateOutcome.MALFORMED, "unknown gate",
            )
        if not isinstance(reason, str) or not reason.strip():
            return LightGateRevocation(
                gate_id, LightGateOutcome.MALFORMED, "reason required",
            )
        self._revoked.add(gate_id)

        # Send a follow-up message marking the gate expired/superseded.
        follow_up = f"⚠️ Gate {gate_id} revoked: {reason}"
        self._transport.send(self._room, follow_up)

        return LightGateRevocation(gate_id, LightGateOutcome.REVOKED, reason)

    # -- Matrix-specific extras ------------------------------------------- #

    @staticmethod
    def parse_gate_command(text: str) -> ParsedGateCommand | None:
        """Parse a ``/gate`` command from raw text (pure, no state)."""
        return parse_gate_command(text)

    def process_reply(
        self, raw_text: str, subject_ref: str,
    ) -> LightGateDecision | None:
        """Parse a Matrix reply and record the decision if it's a command.

        Returns ``None`` for free text (no decision recorded).
        Returns a :class:`LightGateDecision` for valid commands (including
        MALFORMED outcomes for bad option/gate references).
        """
        parsed = parse_gate_command(raw_text)
        if parsed is None:
            return None  # free text — ignored

        request = self._requests.get(parsed.gate_id)
        if request is None:
            return LightGateDecision(
                parsed.gate_id, LightGateOutcome.MALFORMED, "", subject_ref,
                _now_utc_iso(),
            )

        if parsed.verb == "approve":
            chosen = request.recommended_option
        elif parsed.verb == "reject":
            chosen = ""
        else:  # pick; numeric indexes make multi-word options unambiguous.
            chosen = parsed.picked_option
            if chosen.isdigit():
                index = int(chosen) - 1
                chosen = request.options[index] if 0 <= index < len(request.options) else ""

        return self.record_decision(parsed.gate_id, chosen, subject_ref)

    def process_reaction(
        self, message: object, subject_ref: str = "",
    ) -> LightGateDecision | None:
        """Resolve only an exact reaction annotation on the pending prompt.

        Matrix reaction events are deliberately separate from text commands:
        the key must be exactly ``✅`` or ``❌`` and ``m.relates_to.event_id``
        must be the event ID returned by :meth:`present` for a still-pending
        gate.  Arbitrary emoji text and annotations on other messages are not
        approval signals.
        """
        event_id = _event_value(message, "event_id", "message_id")
        sender = _event_value(message, "sender", "user_id") or subject_ref
        room_id = _event_value(message, "room_id", "chat_id")
        event_type = _event_value(message, "event_type", "type")
        relation = _reaction_relation(message)
        if event_type not in {"m.reaction", "reaction"} or not relation:
            return None
        if relation.get("rel_type") not in {"m.annotation", "annotation"}:
            return None
        prompt_event_id = relation.get("event_id", "")
        key = relation.get("key", "")
        if key not in {"✅", "❌"} or not prompt_event_id:
            return None
        if room_id and room_id != self._room:
            return None
        with self._lock:
            if event_id and event_id in self._reaction_events:
                return None
            gate_id = next((gate for gate, event in self._event_ids.items()
                            if event == prompt_event_id), None)
            if gate_id is None or gate_id in self._revoked:
                return None
            request = self._requests.get(gate_id)
            if request is None:
                return None
            chosen = request.recommended_option if key == "✅" else ""
            decision = self.record_decision(gate_id, chosen, str(sender or ""))
            value = getattr(getattr(decision, "outcome", None), "value", None)
            if event_id and value in {"approved", "rejected", "expired", "revoked"}:
                self._reaction_events.add(event_id)
            return decision

    def get_matrix_event_id(self, gate_id: str) -> str:
        """Return the Matrix event ID for a presented gate (empty if unknown)."""
        return self._event_ids.get(gate_id, "")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_value(event: object, *names: str) -> str:
    for name in names:
        value = getattr(event, name, None)
        if value is None and isinstance(event, dict):
            value = event.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def _reaction_relation(event: object) -> dict[str, str]:
    """Normalize mautrix, gateway, and test event relation shapes."""
    relation = getattr(event, "relates_to", None)
    if relation is None and isinstance(event, dict):
        relation = event.get("relates_to")
        content = event.get("content")
        if relation is None and isinstance(content, dict):
            relation = content.get("m.relates_to") or content.get("relates_to")
    if relation is None:
        content = getattr(event, "content", None)
        if isinstance(content, dict):
            relation = content.get("m.relates_to") or content.get("relates_to")
    if not isinstance(relation, dict):
        return {}
    normalized = {
        "rel_type": str(relation.get("rel_type") or relation.get("relType") or ""),
        "event_id": str(relation.get("event_id") or relation.get("eventId") or ""),
        "key": str(relation.get("key") or ""),
    }
    return normalized


def _malformed_request() -> LightGateRequest:
    return LightGateRequest(
        "", "", "", (), "", "", "", "", "",
        outcome=LightGateOutcome.MALFORMED,
    )


def _with_outcome(request: LightGateRequest, outcome: LightGateOutcome) -> LightGateRequest:
    from dataclasses import replace
    return replace(request, outcome=outcome)


__all__ = [
    "MatrixGateAdapter",
    "MatrixMessage",
    "MatrixTransport",
    "ParsedGateCommand",
    "parse_gate_command",
]
