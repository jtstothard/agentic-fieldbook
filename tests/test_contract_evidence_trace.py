"""Evidence-based tests for v0.3.0 adapter contract.

These tests verify the contract documentation traces to observed evidence
from the contrast matrix (16268bb). They do NOT test the sophisticated
DispatchAdapter abstract class; that's covered by separate tests.
"""

from pathlib import Path

from agentic_fieldbook.adapter_contract import DispatchResult, StatusResult
from agentic_fieldbook.inline_adapter_contract import InlineAdapterContract
from agentic_fieldbook.kanban_adapter import KanbanAdapter

ROOT = Path(__file__).resolve().parent.parent


def test_contract_document_exists_and_traces_to_evidence():
    """Contract must exist and reference the contrast evidence."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    assert "docs/adapter-contrast-matrix.md" in contract
    assert "16268bb" in contract
    assert "57b9b17" in contract
    for operation in ("dispatch", "get_status", "create", "claim", "poll", "read_result", "handle_failure"):
        assert operation in contract


def test_contract_documents_all_9_scenarios():
    """Contract must document all contrast matrix scenarios."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    scenarios = [
        "create_dispatch",
        "claim_poll",
        "status_check",
        "result_read",
        "dry_run",
        "repeated_invocation",
        "concurrent_claim",
        "stale_claim_recovery",
        "handle_failure",
    ]
    for scenario in scenarios:
        assert scenario.lower() in contract.lower()


def test_shared_dispatch_shapes_are_stable():
    """Inline adapter returns stable DispatchResult shape per contract."""
    result = InlineAdapterContract().dispatch("contract task", assignee="worker")
    status = InlineAdapterContract().get_status("ignored")

    assert isinstance(result, DispatchResult)
    assert result.success is True
    assert result.task_id is None  # Contract: Inline returns task_id=None
    assert result.metadata["backend"] == "inline"
    assert isinstance(status, StatusResult)
    assert status.success is True
    assert status.metadata["backend"] == "inline"


def test_inline_limitations_are_explicit_not_fake_success():
    """Inline adapter limitations are explicit, not hidden behind fake success."""
    adapter = InlineAdapterContract()

    # Idempotency is not part of the observed inline dispatch seam.
    first = adapter.dispatch("same task", assignee="worker")
    second = adapter.dispatch("same task", assignee="worker")

    assert first.success and second.success
    assert first.task_id is None and second.task_id is None
    assert "idempotency_key" not in first.metadata

    # Kanban-only operations are NOT present on Inline
    kanban_only = ("create", "claim", "poll", "read_result", "handle_failure")
    for capability in kanban_only:
        assert not hasattr(adapter, capability)


def test_kanban_only_capabilities_are_not_claimed_by_inline():
    """Inline adapter doesn't claim Kanban-only capabilities."""
    inline = InlineAdapterContract()
    kanban_capabilities = ("create", "claim", "poll", "read_result", "handle_failure")
    assert all(not hasattr(inline, capability) for capability in kanban_capabilities)
    assert all(hasattr(KanbanAdapter, capability) for capability in kanban_capabilities)


def test_contract_documents_unsupported_dependency_semantics():
    """Contract explicitly excludes unsupported dependency semantics."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    assert "Dependency Failure Recovery" in contract
    assert "Not directly tested in contrast matrix" in contract
    assert "out of contract scope" in contract.lower()


def test_contract_documents_deterministic_recovery_boundaries():
    """Contract documents all observed recovery boundaries."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    for phrase in (
        "Stale Claim Recovery",
        "Concurrent Claim Recovery",
        "Failure Semantics",
        "Idempotency",
    ):
        assert phrase in contract
    assert "Optional operations are exposed only by capability protocols" in contract


def test_contract_declares_capability_detection_required():
    """Contract requires capability detection before Kanban-only operations."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    assert "Capability Detection" in contract
    assert "AdapterCapability.TASK_CREATION in capabilities and isinstance(adapter, TaskCreator)" in contract
    assert "AdapterCapability.CLAIM_LIFECYCLE in capabilities" in contract
    assert "isinstance(adapter, ClaimLifecycle)" in contract
    assert "Callers MUST verify the adapter supports them" in contract


def test_contract_traces_operations_to_evidence():
    """Each contract operation traces to specific contrast matrix evidence."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")

    operations_evidence = [
        ("dispatch", "Scenario `create_dispatch`"),
        ("get_status", "Scenario `status_check`"),
        ("create", "Scenario `claim_poll`"),
        ("claim", "Scenario `concurrent_claim`"),
        ("poll", "Scenario `claim_poll`"),
        ("read_result", "Scenario `result_read`"),
        ("handle_failure", "Scenario `handle_failure`"),
    ]

    for operation, evidence_hint in operations_evidence:
        assert operation in contract
        assert evidence_hint in contract


def test_contract_documents_all_inline_limitations():
    """Contract documents all observed Inline adapter limitations."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")

    inline_limitations = [
        "Cannot prevent duplicate work",
        "Cannot re-read results after session ends",
        "Cannot record and requeue failed tasks",
        "Cannot recover from stale claims",
        "No persistent task ID across sessions",
        "No real dry-run enforcement",
        "No task-level idempotency",
    ]

    for limitation in inline_limitations:
        assert limitation in contract


def test_contract_documents_all_kanban_limitations():
    """Contract documents all observed Kanban adapter limitations."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")

    kanban_limitations = [
        "Requires Kanban backend infrastructure",
        "Additional complexity for simple synchronous tasks",
        "Claim race complexity requires careful TTL management",
        "Idempotency requires Kanban backend enforcement",
    ]

    for limitation in kanban_limitations:
        assert limitation in contract


def test_contract_declares_deterministic_behavior():
    """Contract declares that all operations must be deterministic."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    assert "Deterministic Behavior" in contract
    assert "All contract operations must produce deterministic results" in contract
    assert "never return success when operation failed" in contract.lower()


def test_contract_declares_additive_evolution():
    """Contract declares versioning and evolution rules."""
    contract = (ROOT / "docs" / "adapter-contract.md").read_text(encoding="utf-8")
    assert "Versioning and Evolution" in contract
    assert "v0.3.0" in contract
    assert "Additive only" in contract
    assert "Deprecated before removal" in contract