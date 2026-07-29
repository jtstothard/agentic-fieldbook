"""Adversarial contract tests for the deployment-neutral approval seam."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from agentic_fieldbook.approval_gate import (
    ActionPackage, ApprovalGateAdapter, ApprovalOutcome, ApprovalReceipt,
    AuthenticatedHumanSubject, ApprovalRequest, DecisionResult,
    PresentationResult, RequesterContext, RevocationResult,
    HumanAuthenticationAssertion, provider_assertion, validate_action_package,
    validate_presentation,
)


def make_package(**changes: Any) -> ActionPackage:
    base = dict(target={"cluster": "example", "type": "guest", "id": "123"},
                capability="snapshot_guest", parameters={"snapshot": "approved", "nested": {"items": [1, 2]}},
                lease_ttl=300, operation_limit=1, verification_method="direct-query",
                rollback={"required": True}, abort_conditions=["verification-fails"],
                approval_expires_at="2099-01-01T00:10:00Z", contract_digest="")
    base.update(changes)
    unsigned = ActionPackage(**base)
    return replace(unsigned, contract_digest=unsigned.digest()) if "contract_digest" not in changes else unsigned


PACKAGE = make_package()
CONTEXT = RequesterContext("requester-ref", "broker-ref", "retry-key")


class ObservableAdapter(ApprovalGateAdapter):
    """A deliberately small implementation which obeys the public contract."""
    def __init__(self):
        self.requests: dict[str, ApprovalRequest] = {}
        self.retries: dict[tuple[str, str, str], str] = {}
        self.receipts: dict[str, ApprovalReceipt] = {}
        self.counter = 0
        self._lock = __import__("threading").Lock()

    def create_request(self, action_package, requester_context):
        errors = validate_action_package(action_package)
        if errors or not isinstance(requester_context, RequesterContext):
            return ApprovalRequest("", "", {}, "", "", "", ApprovalOutcome.MALFORMED)
        key = (requester_context.requester_ref, requester_context.audience, requester_context.idempotency_key)
        digest = action_package.digest()
        with self._lock:
            if key in self.retries:
                old = self.requests[self.retries[key]]
                if old.action_digest != digest:
                    return replace(old, outcome=ApprovalOutcome.IDEMPOTENCY_CONFLICT)
                return old
            self.counter += 1
            frozen = MappingProxyType({k: _freeze(v) for k, v in action_package.as_mapping().items()})
            request = ApprovalRequest(f"req-{self.counter}", digest, frozen,
                                      requester_context.requester_ref, requester_context.audience,
                                      action_package.approval_expires_at,
                                      idempotency_key=requester_context.idempotency_key)
            self.requests[request.approval_request_id] = request
            self.retries[key] = request.approval_request_id
            return request

    def present(self, request_id):
        request = self.requests.get(request_id)
        if request is None:
            return PresentationResult(ApprovalOutcome.MALFORMED, request_id, "", reason="unknown request")
        return PresentationResult(ApprovalOutcome.PRESENTED, request_id, request.action_digest, request.action_package)

    def record_decision(self, request_id, decision, authenticated_subject):
        request = self.requests.get(request_id)
        if request is None or not isinstance(decision, str) or decision not in {"approve", "reject"}:
            return DecisionResult(ApprovalOutcome.MALFORMED, request_id)
        if not isinstance(authenticated_subject, HumanAuthenticationAssertion):
            return DecisionResult(ApprovalOutcome.UNAUTHENTICATED, request_id)
        if not authenticated_subject.is_bound_to(request_id, request.audience):
            return DecisionResult(ApprovalOutcome.UNAUTHENTICATED, request_id)
        try:
            expired = datetime.fromisoformat(request.expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return DecisionResult(ApprovalOutcome.MALFORMED, request_id, request.action_digest)
        if expired:
            return DecisionResult(ApprovalOutcome.EXPIRED, request_id, request.action_digest)
        if not validate_presentation(request.action_package, request.action_digest):
            return DecisionResult(ApprovalOutcome.MALFORMED, request_id, request.action_digest)
        if decision == "reject":
            return DecisionResult(ApprovalOutcome.REJECTED, request_id, request.action_digest)
        with self._lock:
            if request_id in self.receipts:
                receipt = self.receipts[request_id]
                return DecisionResult(ApprovalOutcome.APPROVED, request_id, request.action_digest, receipt, authenticated_subject.subject_ref)
            receipt = ApprovalReceipt("1", f"receipt-{request_id}", request_id, request.action_digest,
                                      {"decision": "approved", "issuer": authenticated_subject.subject_ref})
            self.receipts[request_id] = receipt
            return DecisionResult(ApprovalOutcome.APPROVED, request_id, request.action_digest, receipt, authenticated_subject.subject_ref)

    def revoke(self, receipt_id, actor, reason):
        if not isinstance(actor, HumanAuthenticationAssertion) or not isinstance(reason, str) or not reason.strip():
            return RevocationResult(ApprovalOutcome.MALFORMED, receipt_id)
        return RevocationResult(ApprovalOutcome.REVOKED, receipt_id, reason)


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def assertion(request):
    return provider_assertion(request.approval_request_id, request.audience, "2099-01-01T00:00:00Z", "human-1")


def test_digest_domain_excludes_caller_declared_digest_and_rejects_mismatch():
    assert PACKAGE.digest() == make_package(contract_digest="bogus").digest()
    assert validate_action_package(make_package(contract_digest="bogus")) == ["contract_digest does not match canonical action digest"]


def test_stable_id_and_atomic_same_key_conflict_under_concurrency():
    adapter = ObservableAdapter()
    results = list(ThreadPoolExecutor(max_workers=8).map(lambda _: adapter.create_request(PACKAGE, CONTEXT), range(8)))
    assert {r.approval_request_id for r in results} == {"req-1"}
    conflict = adapter.create_request(make_package(parameters={"changed": True}), CONTEXT)
    assert conflict.outcome is ApprovalOutcome.IDEMPOTENCY_CONFLICT
    assert adapter.counter == 1


def test_presentation_is_immutable_and_rehashed():
    adapter = ObservableAdapter(); request = adapter.create_request(PACKAGE, CONTEXT)
    presentation = adapter.present(request.approval_request_id)
    assert presentation.outcome is ApprovalOutcome.PRESENTED
    assert validate_presentation(presentation.action_package, request.action_digest)
    try:
        presentation.action_package["parameters"] = {}  # type: ignore[index]
        assert False
    except TypeError:
        pass
    assert validate_presentation(presentation.action_package, request.action_digest)


def test_forged_subject_and_wrong_binding_are_not_proof():
    adapter = ObservableAdapter(); request = adapter.create_request(PACKAGE, CONTEXT)
    assert adapter.record_decision(request.approval_request_id, "approve", AuthenticatedHumanSubject("human-1", "fake")).outcome is ApprovalOutcome.UNAUTHENTICATED
    forged = provider_assertion("other-request", request.audience, "2099-01-01T00:00:00Z", "human-1")
    assert adapter.record_decision(request.approval_request_id, "approve", forged).outcome is ApprovalOutcome.UNAUTHENTICATED


def test_approved_decision_has_typed_versioned_secret_free_receipt_and_is_idempotent():
    adapter = ObservableAdapter(); request = adapter.create_request(PACKAGE, CONTEXT)
    first = adapter.record_decision(request.approval_request_id, "approve", assertion(request))
    second = adapter.record_decision(request.approval_request_id, "approve", assertion(request))
    assert first.outcome is ApprovalOutcome.APPROVED and isinstance(first.receipt, ApprovalReceipt)
    assert first.receipt.receipt_version == "1" and first.receipt == second.receipt
    assert "signature" not in first.receipt.payload and "secret" not in repr(first.receipt.payload).lower()


def test_malformed_types_and_expiry_are_explicit():
    assert any("integer" in e for e in validate_action_package(make_package(lease_ttl=True)))
    assert any("timestamp" in e for e in validate_action_package(make_package(approval_expires_at=123)))
    expired = make_package(approval_expires_at="2000-01-01T00:00:00Z")
    adapter = ObservableAdapter(); request = adapter.create_request(expired, RequesterContext("r", "a", "e"))
    assert request.outcome is ApprovalOutcome.PENDING
    assert adapter.record_decision(request.approval_request_id, "approve", assertion(request)).outcome is ApprovalOutcome.EXPIRED


def test_invalid_decision_and_revocation_inputs_fail_closed():
    adapter = ObservableAdapter(); request = adapter.create_request(PACKAGE, CONTEXT)
    assert adapter.record_decision(request.approval_request_id, 1, None).outcome is ApprovalOutcome.MALFORMED
    assert adapter.revoke("r", "human", "reason").outcome is ApprovalOutcome.MALFORMED


def test_contract_has_no_deployment_secrets():
    assert not hasattr(ApprovalGateAdapter, "channel")
    assert not hasattr(ApprovalGateAdapter, "private_key")
    assert not hasattr(ApprovalGateAdapter, "credential")
