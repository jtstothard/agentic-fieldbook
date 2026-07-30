"""Focused conformance tests for the Claude Code Fieldbook adapter."""

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from agentic_fieldbook.adapter_contract import AdapterCapability, TaskStatus
from agentic_fieldbook.approval_gate import ApprovalReceipt
from agentic_fieldbook.broker import ApprovalStore, ApproverPolicy, Clock, KeyStore, ReservationOutcome
from agentic_fieldbook.claude_code_adapter import ClaudeCodeAdapter
from tests.claude_adapter_test_helper import make_test_adapter
from agentic_fieldbook.lifecycle import LifecycleState, TaskContract
from agentic_fieldbook.receipt import signed_payload
from agentic_fieldbook.storage import PortableTaskStore


class _TrustedKeyStore(KeyStore):
    def verify_signature(self, signature: Mapping[str, Any], payload: bytes) -> bool:
        return (signature.get("key_id") == "adapter-test-key"
                and signature.get("value") == hashlib.sha256(payload).hexdigest())


class _TrustedPolicy(ApproverPolicy):
    def is_authorized_approver(self, issuer: str, capability: str,
                               target: Mapping[str, Any]) -> bool:
        return issuer == "human-1"

    def is_requester_authorized(self, requester: str, capability: str) -> bool:
        return requester == "fieldbook-requester"


class _TrustedStore(ApprovalStore):
    def __init__(self) -> None:
        self.reserved: set[tuple[str, str, str]] = set()

    def is_available(self) -> bool:
        return True

    def get_request_status(self, request_id: str) -> str | None:
        return "approved" if request_id == "adapter-request" else None

    def reserve_and_record_verification(self, receipt_id: str, nonce: str,
                                        request_id: str, timestamp: datetime) -> ReservationOutcome:
        key = (receipt_id, nonce, request_id)
        if key in self.reserved:
            return ReservationOutcome.REPLAY
        self.reserved.add(key)
        return ReservationOutcome.RESERVED

    def reserve_and_record_lease(self, receipt_id: str, nonce: str, request_id: str,
                                 action_digest: str, target: Mapping[str, Any],
                                 capability: str, parameters: Mapping[str, Any],
                                 issued_at: datetime, expires_at: datetime,
                                 operation_limit: int) -> ReservationOutcome:
        return self.reserve_and_record_verification(receipt_id, nonce, request_id, issued_at)


class _TrustedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self.now = now

    def utcnow(self) -> datetime:
        return self.now


def _attach_trusted_receipt(adapter: ClaudeCodeAdapter, goal: str) -> None:
    binding = adapter._action_binding(goal)
    now = datetime.now(timezone.utc)
    payload = {
        **binding,
        "receipt_version": "1",
        "receipt_id": "adapter-receipt",
        "approval_request_id": "adapter-request",
        "action_digest": binding["action_digest"],
        "contract_digest": binding["contract_digest"],
        "issuer": "human-1",
        "decision": "approved",
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "valid_until": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "audience": "fieldbook",
        "nonce": "adapter-nonce",
        "signature": {"algorithm": "sha256-test", "key_id": "adapter-test-key", "value": "pending"},
    }
    payload["signature"]["value"] = hashlib.sha256(signed_payload(payload)).hexdigest()
    adapter.approval_receipt = ApprovalReceipt("1", "adapter-receipt", "adapter-request",
                                                binding["action_digest"], payload)
    adapter.broker_context = {
        "contract": binding,
        "broker_audience": "fieldbook",
        "requester": "fieldbook-requester",
        "keystore": _TrustedKeyStore(),
        "policy": _TrustedPolicy(),
        "store": _TrustedStore(),
        "clock": _TrustedClock(now),
    }


def claude_payload(result="implemented", session_id="s1", **extra):
    payload = {"type": "result", "subtype": "success", "is_error": False,
               "result": result, "session_id": session_id, "duration_ms": 1}
    payload.update(extra)
    return json.dumps(payload)


def contract(*, risk_class="low", capabilities=("repo-write", "local-test")):
    required_evidence = ("claude-output", "rollback-evidence") if risk_class == "high" else ("claude-output",)
    return TaskContract(
        contract_id="FB-CLAUDE-001",
        objective="Fix the parser bug",
        scope=("agentic_fieldbook", "tests"),
        exclusions=("deployment",),
        risk_class=risk_class,
        capabilities=capabilities,
        acceptance_criteria=("adapter-result-recorded",),
        required_evidence=required_evidence,
        domain="coding.v1",
    )


def test_adapter_reports_persistent_dispatch_and_capability_enforcement(tmp_path: Path):
    adapter = make_test_adapter(
        contract=contract(),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"),
        workspace_root=tmp_path,
        runner=lambda *args, **kwargs: (0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": "s1"}), ""),
    )

    assert adapter.get_capabilities() == {
        AdapterCapability.SYNC_DISPATCH,
        AdapterCapability.TASK_ID_PERSISTENCE,
        AdapterCapability.RESULT_PERSISTENCE,
        AdapterCapability.STATUS_TRACKING,
        AdapterCapability.FAILURE_STATE_MANAGEMENT,
    }


def test_dispatch_injects_contract_runs_claude_and_persists_evidence(tmp_path: Path):
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return 0, claude_payload("implemented", "s1"), ""

    adapter = make_test_adapter(
        contract=contract(),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"),
        workspace_root=tmp_path,
        runner=runner,
    )

    result = adapter.dispatch("Fix the parser bug", assignee="claude-code")

    assert result.success is False
    assert result.task_id
    record = adapter.store.load(result.task_id)
    assert record.state is LifecycleState.REPORTED_COMPLETE
    assert result.metadata["reason"] == "reported_execution"
    assert record.evidence[0]["requirement"] == "claude-output"
    prompt = calls[0][0][2]
    assert "artifact-only" in prompt
    assert "parser bug" in prompt
    assert "deployment" in prompt
    assert adapter.get_status(result.task_id).status is TaskStatus.BLOCKED


def test_high_risk_dispatch_without_approval_is_blocked_and_persisted(tmp_path: Path):
    adapter = make_test_adapter(
        contract=contract(risk_class="high", capabilities=("prod-write",)),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",),
        workspace_root=tmp_path,
        runner=lambda *args, **kwargs: pytest.fail("Claude must not run before approval"),
    )

    result = adapter.dispatch("Change production", assignee="claude-code")

    assert result.success is False
    assert result.metadata["reason"] == "approval_unavailable"
    assert adapter.get_status(result.task_id).status is TaskStatus.BLOCKED


def test_dispatch_fails_closed_when_executor_lacks_capability(tmp_path: Path):
    adapter = make_test_adapter(
        contract=contract(),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("local-test",),
        workspace_root=tmp_path,
        runner=lambda *args, **kwargs: pytest.fail("Claude must not run without capability"),
    )

    result = adapter.dispatch("Fix parser", assignee="claude-code")

    assert result.success is False
    assert result.metadata["reason"] == "capability_mismatch"
    assert adapter.get_status(result.task_id).status is TaskStatus.BLOCKED


def test_high_risk_can_run_only_with_explicit_independent_approval(tmp_path: Path):
    adapter = make_test_adapter(
        contract=contract(risk_class="high", capabilities=("prod-write",)),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",),
        workspace_root=tmp_path,
        approval_actor="human-approver",
        runner=lambda *args, **kwargs: (0, claude_payload("approved run", "s1"), ""),
    )

    result = adapter.dispatch("Change production", assignee="claude-code")

    assert result.success is False
    assert result.metadata["reason"] == "approval_unavailable"
    assert adapter.store.load(result.task_id).state is LifecycleState.BLOCKED


@pytest.mark.parametrize("runner", [
    lambda *args, **kwargs: (0, "", ""),
    lambda *args, **kwargs: (0, "not-json", ""),
    lambda *args, **kwargs: (0, json.dumps({"session_id": "s1"}), ""),
    lambda *args, **kwargs: (_ for _ in ()).throw(OSError("runner unavailable")),
])
def test_adapter_fails_closed_on_invalid_execution_evidence(tmp_path: Path, runner):
    adapter = make_test_adapter(
        contract=contract(),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"),
        workspace_root=tmp_path,
        runner=runner,
    )

    result = adapter.dispatch("Fix parser", assignee="claude-code")

    assert result.success is False
    assert result.metadata["reason"] in {"invalid_output", "execution_failed"}
    assert adapter.store.load(result.task_id).state in {LifecycleState.FAILED, LifecycleState.BLOCKED}
    assert adapter.get_status(result.task_id).status is TaskStatus.BLOCKED


def test_adapter_persists_provenance_and_reports_execution_not_verification(tmp_path: Path):
    adapter = make_test_adapter(
        contract=contract(),
        store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"),
        workspace_root=tmp_path,
        runner=lambda *args, **kwargs: (0, claude_payload("implemented", "s1"), "warning"),
    )

    result = adapter.dispatch("Fix parser", assignee="claude-code")
    record = adapter.store.load(result.task_id)

    assert result.success is False
    assert record.state is LifecycleState.REPORTED_COMPLETE
    assert adapter.get_status(result.task_id).status is not TaskStatus.DONE
    assert record._provenance["session_id"] == "s1"
    assert record._provenance["stderr"] == "warning"
    assert "stdout_digest" in record._provenance
    assert "raw_output" not in record._provenance
    assert record._provenance["contract_digest"]
    assert record._provenance["cwd"] == str(tmp_path.resolve())


def test_adapter_rejects_scope_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="workspace"):
        make_test_adapter(
            contract=TaskContract(
                contract_id="FB-CLAUDE-ESCAPE", objective="x", scope=("../outside",),
                exclusions=(), risk_class="low", capabilities=(),
                acceptance_criteria=("adapter-result-recorded",), required_evidence=("claude-output",),
            ),
            store=PortableTaskStore(tmp_path), executor_capabilities=(), workspace_root=tmp_path,
        )


def test_adapter_requires_workspace_root(tmp_path: Path):
    with pytest.raises(ValueError, match="workspace_root"):
        adapter = ClaudeCodeAdapter(contract=contract(), store=PortableTaskStore(tmp_path), executor_capabilities=())


def test_adapter_rejects_symlink_scope_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside-scope"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="workspace"):
        make_test_adapter(
            contract=TaskContract(contract_id="FB-CLAUDE-SYMLINK", objective="x", scope=("escape",),
                exclusions=(), risk_class="low", capabilities=(), acceptance_criteria=("adapter-result-recorded",),
                required_evidence=("claude-output",)), store=PortableTaskStore(tmp_path),
            executor_capabilities=(), workspace_root=tmp_path,
        )


def test_dispatch_passes_constrained_cwd_and_timeout(tmp_path: Path):
    calls = []
    def runner(*args, **kwargs):
        calls.append(kwargs)
        return 0, claude_payload("ok", "s1"), ""
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path,
        timeout=42, runner=runner)
    adapter.dispatch("Fix parser", assignee="claude-code")
    assert calls[0] == {"cwd": str(tmp_path.resolve()), "timeout": 42, "env": adapter._safe_env(), "netns_name": "fieldbook-test"}


def test_timeout_persists_failed_result(tmp_path: Path):
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path, runner=runner)
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert result.metadata["reason"] == "execution_timeout"
    assert record.state is LifecycleState.FAILED
    assert "timed out" in record.history[-1]["reason"]


def test_approved_record_can_be_blocked_directly():
    from agentic_fieldbook.lifecycle import CanonicalTaskRecord
    record = CanonicalTaskRecord.create(contract(), task_id="t1")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="planner")
    record.transition(LifecycleState.BLOCKED, actor="adapter", reason="missing evidence")
    assert record.state is LifecycleState.BLOCKED


def test_scope_boundary_rejects_excluded_workspace_changes(tmp_path: Path):
    def runner(*args, **kwargs):
        (tmp_path / "deployment").mkdir()
        (tmp_path / "deployment" / "secret.txt").write_text("must not persist")
        return 0, claude_payload(), ""
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path, runner=runner)
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert result.metadata["reason"] == "scope_violation"
    assert record.state is LifecycleState.BLOCKED


def test_runtime_executor_exception_is_durable_with_provenance(tmp_path: Path):
    def runner(*args, **kwargs):
        raise RuntimeError("executor exploded")
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path, runner=runner)
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert result.metadata["reason"] == "execution_failed"
    assert record.state is LifecycleState.FAILED
    assert record._provenance["error_type"] == "RuntimeError"
    assert "executor exploded" in record._provenance["stderr"]


@pytest.mark.parametrize("payload", [
    {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "implemented", "session_id": "s"},
    {"type": "result", "subtype": "success", "is_error": True, "result": "implemented", "session_id": "s"},
    {"result": "implemented", "session_id": "s"},
])
def test_claude_error_subtypes_and_fabricated_text_fail_closed(tmp_path: Path, payload):
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path,
        runner=lambda *args, **kwargs: (0, json.dumps(payload), ""))
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    assert result.metadata["reason"] == "invalid_output"
    assert adapter.store.load(result.task_id).state is LifecycleState.FAILED


def test_approval_receipt_binds_action_and_issuer(tmp_path: Path):
    high = contract(risk_class="high", capabilities=("prod-write",))
    adapter = make_test_adapter(contract=high, store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",), workspace_root=tmp_path,
        approval_actor="human-1",
        runner=lambda *args, **kwargs: (0, claude_payload(), ""))
    _attach_trusted_receipt(adapter, "Change production")
    result = adapter.dispatch("Change production", assignee="claude-code")
    assert adapter.store.load(result.task_id).state is LifecycleState.REPORTED_COMPLETE
    assert result.metadata["reason"] == "reported_execution"


def test_untrusted_approval_callback_is_rejected_at_construction(tmp_path: Path):
    with pytest.raises(TypeError, match="canonical broker receipt verifier"):
        make_test_adapter(contract=contract(risk_class="high", capabilities=("prod-write",)),
            store=PortableTaskStore(tmp_path), executor_capabilities=("prod-write",),
            workspace_root=tmp_path, approval_verifier=lambda receipt, binding: True)


def test_provenance_redacts_and_bounds_sensitive_output(tmp_path: Path):
    secret = "api_key=super-secret-token"
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path,
        runner=lambda *args, **kwargs: (0, claude_payload(secret), secret))
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    provenance = adapter.store.load(result.task_id)._provenance
    assert "super-secret-token" not in json.dumps(provenance)
    assert len(provenance["stdout_preview"]) <= 4096
    assert "SECRET" not in provenance["environment_keys"]


def test_blocker_and_failure_side_transitions_from_review_stages():
    from agentic_fieldbook.lifecycle import CanonicalTaskRecord
    for stage in (LifecycleState.REPORTED_COMPLETE, LifecycleState.REVIEW, LifecycleState.VERIFICATION):
        record = CanonicalTaskRecord.create(contract(), task_id="side-" + stage.value)
        for state in (LifecycleState.PLANNED, LifecycleState.APPROVED, LifecycleState.EXECUTING):
            record.transition(state, actor="worker", executor_capabilities=("repo-write", "local-test") if state is LifecycleState.EXECUTING else None)
        record.transition(LifecycleState.REPORTED_COMPLETE, actor="worker")
        if stage is LifecycleState.REVIEW:
            record.transition(LifecycleState.REVIEW, actor="reviewer")
        elif stage is LifecycleState.VERIFICATION:
            record.transition(LifecycleState.REVIEW, actor="reviewer")
            record.transition(LifecycleState.VERIFICATION, actor="verifier")
        for target in (LifecycleState.BLOCKED, LifecycleState.FAILED):
            fresh = CanonicalTaskRecord.from_dict(record.to_dict())
            fresh.transition(target, actor="gate", reason=target.value)
            assert fresh.state is target


def test_high_risk_execution_failure_persists_recovery_evidence(tmp_path: Path):
    high = contract(risk_class="high", capabilities=("prod-write",))
    adapter = make_test_adapter(
        contract=high, store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",), workspace_root=tmp_path,
        approval_actor="human-1",
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _attach_trusted_receipt(adapter, "Change production")
    result = adapter.dispatch("Change production", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert record.state is LifecycleState.BLOCKED
    assert any(item["requirement"] == "rollback-evidence" and not item["passed"]
               for item in record.evidence)


def test_metadata_is_allowlisted_and_recursively_bounded(tmp_path: Path):
    nested = {"usage": {"deep": {"deeper": {"secret": "hidden"}}},
              "unexpected": "must not persist", "type": "result"}
    adapter = make_test_adapter(
        contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path,
        runner=lambda *args, **kwargs: (0, claude_payload(**nested), ""),
    )
    result = adapter.dispatch("Fix parser", assignee="claude-code")
    metadata = adapter.store.load(result.task_id)._provenance["execution_metadata"]
    assert set(metadata) <= {"type", "subtype", "is_error", "session_id", "duration_ms",
                              "num_turns", "total_cost_usd", "usage", "model"}
    assert "unexpected" not in json.dumps(metadata)
    assert "hidden" not in json.dumps(metadata)


def test_runner_receives_isolated_home_and_trusted_path(tmp_path: Path):
    observed = {}
    def runner(*args, **kwargs):
        observed.update(kwargs["env"])
        assert Path(kwargs["env"]["HOME"]).is_dir()
        return 0, claude_payload(), ""
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=("repo-write", "local-test"), workspace_root=tmp_path,
        runner=runner)
    adapter.dispatch("Fix parser", assignee="claude-code")
    assert observed["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert observed["HOME"] != str(Path.home())


def test_safe_env_includes_configured_proxy_credentials(tmp_path: Path):
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=(), workspace_root=tmp_path,
        anthropic_base_url="http://192.168.10.252:8318", anthropic_api_key="test-key")
    env = adapter._safe_env(str(tmp_path))
    assert env["ANTHROPIC_BASE_URL"] == "http://192.168.10.252:8318"
    assert env["ANTHROPIC_API_KEY"] == "test-key"
    assert adapter.allowed_egress_host == "192.168.10.252"
    assert adapter.allowed_egress_port == 8318


@pytest.mark.parametrize("kwargs", [
    {"netns_name": "attacker-netns"},
    {"allowed_egress_host": "127.0.0.1"},
    {"allowed_egress_port": 443},
    {"anthropic_base_url": "http://example.com:8318"},
    {"anthropic_base_url": "https://192.168.10.252:8318"},
    {"anthropic_base_url": "http://192.168.10.252:8318/v1"},
])
def test_network_policy_configuration_cannot_drift_from_managed_sandbox(tmp_path: Path, kwargs):
    with pytest.raises(ValueError, match="(managed|exactly match)"):
        make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
                          executor_capabilities=(), workspace_root=tmp_path, **kwargs)


def test_run_process_enters_configured_netns_without_unshare_net(tmp_path: Path, monkeypatch):
    observed = {}
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_bwrap_path", staticmethod(lambda configured=None: "/usr/bin/bwrap"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_executable_path", staticmethod(lambda configured: "/usr/local/bin/claude"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_ip_path", staticmethod(lambda: "/usr/sbin/ip"))

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(subprocess, "run", run)
    ClaudeCodeAdapter._run_process("claude", "--version", cwd=str(tmp_path), timeout=3,
                                   env={"HOME": str(tmp_path)}, netns_name="fieldbook-test")
    assert observed["command"][:4] == ["/usr/sbin/ip", "netns", "exec", "fieldbook-test"]
    assert "--unshare-net" not in observed["command"]
    assert observed["command"][-3:] == ["--", "/usr/local/bin/claude", "--version"]


def test_run_process_fails_closed_without_trusted_ip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_bwrap_path", staticmethod(lambda configured=None: "/usr/bin/bwrap"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_executable_path", staticmethod(lambda configured: "/usr/bin/true"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_ip_path", staticmethod(lambda: None))
    with pytest.raises(RuntimeError, match="trusted ip"):
        ClaudeCodeAdapter._run_process("claude", cwd=str(tmp_path), timeout=1,
                                       env={"HOME": str(tmp_path), "PATH": "/usr/bin"})


def test_bwrap_is_mandatory_and_missing_bwrap_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_bwrap_path", staticmethod(lambda configured=None: None))
    with pytest.raises(RuntimeError, match="bubblewrap is required"):
        ClaudeCodeAdapter._run_process("claude", cwd=str(tmp_path), timeout=1,
                                       env={"HOME": str(tmp_path), "PATH": "/usr/bin"})


def test_high_risk_sandbox_failure_invokes_rollback_handling(tmp_path: Path):
    high = contract(risk_class="high", capabilities=("prod-write",))
    rollback_marker = tmp_path.parent / (tmp_path.name + "-rollback-called")

    def rollback(record, message):
        rollback_marker.write_text(message)
        return True

    adapter = make_test_adapter(contract=high, store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",), workspace_root=tmp_path,
        approval_actor="human-1", rollback_callback=rollback)
    _attach_trusted_receipt(adapter, "Change production")
    result = adapter.dispatch("Change production", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert result.metadata["reason"] == "execution_failed"
    assert record.state is LifecycleState.FAILED
    assert rollback_marker.exists()
    assert any(item["requirement"] == "rollback-evidence" and item["passed"]
               for item in record.evidence)



def test_high_risk_scope_failure_records_independent_snapshot_restoration(tmp_path: Path):
    high = contract(risk_class="high", capabilities=("prod-write",))
    rollback_marker = tmp_path.parent / (tmp_path.name + "-rollback-called")

    def runner(*args, **kwargs):
        (tmp_path / "deployment").mkdir()
        (tmp_path / "deployment" / "secret.txt").write_text("temporary")
        return 0, claude_payload(), ""

    def rollback(record, message):
        (tmp_path / "deployment" / "secret.txt").unlink()
        (tmp_path / "deployment").rmdir()
        rollback_marker.write_text(message)
        return True

    adapter = make_test_adapter(contract=high, store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",), workspace_root=tmp_path,
        approval_actor="human-1", rollback_callback=rollback, runner=runner)
    _attach_trusted_receipt(adapter, "Change production")
    result = adapter.dispatch("Change production", assignee="claude-code")
    record = adapter.store.load(result.task_id)
    assert result.metadata["reason"] == "scope_violation"
    assert record.state is LifecycleState.BLOCKED
    assert rollback_marker.exists()
    assert any(item["requirement"] == "rollback-evidence" and item["passed"]
               for item in record.evidence)


def test_production_adapter_has_no_runner_injection_factory(tmp_path: Path):
    assert not hasattr(ClaudeCodeAdapter, "for_testing")
    with pytest.raises(TypeError):
        ClaudeCodeAdapter(contract=contract(), store=PortableTaskStore(tmp_path),
                          executor_capabilities=(), workspace_root=tmp_path,
                          _test_runner=lambda *a, **k: (0, "", ""))


def test_snapshot_contains_portable_mode_and_ownership_metadata(tmp_path: Path):
    (tmp_path / "agentic_fieldbook").mkdir()
    (tmp_path / "agentic_fieldbook" / "x.py").write_text("x")
    adapter = make_test_adapter(contract=contract(), store=PortableTaskStore(tmp_path),
        executor_capabilities=(), workspace_root=tmp_path)
    snapshot = adapter._snapshot()
    entry = snapshot["agentic_fieldbook/x.py"]
    assert {"mode", "uid", "gid", "type", "sha256"} <= set(entry)
    assert snapshot["agentic_fieldbook/"]["type"] == "directory"


def test_bwrap_command_clears_environment_and_rejects_symlink_launcher(tmp_path: Path, monkeypatch):
    launcher = tmp_path / "claude"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    link = tmp_path / "link"
    link.symlink_to(launcher)
    assert ClaudeCodeAdapter._trusted_executable_path(str(link)) is None
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_bwrap_path", staticmethod(lambda configured=None: "/usr/bin/bwrap"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_executable_path", staticmethod(lambda configured: "/usr/bin/true"))
    monkeypatch.setattr(ClaudeCodeAdapter, "_trusted_ip_path", staticmethod(lambda: "/usr/sbin/ip"))
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: seen.update(command=command) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    ClaudeCodeAdapter._run_process("claude", cwd=str(tmp_path), timeout=1,
                                   env={"HOME": str(tmp_path), "PATH": "/usr/bin", "LANG": "C", "LC_ALL": "C"})
    assert "--clearenv" in seen["command"]


def test_rollback_timeout_is_killable_and_cannot_mutate_after_return(tmp_path: Path):
    high = contract(risk_class="high", capabilities=("prod-write",))
    late_marker = tmp_path / "late-rollback-mutation"

    def rollback(record, message):
        import time
        time.sleep(0.25)
        late_marker.write_text("must never be written after timeout")
        return True

    adapter = make_test_adapter(
        contract=high, store=PortableTaskStore(tmp_path),
        executor_capabilities=("prod-write",), workspace_root=tmp_path,
        approval_actor="human-1", rollback_callback=rollback, rollback_timeout=0.03,
    )
    _attach_trusted_receipt(adapter, "Change production")
    record = adapter._new_record("rollback-timeout", "Change production")
    ok, evidence = adapter._rollback_evidence(record, "rollback test")
    assert not ok
    assert evidence["result"] == "rollback timeout"
    import time
    time.sleep(0.35)
    assert not late_marker.exists()
