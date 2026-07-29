"""End-to-end native approval gate -> broker verification regression tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from agentic_fieldbook.approval_flow import NativeApprovalFlow
from agentic_fieldbook.approval_gate import (
    ActionPackage, ApprovalGateAdapter, ApprovalOutcome, ApprovalReceipt,
    ApprovalRequest, DecisionResult, HumanAuthenticationAssertion, PresentationResult,
    RequesterContext, RevocationResult, provider_assertion,
)
from agentic_fieldbook.broker import (
    ACTION_MISMATCH, AUDIENCE_MISMATCH, VERIFICATION_FAILED, ApprovalStore, ApproverPolicy, Clock, KeyStore,
    ReservationOutcome, verify_approval_receipt,
)
from agentic_fieldbook.receipt import canonical_digest, signed_payload
import hashlib


class Adapter(ApprovalGateAdapter):
    def __init__(self, receipt: Mapping[str, Any]):
        self.receipt = dict(receipt)
        self.request: ApprovalRequest | None = None

    def create_request(self, action_package, requester_context):
        self.request = ApprovalRequest("req-1", action_package.digest(), action_package.as_mapping(),
                                      requester_context.requester_ref, requester_context.audience,
                                      action_package.approval_expires_at,
                                      idempotency_key=requester_context.idempotency_key)
        return self.request

    def present(self, request_id):
        assert self.request and request_id == self.request.approval_request_id
        return PresentationResult(ApprovalOutcome.PRESENTED, request_id,
                                  self.request.action_digest, self.request.action_package)

    def record_decision(self, request_id, decision, authenticated_subject):
        if decision != "approve":
            return DecisionResult(ApprovalOutcome.REJECTED, request_id)
        return DecisionResult(ApprovalOutcome.APPROVED, request_id,
                              self.request.action_digest if self.request else None,
                              ApprovalReceipt("1", self.receipt["receipt_id"], request_id,
                                              self.receipt["action_digest"], self.receipt))

    def revoke(self, receipt_id, actor, reason):
        return RevocationResult(ApprovalOutcome.REVOKED, receipt_id, reason)


class Keys(KeyStore):
    def verify_signature(self, signature, payload):
        return signature["value"] == hashlib.sha256(payload).hexdigest()


class Policy(ApproverPolicy):
    def is_authorized_approver(self, issuer, capability, target):
        return issuer == "human-1"

    def is_requester_authorized(self, requester, capability):
        return requester == "requester-1"


class Store(ApprovalStore):
    def __init__(self):
        self.consumed_nonces = set()
        self.consumed_receipt_ids = set()
        self.consumed_request_ids = set()
        self.events = []
        self.lease_events = []

    def is_available(self): return True
    def get_request_status(self, request_id): return "approved"

    def reserve_and_record_verification(self, receipt_id, nonce, request_id, timestamp):
        if (nonce in self.consumed_nonces
                or receipt_id in self.consumed_receipt_ids
                or request_id in self.consumed_request_ids):
            return ReservationOutcome.REPLAY
        self.consumed_nonces.add(nonce)
        self.consumed_receipt_ids.add(receipt_id)
        self.consumed_request_ids.add(request_id)
        self.events.append((receipt_id, request_id, timestamp))
        return ReservationOutcome.RESERVED

    def reserve_and_record_lease(self, receipt_id, nonce, request_id, action_digest,
                                 target, capability, parameters, issued_at,
                                 expires_at, operation_limit):
        """Atomically reserve replay keys and commit verification plus lease audit."""
        if (nonce in self.consumed_nonces
                or receipt_id in self.consumed_receipt_ids
                or request_id in self.consumed_request_ids):
            return ReservationOutcome.REPLAY
        self.consumed_nonces.add(nonce)
        self.consumed_receipt_ids.add(receipt_id)
        self.consumed_request_ids.add(request_id)
        self.events.append((receipt_id, request_id, issued_at))
        self.lease_events.append((receipt_id, request_id, action_digest))
        return ReservationOutcome.RESERVED


class FixedClock(Clock):
    def utcnow(self): return datetime(2025, 1, 1, 12, tzinfo=timezone.utc)


def make_case():
    contract = {"target": {"type": "guest", "id": "123"}, "capability": "snapshot_guest",
                "parameters": {"nested": {"flag": True}}, "lease_ttl": 300,
                "operation_limit": 1, "verification_method": "direct-query",
                "rollback": {}, "abort_conditions": [],
                "approval_expires_at": "2025-01-01T12:05:00Z"}
    digest = canonical_digest(contract)
    receipt = {"receipt_version": "1", "approval_request_id": "req-1", "decision": "approved",
               "action_digest": digest, "target": contract["target"], "capability": contract["capability"],
               "parameters": contract["parameters"], "issuer": "human-1",
               "issued_at": "2025-01-01T11:55:00Z", "valid_until": "2025-01-01T12:05:00Z",
               "audience": "broker-1", "receipt_id": "receipt-1", "nonce": "nonce-1",
               "signature": {"algorithm": "test", "key_id": "key-1", "value": ""}}
    receipt["signature"]["value"] = hashlib.sha256(signed_payload(receipt)).hexdigest()
    package = ActionPackage(digest, contract["target"], contract["capability"], contract["parameters"],
                            300, 1, "direct-query", {}, [], "2025-01-01T12:05:00Z")
    return contract, package, receipt


def test_native_flow_connects_authenticated_decision_to_broker_lease():
    contract, package, receipt = make_case()
    store = Store()
    flow = NativeApprovalFlow(Adapter(receipt), Keys(), Policy(), store, FixedClock(), "broker-1")
    result = flow.authorize(package, RequesterContext("requester-1", "broker-1", "retry-1"),
                            provider_assertion("req-1", "broker-1", "2099-01-01T00:00:00Z", "human-1"))
    assert result.success and result.lease_id
    assert store.events == [("receipt-1", "req-1", FixedClock().utcnow())]


def test_native_flow_does_not_authorize_changed_action():
    contract, package, receipt = make_case()
    flow = NativeApprovalFlow(Adapter(receipt), Keys(), Policy(), Store(), FixedClock(), "broker-1")
    changed = replace(package, parameters={"nested": {"flag": 1}}, contract_digest="")
    changed = replace(changed, contract_digest=changed.digest())
    result = flow.authorize(changed, RequesterContext("requester-1", "broker-1", "retry-1"),
                            provider_assertion("req-1", "broker-1", "2099-01-01T00:00:00Z", "human-1"))
    assert not result.success and result.category is VERIFICATION_FAILED
    assert not flow.store.events


class SubstitutionAdapter(Adapter):
    def present(self, request_id):
        presented = dict(self.request.action_package)
        presented["parameters"] = {"nested": {"flag": False}}
        return PresentationResult(ApprovalOutcome.PRESENTED, request_id,
                                  self.request.action_digest, presented)


class IdentityAdapter(Adapter):
    def present(self, request_id):
        result = super().present(request_id)
        return replace(result, approval_request_id="other-request")


class MalformedAdapter(Adapter):
    def present(self, request_id):
        return object()


class ThrowingAdapter(Adapter):
    def present(self, request_id):
        raise RuntimeError("private identity provider detail")


def make_flow(adapter, audience="broker-1"):
    return NativeApprovalFlow(adapter, Keys(), Policy(), Store(), FixedClock(), audience)


def assertion_for_audience(audience):
    return provider_assertion("req-1", audience, "2099-01-01T00:00:00Z", "human-1")


def test_native_flow_rejects_presented_package_substitution_before_decision():
    contract, package, receipt = make_case()
    adapter = SubstitutionAdapter(receipt)
    flow = make_flow(adapter)
    result = flow.authorize(package, RequesterContext("requester-1", "broker-1", "retry-1"),
                                          assertion_for_audience("broker-1"))
    assert not result.success and result.category is VERIFICATION_FAILED
    assert not flow.store.events


def test_native_flow_requires_deployment_owned_audience_and_rejects_override():
    contract, package, receipt = make_case()
    flow = make_flow(Adapter(receipt), "broker-1")
    result = flow.authorize(package, RequesterContext("requester-1", "attacker-audience", "retry-1"),
                            assertion_for_audience("broker-1"))
    assert not result.success and result.category is AUDIENCE_MISMATCH


def test_native_flow_rejects_returned_request_identity_mismatch():
    contract, package, receipt = make_case()
    result = make_flow(IdentityAdapter(receipt)).authorize(
        package, RequesterContext("requester-1", "broker-1", "retry-1"), assertion_for_audience("broker-1"))
    assert not result.success and result.category is VERIFICATION_FAILED


def test_native_flow_normalizes_malformed_and_throwing_adapters_fail_closed():
    contract, package, receipt = make_case()
    context = RequesterContext("requester-1", "broker-1", "retry-1")
    for adapter in (MalformedAdapter(receipt), ThrowingAdapter(receipt)):
        result = make_flow(adapter).authorize(package, context, assertion_for_audience("broker-1"))
        assert not result.success and result.category is VERIFICATION_FAILED
