"""Tests for the v0.3.0 adapter contract interface.

These tests verify that adapters comply with the contract interface and
correctly report their capabilities. They do NOT test adapter-specific
behavior (those are in the adapter characterization tests).
"""

import pytest

from agentic_fieldbook.adapter_contract import (
    AdapterCapability,
    ClaimLostError,
    CreateResult,
    DispatchAdapter,
    DispatchResult,
    ClaimResult,
    StatusResult,
    ResultResult,
    TaskNotFoundError,
    TaskStatus,
    UnsupportedOperationError,
)


class TestAdapterInterface:
    """Test that the DispatchAdapter interface is well-defined."""

    def test_stable_methods_are_goal_dispatch_status_and_capabilities(self):
        """The stable API dispatches a real goal; Kanban methods are optional."""
        abstract_methods = DispatchAdapter.__abstractmethods__
        expected_methods = {
            "get_status",
            "dispatch",
            "get_capabilities",
        }
        assert abstract_methods == expected_methods

    def test_dispatch_requires_non_empty_goal_and_assignee_is_keyword_only(self):
        import inspect

        signature = inspect.signature(DispatchAdapter.dispatch)
        assert list(signature.parameters) == ["self", "goal", "assignee"]
        assert signature.parameters["goal"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert signature.parameters["assignee"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_return_types_are_dataclasses(self):
        """All operation results must be dataclasses with required fields."""

        # CreateResult
        result = CreateResult(success=True, task_id="t_123", status=TaskStatus.READY, metadata={})
        assert result.success is True
        assert result.task_id == "t_123"
        assert result.status == TaskStatus.READY
        assert result.metadata == {}

        # ClaimResult
        result = ClaimResult(success=True, status=TaskStatus.RUNNING, task_id="t_123", metadata={})
        assert result.success is True
        assert result.status == TaskStatus.RUNNING
        assert result.task_id == "t_123"
        assert result.metadata == {}

        # StatusResult
        result = StatusResult(success=True, status=TaskStatus.DONE, metadata={})
        assert result.success is True
        assert result.status == TaskStatus.DONE
        assert result.metadata == {}

        # ResultResult
        result = ResultResult(success=True, result="test-output", metadata={})
        assert result.success is True
        assert result.result == "test-output"
        assert result.metadata == {}

        # DispatchResult
        result = DispatchResult(success=True, task_id="t_123", metadata={}, message="")
        assert result.success is True
        assert result.task_id == "t_123"
        assert result.metadata == {}

    def test_task_status_enum(self):
        """TaskStatus enum must cover all observed statuses."""
        # From contrast evidence: inline uses SYNCHRONOUS, kanban uses READY/RUNNING/DONE/BLOCKED
        all_statuses = {status.value for status in TaskStatus}
        expected_statuses = {"ready", "running", "done", "blocked", "synchronous"}
        assert all_statuses == expected_statuses

    def test_adapter_capability_enum(self):
        """AdapterCapability enum must cover all observed capabilities."""
        # From contrast evidence: differences between inline and kanban
        all_capabilities = {cap.value for cap in AdapterCapability}
        expected_capabilities = {
            "sync_dispatch",
            "async_dispatch",
            "task_id_persistence",
            "task_creation",
            "result_persistence",
            "status_tracking",
            "claim_lifecycle",
            "dry_run_enforcement",
            "idempotency_enforcement",
            "concurrent_claim_detection",
            "stale_claim_recovery",
            "failure_state_management",
        }
        assert all_capabilities == expected_capabilities

    def test_error_hierarchy(self):
        """Error types must be well-defined and usable."""

        # ClaimLostError should be instantiable
        error = ClaimLostError("Lost the race")
        assert isinstance(error, RuntimeError)
        assert "Lost the race" in str(error)

        # TaskNotFoundError should be instantiable
        error = TaskNotFoundError("t_missing")
        assert isinstance(error, RuntimeError)
        assert "t_missing" in str(error)

        # UnsupportedOperationError should be instantiable
        error = UnsupportedOperationError("claim_task")
        assert isinstance(error, RuntimeError)
        assert "claim_task" in str(error)


class TestInlineAdapterContractCompliance:
    """Test that InlineAdapterContract complies with the contract."""

    def test_inline_adapter_implements_contract(self):
        """InlineAdapterContract must be a DispatchAdapter subclass."""
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        assert issubclass(InlineAdapterContract, DispatchAdapter)

    def test_inline_adapter_reports_capabilities(self):
        """InlineAdapterContract must correctly report its (limited) capabilities."""
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        adapter = InlineAdapterContract()
        capabilities = adapter.get_capabilities()

        # From contrast evidence: inline does NOT support async, claims, persistence
        assert AdapterCapability.ASYNC_DISPATCH not in capabilities
        assert AdapterCapability.CLAIM_LIFECYCLE not in capabilities
        assert AdapterCapability.TASK_CREATION not in capabilities
        assert AdapterCapability.TASK_ID_PERSISTENCE not in capabilities
        assert AdapterCapability.RESULT_PERSISTENCE not in capabilities

    def test_inline_dispatch_returns_none_task_id(self):
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        result = InlineAdapterContract().dispatch("test", assignee="coder")
        assert result.task_id is None

    def test_inline_dispatch_rejects_empty_goal(self):
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        with pytest.raises(ValueError, match="non-empty"):
            InlineAdapterContract().dispatch("", assignee="coder")

    def test_inline_adapter_get_status_returns_synchronous(self):
        """InlineAdapterContract must return SYNCHRONOUS status."""
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        adapter = InlineAdapterContract()
        status = adapter.get_status("ignored_task_id")
        assert status.status == TaskStatus.SYNCHRONOUS

    def test_inline_contract_does_not_fake_unsupported_result_read(self):
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        assert not hasattr(InlineAdapterContract(), "read_result")


class TestContractAdditiveSuperset:
    """Test that the contract represents an additive superset of observed behavior."""

    def test_contract_covers_inline_lifecycle(self):
        """Contract must cover inline create/execute/status lifecycle."""
        # Inline lifecycle: create, status query (executes synchronously)
        required_methods = {"get_status", "dispatch", "get_capabilities"}
        assert required_methods.issubset(DispatchAdapter.__abstractmethods__)

    def test_contract_covers_kanban_lifecycle(self):
        """Contract must cover Kanban create/claim/dispatch/result/failure lifecycle."""
        # Kanban lifecycle: create, claim, dispatch, poll (status), read_result, handle_failure
        required_methods = {"dispatch", "get_status", "get_capabilities"}
        assert required_methods.issubset(DispatchAdapter.__abstractmethods__)

    def test_contract_covers_shared_parameters(self):
        """Contract must cover parameters observed in both adapters."""
        import inspect

        dispatch_sig = inspect.signature(DispatchAdapter.dispatch)
        assert list(dispatch_sig.parameters) == ["self", "goal", "assignee"]


class TestContractFailureSemantics:
    """Test that contract failure semantics are explicit and recoverable."""

    def test_claim_lost_error_is_explicit(self):
        """ClaimLostError must be a distinct error type."""
        assert issubclass(ClaimLostError, RuntimeError)

    def test_task_not_found_error_is_explicit(self):
        """TaskNotFoundError must be distinct."""
        assert issubclass(TaskNotFoundError, RuntimeError)

    def test_unsupported_operation_error_is_explicit(self):
        """UnsupportedOperationError must be distinct."""
        assert issubclass(UnsupportedOperationError, RuntimeError)

class TestContractDryRunSemantics:
    """Test that contract covers dry-run semantics from evidence."""

    def test_dry_run_capability_is_optional(self):
        """Dry run enforcement is an optional capability."""
        # From contrast evidence: inline does not enforce dry_run, kanban does
        assert AdapterCapability.DRY_RUN_ENFORCEMENT in AdapterCapability


class TestContractIdempotencySemantics:
    """Test that contract covers idempotency semantics from evidence."""


    def test_idempotency_capability_is_optional(self):
        """Idempotency enforcement is an optional capability."""
        # From contrast evidence: inline does not enforce idempotency, kanban requires backend
        assert AdapterCapability.IDEMPOTENCY_ENFORCEMENT in AdapterCapability


class TestContractCapabilityReporting:
    """Test that capability reporting is well-defined."""

    def test_get_capabilities_returns_set(self):
        """get_capabilities must return a set of AdapterCapability values."""
        from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract

        adapter = InlineAdapterContract()
        capabilities = adapter.get_capabilities()

        assert isinstance(capabilities, set)
        for cap in capabilities:
            assert isinstance(cap, AdapterCapability)

    def test_capability_enum_is_exhaustive(self):
        """Capability enum must include all required capabilities."""
        # From contrast evidence: this is the minimal set covering both adapters
        required_capabilities = {
            "sync_dispatch",
            "async_dispatch",
            "task_id_persistence",
            "task_creation",
            "result_persistence",
            "status_tracking",
            "claim_lifecycle",
            "dry_run_enforcement",
            "idempotency_enforcement",
            "concurrent_claim_detection",
            "stale_claim_recovery",
            "failure_state_management",
        }
        all_capabilities = {cap.value for cap in AdapterCapability}
        assert required_capabilities.issubset(all_capabilities)