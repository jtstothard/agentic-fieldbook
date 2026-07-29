"""Deployment-neutral orchestration of native approval and broker verification."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .approval_gate import (
    ActionPackage, ApprovalGateAdapter, ApprovalOutcome, HumanAuthenticationAssertion,
    RequesterContext, validate_action_package, _thaw,
)
from .broker import (
    ApproverPolicy, ApprovalStore, Clock, KeyStore, VerificationResult,
    verify_approval_receipt,
)


@dataclass
class NativeApprovalFlow:
    """Connect the public gate seam to broker verification without trusting adapters."""
    adapter: ApprovalGateAdapter
    keystore: KeyStore
    policy: ApproverPolicy
    store: ApprovalStore
    clock: Clock
    broker_audience: str = ""

    def authorize(
        self,
        action_package: ActionPackage,
        requester_context: RequesterContext,
        authenticated_subject: HumanAuthenticationAssertion,
    ) -> VerificationResult:
        errors = validate_action_package(action_package)
        if errors:
            from .broker import VERIFICATION_FAILED
            return VerificationResult(False, VERIFICATION_FAILED, "action package validation failed")
        request = self.adapter.create_request(action_package, requester_context)
        if request.outcome is not ApprovalOutcome.PENDING:
            from .broker import VERIFICATION_FAILED
            return VerificationResult(False, VERIFICATION_FAILED, "approval request was not created")
        presentation = self.adapter.present(request.approval_request_id)
        if presentation.outcome is not ApprovalOutcome.PRESENTED:
            from .broker import VERIFICATION_FAILED
            return VerificationResult(False, VERIFICATION_FAILED, "approval presentation failed")
        decision = self.adapter.record_decision(request.approval_request_id, "approve", authenticated_subject)
        if decision.outcome is not ApprovalOutcome.APPROVED or decision.receipt is None:
            from .broker import VERIFICATION_FAILED
            return VerificationResult(False, VERIFICATION_FAILED, "approval decision did not authorize")
        receipt = _thaw(decision.receipt.payload)
        audience = self.broker_audience or requester_context.audience
        contract = _thaw(action_package.as_mapping())
        contract.pop("contract_digest", None)
        return verify_approval_receipt(
            receipt, contract, audience, requester_context.requester_ref,
            self.keystore, self.policy, self.store, self.clock,
        )
