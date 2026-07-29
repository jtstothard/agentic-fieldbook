"""Observable contract tests for the deployment-neutral approval gate seam."""

from dataclasses import replace
from typing import Any, Mapping

from agentic_fieldbook.approval_gate import (
    ActionPackage,
    ApprovalGateAdapter,
    ApprovalOutcome,
    AuthenticatedHumanSubject,
    ApprovalRequest,
    DecisionResult,
    PresentationResult,
    RequesterContext,
    RevocationResult,
    validate_action_package,
)


PACKAGE = ActionPackage(
    contract_digest="sha256:" + "a" * 64,
    target={"cluster": "example", "type": "guest", "id": "123"},
    capability="snapshot_guest",
    parameters={"snapshot": "approved", "labels": ["one", "two"]},
    lease_ttl=300,
    operation_limit=1,
    verification_method="direct-query",
    rollback={"required": True},
    abort_conditions=["verification-fails"],
    approval_expires_at="2025-01-01T00:10:00Z",
)
CONTEXT = RequesterContext("requester-ref", "broker-ref", "retry-key")
SUBJECT = AuthenticatedHumanSubject("human-subject-ref", "idp-auth-context")


class ObservableAdapter(ApprovalGateAdapter):
    """Small deployment-free test double exercising only public outcomes."""

    def __init__(self):
        self.requests: dict[str, ApprovalRequest] = {}
        self.retries: dict[str, str] = {}
        self.receipts: dict[str, Mapping[str, Any]] = {}
        self.counter = 0
        self.service_available = True

    def create_request(self, action_package, requester_context):
        if not self.service_available:
            return ApprovalRequest("", "", {}, "", "", "", ApprovalOutcome.UNAVAILABLE)
        errors = validate_action_package(action_package)
        if errors:
            return ApprovalRequest("", "", {}, "", "", "", ApprovalOutcome.MALFORMED)
        digest = action_package.digest()
        previous = self.retries.get(requester_context.idempotency_key)
        if previous:
            return self.requests[previous]
        self.counter += 1
        request = ApprovalRequest(
            f"approval-request-{self.counter}", digest, action_package.as_mapping(),
            requester_context.requester_ref, requester_context.audience,
            action_package.approval_expires_at,
        )
        self.requests[request.approval_request_id] = request
        self.retries[requester_context.idempotency_key] = request.approval_request_id
        return request

    def present(self, request_id):
        request = self.requests.get(request_id)
        if not self.service_available:
            return PresentationResult(ApprovalOutcome.UNAVAILABLE, request_id, "")
        if request is None:
            return PresentationResult(ApprovalOutcome.MALFORMED, request_id, "", reason="unknown request")
        return PresentationResult(ApprovalOutcome.PRESENTED, request_id, request.action_digest, request.action_package)

    def record_decision(self, request_id, decision, authenticated_subject):
        request = self.requests.get(request_id)
        if not self.service_available:
            return DecisionResult(ApprovalOutcome.UNAVAILABLE, request_id)
        if request is None or decision not in {"approve", "reject"}:
            return DecisionResult(ApprovalOutcome.MALFORMED, request_id)
        if authenticated_subject is None:
            return DecisionResult(ApprovalOutcome.UNAUTHENTICATED, request_id)
        if request.expires_at < "2020-01-01T00:00:00Z":
            return DecisionResult(ApprovalOutcome.EXPIRED, request_id, request.action_digest)
        if decision == "reject":
            return DecisionResult(ApprovalOutcome.REJECTED, request_id, request.action_digest)
        receipt = {"approval_request_id": request_id, "action_digest": request.action_digest,
                   "issuer": authenticated_subject.subject_ref, "decision": "approved"}
        self.receipts[request_id] = receipt
        return DecisionResult(ApprovalOutcome.APPROVED, request_id, request.action_digest, receipt,
                              authenticated_subject.subject_ref)

    def revoke(self, receipt_id, actor, reason):
        if not self.service_available:
            return RevocationResult(ApprovalOutcome.UNAVAILABLE, receipt_id)
        if actor is None or not reason.strip():
            return RevocationResult(ApprovalOutcome.MALFORMED, receipt_id)
        return RevocationResult(ApprovalOutcome.REVOKED, receipt_id, reason)


def test_request_has_stable_id_and_immutable_digest():
    adapter = ObservableAdapter()
    first = adapter.create_request(PACKAGE, CONTEXT)
    retry = adapter.create_request(PACKAGE, CONTEXT)
    assert first.approval_request_id == retry.approval_request_id
    assert first.action_digest == retry.action_digest == PACKAGE.digest()
    assert first.action_package == PACKAGE.as_mapping()


def test_presentation_is_exact_and_independently_hashable():
    adapter = ObservableAdapter()
    request = adapter.create_request(PACKAGE, CONTEXT)
    presentation = adapter.present(request.approval_request_id)
    assert presentation.outcome is ApprovalOutcome.PRESENTED
    assert presentation.action_digest == request.action_digest
    assert presentation.action_package == request.action_package
    assert presentation.action_digest == PACKAGE.digest()
    changed = dict(presentation.action_package)
    changed["parameters"] = {"snapshot": "different"}
    assert ActionPackage(**changed).digest() != presentation.action_digest


def test_decision_requires_independently_authenticated_subject():
    adapter = ObservableAdapter()
    request = adapter.create_request(PACKAGE, CONTEXT)
    assert adapter.record_decision(request.approval_request_id, "approve", None).outcome is ApprovalOutcome.UNAUTHENTICATED
    approved = adapter.record_decision(request.approval_request_id, "approve", SUBJECT)
    assert approved.outcome is ApprovalOutcome.APPROVED
    assert approved.issuer_subject_ref == SUBJECT.subject_ref
    assert approved.receipt["issuer"] == SUBJECT.subject_ref


def test_non_success_outcomes_are_explicit_and_fail_closed():
    adapter = ObservableAdapter()
    request = adapter.create_request(PACKAGE, CONTEXT)
    assert adapter.record_decision(request.approval_request_id, "reject", SUBJECT).outcome is ApprovalOutcome.REJECTED
    assert adapter.revoke("receipt-1", SUBJECT, "operator action").outcome is ApprovalOutcome.REVOKED
    assert adapter.revoke("receipt-1", SUBJECT, "").outcome is ApprovalOutcome.MALFORMED
    adapter.service_available = False
    assert adapter.present(request.approval_request_id).outcome is ApprovalOutcome.UNAVAILABLE
    assert adapter.record_decision(request.approval_request_id, "approve", SUBJECT).outcome is ApprovalOutcome.UNAVAILABLE
    assert adapter.revoke("receipt-1", SUBJECT, "operator action").outcome is ApprovalOutcome.UNAVAILABLE


def test_expired_decision_is_explicit():
    adapter = ObservableAdapter()
    expired_package = replace(PACKAGE, approval_expires_at="2019-01-01T00:00:00Z")
    request = adapter.create_request(expired_package, CONTEXT)
    result = adapter.record_decision(request.approval_request_id, "approve", SUBJECT)
    assert result.outcome is ApprovalOutcome.EXPIRED


def test_malformed_request_is_explicit():
    adapter = ObservableAdapter()
    malformed = replace(PACKAGE, capability="", operation_limit=0)
    result = adapter.create_request(malformed, CONTEXT)
    assert result.outcome is ApprovalOutcome.MALFORMED
    assert validate_action_package(malformed) == ["capability is required", "operation_limit must be >= 1"]


def test_retry_does_not_create_second_authorization():
    adapter = ObservableAdapter()
    request = adapter.create_request(PACKAGE, CONTEXT)
    first = adapter.record_decision(request.approval_request_id, "approve", SUBJECT)
    second = adapter.record_decision(request.approval_request_id, "approve", SUBJECT)
    assert first.receipt == second.receipt
    assert len(adapter.receipts) == 1
    assert adapter.counter == 1


def test_contract_has_no_deployment_secret_or_channel_requirement():
    assert not hasattr(ApprovalGateAdapter, "channel")
    assert not hasattr(ApprovalGateAdapter, "private_key")
    assert not hasattr(ApprovalGateAdapter, "credential")
