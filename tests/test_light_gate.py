"""Contract tests for the deployment-neutral light-gate seam.

Mirrors the shape of tests/test_approval_gate.py: create, present, decide,
revoke, expiry, idempotency conflict.  Uses a deliberately small observable
adapter that obeys the public contract.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from agentic_fieldbook.light_gate import (
    LightGateAdapter,
    LightGateDecision,
    LightGateOutcome,
    LightGatePresentation,
    LightGateRequest,
    LightGateRevocation,
    compute_fork_signature,
    parse_timestamp,
    validate_light_gate_fields,
)


# Minimal valid inputs ------------------------------------------------------

EXPIRES_FUTURE = "2099-01-01T00:00:00Z"
EXPIRES_PAST = "2000-01-01T00:00:00Z"


def make_inputs(**changes: str) -> dict:
    base = dict(
        fork_description="deploy v2 to prod",
        recommended_option="blue-green",
        options=["blue-green", "rolling", "halt"],
        trade_off="blue-green needs capacity headroom",
        revert_path="rollback to v1 via deploy button",
        expires_at=EXPIRES_FUTURE,
        idempotency_key="gate-1",
    )
    base.update(changes)
    return base


def signature_for(inputs: dict) -> str:
    return compute_fork_signature(
        inputs["fork_description"],
        inputs["recommended_option"],
        inputs["options"],
        inputs["trade_off"],
        inputs["revert_path"],
        inputs["expires_at"],
    )


class ObservableAdapter(LightGateAdapter):
    """A deliberately small implementation which obeys the public contract."""
    def __init__(self):
        self.requests: dict[str, LightGateRequest] = {}
        self.by_key: dict[str, str] = {}  # idempotency_key -> gate_id
        self.revoked: set[str] = set()
        self.counter = 0
        self._lock = __import__("threading").Lock()

    def create_request(self, fork_description, recommended_option, options,
                       trade_off, revert_path, expires_at, idempotency_key):
        errors = validate_light_gate_fields(
            fork_description, recommended_option, options,
            trade_off, revert_path, expires_at, idempotency_key,
        )
        if errors:
            return LightGateRequest(
                "", "", "", (), "", "", "", "", "",
                outcome=LightGateOutcome.MALFORMED,
            )
        sig = compute_fork_signature(
            fork_description, recommended_option, options,
            trade_off, revert_path, expires_at,
        )
        with self._lock:
            if idempotency_key in self.by_key:
                old = self.requests[self.by_key[idempotency_key]]
                if old.fork_signature != sig:
                    return replace_outcome(old, LightGateOutcome.IDEMPOTENCY_CONFLICT)
                return old
            self.counter += 1
            gate_id = f"gate-{self.counter}"
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
            self.requests[gate_id] = request
            self.by_key[idempotency_key] = gate_id
            return request

    def present(self, gate_id):
        request = self.requests.get(gate_id)
        if request is None:
            return LightGatePresentation(
                LightGateOutcome.MALFORMED, gate_id, "", "", (), "", "",
                reason="unknown gate",
            )
        if gate_id in self.revoked:
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
        return LightGatePresentation(
            LightGateOutcome.PRESENTED,
            gate_id,
            request.fork_description,
            request.recommended_option,
            request.options,
            request.trade_off,
            request.revert_path,
        )

    def record_decision(self, gate_id, chosen_option, subject_ref):
        request = self.requests.get(gate_id)
        if request is None:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", "", now_iso(),
            )
        if gate_id in self.revoked:
            return LightGateDecision(
                gate_id, LightGateOutcome.REVOKED, "", subject_ref, now_iso(),
            )
        try:
            if parse_timestamp(request.expires_at) <= datetime.now(timezone.utc):
                return LightGateDecision(
                    gate_id, LightGateOutcome.EXPIRED, "", subject_ref, now_iso(),
                )
        except ValueError:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", subject_ref, now_iso(),
            )
        if not isinstance(chosen_option, str):
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, "", subject_ref, now_iso(),
            )
        if chosen_option == "":
            return LightGateDecision(
                gate_id, LightGateOutcome.REJECTED, "", subject_ref, now_iso(),
            )
        if chosen_option not in request.options:
            return LightGateDecision(
                gate_id, LightGateOutcome.MALFORMED, chosen_option, subject_ref, now_iso(),
            )
        return LightGateDecision(
            gate_id, LightGateOutcome.APPROVED, chosen_option, subject_ref, now_iso(),
        )

    def revoke(self, gate_id, reason):
        if gate_id not in self.requests:
            return LightGateRevocation(
                gate_id, LightGateOutcome.MALFORMED, "unknown gate",
            )
        if not isinstance(reason, str) or not reason.strip():
            return LightGateRevocation(
                gate_id, LightGateOutcome.MALFORMED, "reason required",
            )
        self.revoked.add(gate_id)
        return LightGateRevocation(gate_id, LightGateOutcome.REVOKED, reason)


def replace_outcome(request, outcome):
    """Return a copy of *request* with the outcome replaced (frozen dataclass)."""
    from dataclasses import replace
    return replace(request, outcome=outcome)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------

def test_request_created_with_all_fields():
    adapter = ObservableAdapter()
    inputs = make_inputs()
    request = adapter.create_request(**inputs)
    assert request.gate_id == "gate-1"
    assert request.outcome is LightGateOutcome.PENDING
    assert request.fork_description == inputs["fork_description"]
    assert request.recommended_option == inputs["recommended_option"]
    assert request.options == tuple(inputs["options"])
    assert request.trade_off == inputs["trade_off"]
    assert request.revert_path == inputs["revert_path"]
    assert request.expires_at == inputs["expires_at"]
    assert request.idempotency_key == inputs["idempotency_key"]
    assert request.fork_signature


def test_present_returns_renderable_data():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    presentation = adapter.present(request.gate_id)
    assert presentation.outcome is LightGateOutcome.PRESENTED
    assert presentation.gate_id == request.gate_id
    assert presentation.fork_description == request.fork_description
    assert presentation.recommended_option == request.recommended_option
    assert presentation.options == request.options
    assert presentation.trade_off == request.trade_off
    assert presentation.revert_path == request.revert_path


def test_record_decision_approved():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    decision = adapter.record_decision(request.gate_id, "blue-green", "human-1")
    assert decision.outcome is LightGateOutcome.APPROVED
    assert decision.chosen_option == "blue-green"
    assert decision.subject_ref == "human-1"
    assert decision.gate_id == request.gate_id
    assert decision.timestamp


def test_record_decision_rejected():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    decision = adapter.record_decision(request.gate_id, "", "human-1")
    assert decision.outcome is LightGateOutcome.REJECTED
    assert decision.chosen_option == ""


def test_expired_gate_cannot_be_decided():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs(expires_at=EXPIRES_PAST))
    assert request.outcome is LightGateOutcome.PENDING
    decision = adapter.record_decision(request.gate_id, "blue-green", "human-1")
    assert decision.outcome is LightGateOutcome.EXPIRED


def test_revoked_gate_cannot_be_decided():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    revocation = adapter.revoke(request.gate_id, "wrong fork")
    assert revocation.outcome is LightGateOutcome.REVOKED
    assert revocation.reason == "wrong fork"
    decision = adapter.record_decision(request.gate_id, "blue-green", "human-1")
    assert decision.outcome is LightGateOutcome.REVOKED


def test_idempotency_conflict_on_mutated_fork():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    assert request.outcome is LightGateOutcome.PENDING
    mutated = adapter.create_request(**make_inputs(fork_description="deploy v3 to prod"))
    assert mutated.outcome is LightGateOutcome.IDEMPOTENCY_CONFLICT
    assert adapter.counter == 1


def test_idempotent_replay_same_fork():
    adapter = ObservableAdapter()
    first = adapter.create_request(**make_inputs())
    second = adapter.create_request(**make_inputs())
    # Replay returns the original stored request (same identity, same gate_id)
    assert second.gate_id == first.gate_id
    assert second.fork_signature == first.fork_signature
    assert adapter.counter == 1


def test_stable_id_and_conflict_under_concurrency():
    adapter = ObservableAdapter()
    inputs = make_inputs()
    results = list(ThreadPoolExecutor(max_workers=8).map(
        lambda _: adapter.create_request(**inputs), range(8),
    ))
    assert {r.gate_id for r in results} == {"gate-1"}
    assert all(r.outcome is LightGateOutcome.PENDING for r in results)
    assert adapter.counter == 1


def test_malformed_inputs_fail_closed():
    adapter = ObservableAdapter()
    empty = adapter.create_request(**make_inputs(fork_description=""))
    assert empty.outcome is LightGateOutcome.MALFORMED
    assert empty.gate_id == ""
    no_options = adapter.create_request(**make_inputs(options=[]))
    assert no_options.outcome is LightGateOutcome.MALFORMED
    rec_not_in_options = adapter.create_request(**make_inputs(recommended_option="absent"))
    assert rec_not_in_options.outcome is LightGateOutcome.MALFORMED
    bad_expiry = adapter.create_request(**make_inputs(expires_at="not-a-time"))
    assert bad_expiry.outcome is LightGateOutcome.MALFORMED


def test_invalid_decision_inputs_fail_closed():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    bogus = adapter.record_decision(request.gate_id, 1, "human-1")
    assert bogus.outcome is LightGateOutcome.MALFORMED
    unknown = adapter.record_decision("nope", "blue-green", "human-1")
    assert unknown.outcome is LightGateOutcome.MALFORMED
    not_an_option = adapter.record_decision(request.gate_id, "absent", "human-1")
    assert not_an_option.outcome is LightGateOutcome.MALFORMED


def test_revoke_requires_reason():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    assert adapter.revoke(request.gate_id, "").outcome is LightGateOutcome.MALFORMED
    assert adapter.revoke("nope", "reason").outcome is LightGateOutcome.MALFORMED


def test_fork_signature_excludes_gate_metadata():
    inputs = make_inputs()
    sig1 = signature_for(inputs)
    # Same fork content, different idempotency key → same signature
    sig2 = signature_for(make_inputs(idempotency_key="other"))
    assert sig1 == sig2
    # Mutated fork content → different signature
    sig3 = signature_for(make_inputs(trade_off="changed trade-off"))
    assert sig1 != sig3


def test_contract_is_deployment_neutral():
    # No transport/channel/credential attributes on the contract surface
    for attr in ("channel", "private_key", "credential", "token", "secret"):
        assert not hasattr(LightGateAdapter, attr)
        assert not hasattr(LightGateRequest, attr)
        assert not hasattr(LightGateDecision, attr)
    # The module must not import transport-specific libraries
    import agentic_fieldbook.light_gate as lg
    import inspect
    source = inspect.getsource(lg)
    assert "matrix" not in source.lower()
    assert "homeassistant" not in source.lower()
    assert "home_assistant" not in source.lower()
    assert "mqtt" not in source.lower()


def test_request_and_presentation_are_immutable():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    try:
        request.gate_id = "tampered"  # type: ignore[misc]
        assert False
    except AttributeError:
        pass
    presentation = adapter.present(request.gate_id)
    try:
        presentation.options = ()  # type: ignore[misc]
        assert False
    except AttributeError:
        pass


def test_chosen_option_outside_options_rejected():
    adapter = ObservableAdapter()
    request = adapter.create_request(**make_inputs())
    decision = adapter.record_decision(request.gate_id, "not-listed", "human-1")
    assert decision.outcome is LightGateOutcome.MALFORMED


def test_no_heavy_gate_artifacts_in_contract():
    """No ApprovalReceipt, broker, lease, or cryptographic signature machinery.

    ``fork_signature`` / ``compute_fork_signature`` are digest-based fork
    identifiers for idempotency — not cryptographic signatures — so they are
    expected and allowed.  The heavy-gate-specific classes must be absent.
    """
    import agentic_fieldbook.light_gate as lg
    public = set(dir(lg))
    assert "ApprovalReceipt" not in public
    assert "ReceiptIssuer" not in public
    assert "HumanAuthenticationAssertion" not in public
    assert "provider_assertion" not in public
    for name in public:
        low = name.lower()
        assert "broker" not in low
        assert "lease" not in low
        assert "receipt" not in low
