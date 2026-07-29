"""Deployment-neutral orchestration of native approval and broker verification."""
from __future__ import annotations

from dataclasses import dataclass


from .approval_gate import (
    ActionPackage, ApprovalGateAdapter, ApprovalOutcome, HumanAuthenticationAssertion,
    RequesterContext, validate_action_package, validate_presentation, ApprovalRequest,
    PresentationResult, DecisionResult, _thaw,
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
    broker_audience: str

    def __post_init__(self) -> None:
        if not isinstance(self.broker_audience, str) or not self.broker_audience.strip():
            raise ValueError("broker_audience is required")

    @staticmethod
    def _failed() -> VerificationResult:
        from .broker import VERIFICATION_FAILED
        return VerificationResult(False, VERIFICATION_FAILED, "approval flow failed closed")

    def authorize(
        self,
        action_package: ActionPackage,
        requester_context: RequesterContext,
        authenticated_subject: HumanAuthenticationAssertion,
    ) -> VerificationResult:
        if (validate_action_package(action_package)
                or not isinstance(requester_context, RequesterContext)
                or requester_context.audience != self.broker_audience):
            if isinstance(requester_context, RequesterContext) and requester_context.audience != self.broker_audience:
                from .broker import AUDIENCE_MISMATCH
                return VerificationResult(False, AUDIENCE_MISMATCH, "request audience does not match this broker")
            return self._failed()
        try:
            request = self.adapter.create_request(action_package, requester_context)
            if (not isinstance(request, ApprovalRequest)
                    or request.outcome is not ApprovalOutcome.PENDING
                    or not isinstance(request.approval_request_id, str)
                    or not request.approval_request_id
                    or request.action_digest != action_package.digest()
                    or _thaw(request.action_package) != action_package.as_mapping()
                    or request.requester_ref != requester_context.requester_ref
                    or request.audience != self.broker_audience
                    or request.expires_at != action_package.approval_expires_at
                    or request.idempotency_key not in ("", requester_context.idempotency_key)):
                return self._failed()
            presentation = self.adapter.present(request.approval_request_id)
            if (not isinstance(presentation, PresentationResult)
                    or presentation.outcome is not ApprovalOutcome.PRESENTED
                    or presentation.approval_request_id != request.approval_request_id
                    or presentation.action_digest != request.action_digest
                    or presentation.action_package is None
                    or not validate_presentation(presentation.action_package, request.action_digest)):
                return self._failed()
            decision = self.adapter.record_decision(request.approval_request_id, "approve", authenticated_subject)
            if (not isinstance(decision, DecisionResult)
                    or decision.outcome is not ApprovalOutcome.APPROVED
                    or decision.approval_request_id != request.approval_request_id
                    or decision.action_digest != request.action_digest
                    or decision.receipt is None
                    or decision.receipt.approval_request_id != request.approval_request_id
                    or decision.receipt.action_digest != request.action_digest):
                return self._failed()
            receipt = _thaw(decision.receipt.payload)
        except Exception:
            return self._failed()
        audience = self.broker_audience
        # Preserve the package's contract_digest: the broker verifies it against
        # the complete contract projection before reserving replay/lease state.
        contract = _thaw(action_package.as_mapping())
        try:
            return verify_approval_receipt(
                receipt, contract, audience, requester_context.requester_ref,
                self.keystore, self.policy, self.store, self.clock,
            )
        except Exception:
            return self._failed()
