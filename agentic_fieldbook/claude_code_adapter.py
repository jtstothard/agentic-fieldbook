"""Claude Code executor adapter bound to the Fieldbook lifecycle boundary."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re

import multiprocessing
import queue
import subprocess
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapter_contract import AdapterCapability, DispatchAdapter, DispatchResult, StatusResult, TaskStatus
from .approval_gate import ActionPackage, ApprovalReceipt
from .lifecycle import CanonicalTaskRecord, LifecycleState, TaskContract
from .contract import canonical_contract_projection
from .receipt import canonical_digest
from .broker import verify_approval_receipt, VerificationResult
from .storage import PortableTaskStore

Runner = Callable[..., tuple[int, str, str]]
_MAX_CAPTURE = 4096
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|apiKey|access[_-]?token|accessToken|client[_-]?secret|clientSecret|token|secret|password|credential|private[_-]?key|privateKey)")
_SECRET_VALUE = re.compile(r"(?i)(?:bearer\s+|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,})")
_TRUSTED_PATH = "/usr/local/bin:/usr/bin:/bin"
_METADATA_KEYS = frozenset({"type", "subtype", "is_error", "session_id", "duration_ms", "num_turns", "total_cost_usd", "usage", "model"})
_MAX_METADATA_TOTAL = 8192


def _rollback_worker(callback: Callable[..., Any], record: CanonicalTaskRecord,
                    message: str, result_queue: Any) -> None:
    """Run rollback outside the parent so timeout can be hard-terminated."""
    try:
        result_queue.put((True, repr(callback(record, message))))
    except BaseException as exc:
        result_queue.put((False, repr(exc)))


class ClaudeCodeAdapter(DispatchAdapter):
    """Run Claude Code with a bounded workspace and execution-only contract.

    A prompt, sanitized environment, and before/after workspace snapshots are not
    security boundaries. Snapshots are supplemental evidence only: they include
    portable file type, mode, uid/gid, and content metadata for durable changes, but
    cannot observe transient escape, writes outside the workspace, absolute-path
    writes, or a symlink race that is created and removed before inspection.
    Bubblewrap is the authoritative confinement boundary; if it is unavailable or
    its trusted executable checks fail, execution fails closed.
    """

    def __init__(self, *, contract: TaskContract, store: PortableTaskStore,
                 executor_capabilities: tuple[str, ...], approval_actor: str | None = None,
                 approval_receipt: ApprovalReceipt | None = None,
                 approval_verifier: Callable[..., Any] | None = None,
                 broker_verifier: Callable[..., Any] | None = None,
                 broker_context: dict[str, Any] | None = None,
                 rollback_callback: Callable[..., Any] | None = None,
                 rollback_timeout: float = 30.0,
                 claude_command: str = "claude", workspace_root: Path | str | None = None,
                 timeout: float = 300.0) -> None:
        if workspace_root is None:
            raise ValueError("workspace_root is required")
        if timeout <= 0 or rollback_timeout <= 0:
            raise ValueError("timeouts must be positive")
        self.contract = contract
        self.store = store
        self.executor_capabilities = executor_capabilities
        self.approval_actor = approval_actor
        self.approval_receipt = approval_receipt
        supplied_verifiers = [item for item in (approval_verifier, broker_verifier) if item is not None]
        if supplied_verifiers and any(item is not verify_approval_receipt for item in supplied_verifiers):
            raise TypeError("the Claude adapter only accepts the canonical broker receipt verifier")
        if len(supplied_verifiers) == 2 and supplied_verifiers[0] is not supplied_verifiers[1]:
            raise TypeError("approval verifier arguments must identify the same canonical broker verifier")
        self.approval_verifier = supplied_verifiers[0] if supplied_verifiers else verify_approval_receipt
        self.broker_context = dict(broker_context or {})
        self.rollback_callback = rollback_callback
        self.rollback_timeout = rollback_timeout
        self.claude_command = claude_command
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        self.timeout = timeout
        self._validate_scope()
        self._runner = self._run_process

    def _validate_scope(self) -> None:
        for item in (*self.contract.scope, *self.contract.exclusions):
            candidate = self.workspace_root / item
            if Path(item).is_absolute() or "\x00" in item:
                raise ValueError("contract scope/exclusions must remain within the workspace")
            path = candidate
            current = self.workspace_root
            for part in Path(item).parts:
                current = current / part
                try:
                    if current.is_symlink():
                        raise ValueError("workspace scope/exclusions cannot contain symlinks")
                except OSError as exc:
                    raise ValueError("contract scope/exclusions cannot be inspected") from exc
            path = candidate.resolve(strict=False)
            try:
                path.relative_to(self.workspace_root)
            except ValueError as exc:
                raise ValueError("contract scope/exclusions must remain within the workspace") from exc

    @staticmethod
    def _run_process(*args: str, cwd: str | None = None, timeout: float = 300.0,
                     env: dict[str, str] | None = None) -> tuple[int, str, str]:
        """Run Claude inside bubblewrap; never fall back to an unconfined child."""
        bwrap = ClaudeCodeAdapter._trusted_bwrap_path()
        if not bwrap or not cwd or not env:
            raise RuntimeError("bubblewrap is required for Claude execution; refusing unconfined subprocess")
        home = env.get("HOME")
        if not home or not Path(home).is_dir():
            raise RuntimeError("isolated HOME is required for sandboxed Claude execution")
        executable = ClaudeCodeAdapter._trusted_executable_path(args[0]) if args else None
        if executable is None:
            raise RuntimeError("Claude launcher must be a trusted, non-symlink executable")
        command = [bwrap, "--clearenv", "--die-with-parent", "--unshare-net", "--new-session",
                   "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                   "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
                   "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
                   "--ro-bind", "/etc", "/etc", "--bind", cwd, cwd,
                   "--bind", home, home, "--chdir", cwd]
        for key, value in env.items():
            command += ["--setenv", key, value]
        command += ["--", executable] + list(args[1:])
        completed = subprocess.run(command, cwd=cwd, timeout=timeout, env=None,
                                   text=True, capture_output=True, check=False)
        return completed.returncode, completed.stdout, completed.stderr

    @staticmethod
    def _trusted_bwrap_path(configured: str | None = None) -> str | None:
        """Resolve only an absolute, root-owned, non-writable bwrap binary."""
        candidate = configured or "/usr/bin/bwrap"
        path = Path(candidate)
        try:
            if path.is_symlink():
                return None
            stat_result = path.stat()
        except OSError:
            return None
        import stat
        if (not path.is_absolute() or not stat.S_ISREG(stat_result.st_mode)
                or stat_result.st_uid != 0
                or stat_result.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            return None
        if not (stat_result.st_mode & stat.S_IXUSR):
            return None
        return str(path)

    @staticmethod
    def _trusted_executable_path(configured: str) -> str | None:
        """Resolve a launcher only when its directory entry is not a symlink."""
        import stat
        path = Path(configured)
        if not path.is_absolute():
            for directory in _TRUSTED_PATH.split(":"):
                candidate = Path(directory) / configured
                if candidate.exists():
                    path = candidate
                    break
        try:
            if not path.is_absolute() or path.is_symlink():
                return None
            info = path.stat()
        except OSError:
            return None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or not info.st_mode & stat.S_IXUSR):
            return None
        return str(path)

    def get_capabilities(self) -> set[AdapterCapability]:
        return {AdapterCapability.SYNC_DISPATCH, AdapterCapability.TASK_ID_PERSISTENCE,
                AdapterCapability.RESULT_PERSISTENCE, AdapterCapability.STATUS_TRACKING,
                AdapterCapability.FAILURE_STATE_MANAGEMENT}

    def _contract_digest(self) -> str:
        return canonical_digest(self.contract.to_dict())

    def _approval_contract_digest(self, goal: str, unsigned: ActionPackage) -> str:
        """Compute contract_digest using the same projection as the broker.

        Uses canonical_contract_projection to ensure alignment with broker's
        verification logic at broker.py:526.
        """
        projection = dict(self.contract.to_dict())
        projection.update({key: value for key, value in unsigned.as_mapping().items()
                           if key != "contract_digest"})
        return canonical_digest(canonical_contract_projection(projection))

    def _action_binding(self, goal: str) -> dict[str, Any]:
        capability = self.contract.capabilities[0] if self.contract.capabilities else "claude-code"
        unsigned = ActionPackage(contract_digest="", target={"workspace": str(self.workspace_root)},
                                capability=capability,
                                parameters={"goal": goal, "scope": list(self.contract.scope),
                                            "exclusions": list(self.contract.exclusions)},
                                lease_ttl=300, operation_limit=1,
                                verification_method="claude-structured-output",
                                rollback={"required": self.contract.risk_class == "high"},
                                abort_conditions=["scope-violation", "invalid-output"],
                                approval_expires_at="2099-01-01T00:00:00Z")
        package = replace(unsigned, contract_digest=self._approval_contract_digest(goal, unsigned))
        return {**package.as_mapping(), "action_digest": package.digest()}

    def _validated_approval(self, goal: str) -> tuple[bool, str | None, str | None]:
        receipt = self.approval_receipt
        if receipt is None:
            return False, "No validated approval receipt is available", None
        if not isinstance(receipt, ApprovalReceipt) or receipt.receipt_version != "1":
            return False, "Malformed approval receipt", None
        binding = self._action_binding(goal)
        digest = binding["action_digest"]
        if receipt.action_digest != digest or receipt.payload.get("action_digest") != digest:
            return False, "Approval receipt is not bound to this contract/action", None
        for key in ("receipt_version", "receipt_id", "approval_request_id", "action_digest",
                    "contract_digest", "target", "capability", "parameters", "issuer", "decision",
                    "issued_at", "valid_until", "audience", "nonce", "signature"):
            if key not in receipt.payload:
                return False, f"Approval receipt missing {key}", None
        if (receipt.payload["contract_digest"] != binding["contract_digest"] or
                receipt.payload["target"] != binding["target"] or
                receipt.payload["action_digest"] != digest or
                receipt.payload["decision"] != "approved"):
            return False, "Approval receipt action fields are not bound", None
        def plain(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: plain(member) for key, member in value.items()}
            if hasattr(value, "items"):
                return {key: plain(member) for key, member in value.items()}
            if isinstance(value, (tuple, list)):
                return [plain(member) for member in value]
            return value
        if plain(receipt.payload["capability"]) != binding["capability"] or plain(receipt.payload["parameters"]) != binding["parameters"]:
            return False, "Approval receipt capability or parameters mismatch", None
        issuer = receipt.payload["issuer"]
        if not isinstance(issuer, str) or not issuer.strip():
            return False, "Approval receipt issuer binding invalid", None
        if self.approval_actor is not None and self.approval_actor != issuer:
            return False, "Approval receipt issuer does not match approval_actor", None
        try:
            issued = datetime.fromisoformat(str(receipt.payload["issued_at"]).replace("Z", "+00:00"))
            valid_until = datetime.fromisoformat(str(receipt.payload["valid_until"]).replace("Z", "+00:00"))
            if issued.tzinfo is None or valid_until.tzinfo is None or valid_until <= issued:
                return False, "Approval receipt validity window is invalid", None
        except (TypeError, ValueError):
            return False, "Approval receipt timestamps are invalid", None
        signature = receipt.payload["signature"]
        if not hasattr(signature, "items") or not all(
                isinstance(signature.get(key), str) and signature.get(key).strip()
                for key in ("algorithm", "key_id", "value")):
            return False, "Approval receipt is not authenticated", None
        if self.approval_verifier is None or self.approval_verifier is not verify_approval_receipt:
            return False, "The real broker receipt verifier is required", None
        receipt_mapping = plain(receipt.payload)
        receipt_mapping.update({
            "receipt_version": receipt.receipt_version,
            "approval_request_id": receipt.approval_request_id,
            "action_digest": receipt.action_digest,
            "receipt_id": receipt.receipt_id,
        })
        try:
            required_context = ("contract", "broker_audience", "requester", "keystore", "policy", "store", "clock")
            if any(key not in self.broker_context for key in required_context):
                return False, "Trusted broker verification context is incomplete", None
            # This is deliberately a provider/broker seam.  The adapter does
            # not verify signatures locally or treat receipt fields as proof.
            broker_contract = dict(self.contract.to_dict())
            supplied_contract = self.broker_context["contract"]
            if not isinstance(supplied_contract, Mapping):
                return False, "Trusted broker contract context is malformed", None
            for key in ("target", "capability", "parameters", "lease_ttl", "operation_limit",
                        "verification_method", "rollback", "abort_conditions", "approval_expires_at"):
                if key in supplied_contract:
                    broker_contract[key] = supplied_contract[key]
            broker_contract["contract_digest"] = supplied_contract.get("contract_digest")
            verified = self.approval_verifier(
                receipt_mapping, broker_contract,
                self.broker_context["broker_audience"], self.broker_context["requester"],
                self.broker_context["keystore"], self.broker_context["policy"],
                self.broker_context["store"], self.broker_context["clock"])
            if not isinstance(verified, VerificationResult):
                return False, "Broker verifier returned an invalid result", None
            verified = verified.success
        except Exception:
            verified = False
        if verified is not True:
            return False, "Broker/provider receipt verification failed", None
        return True, None, issuer

    def _new_record(self, task_id: str, goal: str) -> CanonicalTaskRecord:
        record = CanonicalTaskRecord.create(self.contract, task_id=task_id)
        record.transition(LifecycleState.PLANNED, actor="fieldbook-planner")
        approved, reason, issuer = self._validated_approval(goal)
        needs_approval = self.contract.risk_class == "high" or record._governance.requires_human_approval()
        if needs_approval:
            if not approved:
                return record
            # Only the successful canonical broker verification may establish
            # the binding used by the lifecycle execution gate.
            record.bind_approval_receipt(
                receipt_id=self.approval_receipt.receipt_id,
                contract_digest=self.approval_receipt.payload["contract_digest"],
                epoch=record.approval_epoch,
                recovery_attempt=record.recovery_attempt,
            )
            record.transition(LifecycleState.APPROVED, actor=issuer or "approval-gate", reason="validated approval receipt")
        else:
            record.transition(LifecycleState.APPROVED, actor="fieldbook-planner")
        return record

    @classmethod
    def _sanitize_prompt_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Keep the task artifact useful without persisting prompt secrets."""
        def clean(value: Any, depth: int = 0) -> Any:
            if depth > 4:
                return "[TRUNCATED]"
            if isinstance(value, str):
                return cls._safe_text(value)[:512]
            if value is None or type(value) in (bool, int, float):
                return value
            if isinstance(value, Mapping):
                return {str(key)[:80]: clean(member, depth + 1)
                        for key, member in list(value.items())[:32]
                        if not _SECRET_KEY.search(str(key))}
            if isinstance(value, (list, tuple)):
                return [clean(item, depth + 1) for item in list(value)[:32]]
            return cls._safe_text(value)[:512]

        result = clean(payload)
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
        if len(encoded) > _MAX_METADATA_TOTAL:
            return {"artifact_digest": hashlib.sha256(encoded.encode()).hexdigest(),
                    "artifact_preview": cls._safe_text(encoded)[:2048]}
        return result

    def _prompt(self, goal: str) -> str:
        safe_contract = self._sanitize_prompt_payload(self.contract.to_dict())
        return ("Execute this Fieldbook task using the contract artifact below. This is an "
                "artifact-only handoff; do not assume or request prior transcripts. Stay within "
                "scope and exclusions, run declared checks, and report structured execution metadata. "
                "Do not perform review or verification.\n\n"
                f"Goal: {self._safe_text(goal)}\nContract artifact:\n{json.dumps(safe_contract, sort_keys=True)}")

    @staticmethod
    def _safe_text(value: Any) -> str:
        text = str(value or "")
        text = _SECRET_VALUE.sub("[REDACTED]", text)
        text = re.sub(r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|credential|private[_-]?key)[\"']?\s*[:=]\s*)([\"'][^\"']*[\"']|[^\s,;}]+)",
                      r"\1[REDACTED]", text)
        return text[:_MAX_CAPTURE]

    def _safe_env(self, home: str | None = None) -> dict[str, str]:
        if home is None:
            return getattr(self, "_last_safe_env", {"PATH": _TRUSTED_PATH, "HOME": "", "LANG": "C", "LC_ALL": "C"})
        env = {"PATH": _TRUSTED_PATH, "HOME": home, "LANG": "C", "LC_ALL": "C"}
        self._last_safe_env = env
        return env

    def _snapshot(self) -> dict[str, Any]:
        """Capture supplemental durable evidence, not an enforcement boundary."""
        result: dict[str, Any] = {}
        import stat

        def walk(directory: Path) -> None:
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise ValueError(f"workspace cannot be inspected: {directory}") from exc
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(self.workspace_root).as_posix()
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                    mode = entry_stat.st_mode
                except OSError as exc:
                    raise ValueError(f"workspace entry cannot be inspected: {relative}") from exc
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError(f"workspace contains symlink or special entry: {relative}")
                metadata: dict[str, Any] = {"mode": stat.S_IMODE(mode), "uid": entry_stat.st_uid,
                                             "gid": entry_stat.st_gid,
                                             "type": "directory" if stat.S_ISDIR(mode) else "file"}
                if stat.S_ISDIR(mode):
                    result[relative + "/"] = metadata
                    walk(path)
                else:
                    metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    result[relative] = metadata

        walk(self.workspace_root)
        return result

    def _scope_violations(self, before: dict[str, str], after: dict[str, str]) -> list[str]:
        changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        violations = []
        for name in sorted(changed):
            in_scope = any(name == scope or name.startswith(scope.rstrip("/") + "/")
                           for scope in self.contract.scope)
            excluded = any(fnmatch.fnmatch(name, pattern) or name == pattern or
                           name.startswith(pattern.rstrip("/") + "/") for pattern in self.contract.exclusions)
            if not in_scope or excluded:
                violations.append(name)
        return violations

    @staticmethod
    def _redact_args(args: tuple[str, ...]) -> list[Any]:
        redacted: list[Any] = []
        for index, arg in enumerate(args):
            text = str(arg)
            if index == 2 and text:
                redacted.append({"digest": hashlib.sha256(text.encode()).hexdigest(),
                                 "preview": ClaudeCodeAdapter._safe_text(text)[:128], "length": len(text)})
            else:
                redacted.append(text[:256])
        return redacted

    def _provenance(self, args: tuple[str, ...], *, session_id: str | None, returncode: int | None,
                    stderr: str, stdout: str, started: str, finished: str,
                    execution_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"command": self.claude_command, "args": self._redact_args(args), "cwd": str(self.workspace_root),
                "exit_code": returncode, "stderr": self._safe_text(stderr),
                "stdout_digest": hashlib.sha256(stdout.encode()).hexdigest(),
                "stdout_preview": self._safe_text(stdout), "started_at": started, "finished_at": finished,
                "session_id": session_id, "contract_identity": self.contract.contract_id,
                "contract_digest": self._contract_digest(), "capability_snapshot": list(self.executor_capabilities),
                "environment_keys": ["PATH", "HOME", "LANG", "LC_ALL"],
                "execution_metadata": self._sanitize_metadata(execution_metadata or {})}

    @classmethod
    def _sanitize_metadata(cls, payload: dict[str, Any]) -> dict[str, Any]:
        def clean(value: Any, depth: int = 0) -> Any:
            if depth > 4:
                return "[TRUNCATED]"
            if isinstance(value, str):
                return cls._safe_text(value)
            if value is None or type(value) in (bool, int, float):
                return value
            if isinstance(value, dict):
                return {str(k)[:80]: clean(v, depth + 1) for k, v in list(value.items())[:32]
                        if not _SECRET_KEY.search(str(k))}
            if isinstance(value, (list, tuple)):
                return [clean(item, depth + 1) for item in list(value)[:32]]
            return cls._safe_text(value)
        selected = {key: clean(payload[key]) for key in _METADATA_KEYS if key in payload}
        encoded = json.dumps(selected, sort_keys=True, separators=(",", ":"))
        if len(encoded) > _MAX_METADATA_TOTAL:
            return {"metadata_digest": hashlib.sha256(encoded.encode()).hexdigest(),
                    "metadata_preview": cls._safe_text(encoded)[:1024]}
        return selected

    def _rollback_evidence(self, record: CanonicalTaskRecord, message: str,
                           expected_snapshot: dict[str, str] | None = None) -> tuple[bool, dict[str, Any]]:
        requirement = next((item for item in self.contract.required_evidence
                            if any(word in item.lower() for word in ("rollback", "revert", "backout", "recovery"))), None)
        if requirement is None:
            return False, {"requirement": "rollback-evidence", "claim": "Rollback requirement unresolved",
                           "tool": "claude-code-adapter", "result": "No declared rollback requirement", "passed": False}
        if self.rollback_callback is None:
            return False, {"requirement": requirement, "claim": "Rollback was not executed",
                           "tool": "claude-code-adapter", "result": "No rollback/abort callback was configured", "passed": False}
        # Resolve an explicit context so the worker remains independently
        # killable by the parent when the rollback deadline expires.
        try:
            context = multiprocessing.get_context("fork")
        except ValueError as exc:
            raise RuntimeError("rollback worker requires a supported process context") from exc
        result_queue = context.Queue(maxsize=1)
        worker = context.Process(target=_rollback_worker,
                                 args=(self.rollback_callback, record, message, result_queue))
        worker.start()
        worker.join(timeout=self.rollback_timeout)
        timed_out = worker.is_alive()
        if timed_out:
            worker.terminate()
            worker.join(timeout=min(1.0, self.rollback_timeout))
            if worker.is_alive():
                worker.kill()
                worker.join()
            result_queue.close()
            result_queue.join_thread()
            return False, {"requirement": requirement, "claim": "Rollback worker timed out and was terminated",
                           "tool": "killable-rollback-worker", "result": "rollback timeout", "passed": False}
        try:
            ok, callback_result = result_queue.get(timeout=1.0)
        except queue.Empty:
            ok, callback_result = False, "rollback worker exited without evidence"
        finally:
            result_queue.close()
            result_queue.join_thread()
        if not ok:
            return False, {"requirement": requirement, "claim": "Rollback callback failed",
                           "tool": "killable-rollback-worker", "result": callback_result, "passed": False}
        # A callback's result is only a request to inspect state; it is never
        # independent proof that rollback happened.
        restored = False
        if expected_snapshot is not None:
            try:
                restored = self._snapshot() == expected_snapshot
            except Exception:
                restored = False
        return restored, {"requirement": requirement,
                          "claim": "Bounded rollback/abort independently verified",
                          "tool": "workspace-snapshot-verifier", "callback_result": callback_result,
                          "result": "workspace restored" if restored else "workspace restoration not verified",
                          "passed": restored}

    def _save_failure(self, record: CanonicalTaskRecord, task_id: str, reason: str, message: str,
                      *, expected_snapshot: dict[str, str] | None = None) -> DispatchResult:
        target = LifecycleState.BLOCKED if reason in {"approval_unavailable", "scope_violation", "governance_blocked", "capability_mismatch"} else LifecycleState.FAILED
        evidence: list[dict[str, Any]] = []
        if self.contract.risk_class == "high" and record.state is LifecycleState.EXECUTING:
            rollback_ok, rollback_item = self._rollback_evidence(record, message, expected_snapshot)
            evidence.append(rollback_item)
            if not rollback_ok:
                target = LifecycleState.BLOCKED
        elif self.contract.risk_class == "high" and target is LifecycleState.BLOCKED:
            evidence.append({"requirement": "rollback-evidence", "claim": "Rollback was not independently verifiable",
                             "tool": "claude-code-adapter", "result": "no executed workspace state to restore",
                             "passed": False})
        record.transition(target, actor="claude-code", reason=self._safe_text(message), evidence=evidence)
        self.store.save(record)
        return DispatchResult(False, task_id, {"backend": "claude-code", "reason": reason}, self._safe_text(message))

    def dispatch(self, goal: str, *, assignee: str | None) -> DispatchResult:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        task_id = f"claude-{uuid.uuid4().hex}"
        try:
            record = self._new_record(task_id, goal)
        except Exception as exc:
            record = CanonicalTaskRecord.create(self.contract, task_id=task_id)
            record.transition(LifecycleState.PLANNED, actor="fieldbook-planner")
            record._provenance = {"error_type": type(exc).__name__, "error": self._safe_text(exc)}
            self.store.save(record)
            return self._save_failure(record, task_id, "governance_blocked", str(exc))
        self.store.save(record)
        if record.state is not LifecycleState.APPROVED:
            return self._save_failure(record, task_id, "approval_unavailable", "Validated approval receipt required")
        try:
            if (self.contract.risk_class == "high" or record._governance.requires_human_approval()):
                receipt = self.approval_receipt
                if (receipt is None or not record.approval_receipt_is_current(
                        receipt_id=receipt.receipt_id,
                        contract_digest=receipt.payload.get("contract_digest", ""))):
                    return self._save_failure(record, task_id, "approval_unavailable",
                                              "approval binding is stale for this recovery attempt")
            record.transition(LifecycleState.EXECUTING, actor="claude-code", executor_capabilities=self.executor_capabilities)
        except Exception as exc:
            return self._save_failure(record, task_id, "capability_mismatch" if "capabilities" in str(exc).lower() else "governance_blocked", str(exc))
        self.store.save(record)
        args = (self.claude_command, "-p", self._prompt(goal), "--output-format", "json", "--max-turns", "10")
        started = datetime.now().astimezone().isoformat()
        try:
            before = self._snapshot()
        except Exception as exc:
            record._provenance = self._provenance(args, session_id=None, started=started,
                                                   finished=datetime.now().astimezone().isoformat(),
                                                   stderr=str(exc), stdout="", returncode=None)
            return self._save_failure(record, task_id, "scope_violation", str(exc))
        try:
            with tempfile.TemporaryDirectory(prefix="fieldbook-home-") as isolated_home:
                env = self._safe_env(isolated_home)
                returncode, stdout, stderr = self._runner(*args, cwd=str(self.workspace_root), timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            finished = datetime.now().astimezone().isoformat()
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=str(exc), stdout="", returncode=None)
            return self._save_failure(record, task_id, "execution_timeout", str(exc), expected_snapshot=before)
        except Exception as exc:
            finished = datetime.now().astimezone().isoformat()
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=str(exc), stdout="", returncode=None)
            record._provenance["error_type"] = type(exc).__name__
            return self._save_failure(record, task_id, "execution_failed", str(exc), expected_snapshot=before)
        finished = datetime.now().astimezone().isoformat()
        try:
            after = self._snapshot()
        except Exception as exc:
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=stderr, stdout=stdout, returncode=returncode,
                                                   execution_metadata={"snapshot_error": str(exc)})
            return self._save_failure(record, task_id, "scope_violation", str(exc), expected_snapshot=before)
        violations = self._scope_violations(before, after)
        if violations:
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=stderr, stdout=stdout, returncode=returncode,
                                                   execution_metadata={"scope_violations": violations})
            return self._save_failure(record, task_id, "scope_violation", "changed files outside contract boundary: " + ", ".join(violations), expected_snapshot=before)
        if returncode != 0:
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=stderr, stdout=stdout, returncode=returncode)
            return self._save_failure(record, task_id, "execution_failed", "Claude exited unsuccessfully", expected_snapshot=before)
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise ValueError("Claude output must be an object")
            required = ("type", "subtype", "is_error", "result", "session_id")
            if any(key not in payload for key in required):
                raise ValueError("Claude output lacks structured execution metadata")
            if payload["type"] != "result" or payload["subtype"] != "success" or payload["is_error"] is not False:
                raise ValueError("Claude reported a non-success execution status")
            if not isinstance(payload["result"], str) or not payload["result"].strip() or not isinstance(payload["session_id"], str):
                raise ValueError("Claude result/session_id types are invalid")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            record._provenance = self._provenance(args, session_id=None, started=started, finished=finished,
                                                   stderr=stderr, stdout=stdout, returncode=returncode)
            return self._save_failure(record, task_id, "invalid_output", str(exc), expected_snapshot=before)
        metadata = self._sanitize_metadata(payload)
        record._provenance = self._provenance(args, session_id=payload["session_id"], started=started, finished=finished,
                                               stderr=stderr, stdout=stdout, returncode=returncode,
                                               execution_metadata=metadata)
        record.transition(LifecycleState.REPORTED_COMPLETE, actor="claude-code", evidence=[{
            "requirement": "claude-output", "claim": "Claude Code structured execution succeeded",
            "tool": "claude", "result": json.dumps(metadata, sort_keys=True), "passed": True}])
        self.store.save(record)
        return DispatchResult(False, task_id, {"backend": "claude-code", "assignee": assignee,
            "execution_metadata": metadata, "reason": "reported_execution"},
            "Claude Code execution reported; review and verification remain required")

    def get_status(self, task_id: str) -> StatusResult:
        record = self.store.load(task_id)
        mapping = {LifecycleState.PROPOSED: TaskStatus.READY, LifecycleState.PLANNED: TaskStatus.READY,
                   LifecycleState.APPROVED: TaskStatus.READY, LifecycleState.EXECUTING: TaskStatus.RUNNING,
                   LifecycleState.REVIEW: TaskStatus.RUNNING, LifecycleState.VERIFICATION: TaskStatus.RUNNING,
                   LifecycleState.VERIFIED: TaskStatus.DONE, LifecycleState.REPORTED_COMPLETE: TaskStatus.BLOCKED,
                   LifecycleState.BLOCKED: TaskStatus.BLOCKED, LifecycleState.FAILED: TaskStatus.BLOCKED,
                   LifecycleState.CANCELLED: TaskStatus.BLOCKED, LifecycleState.SUPERSEDED: TaskStatus.BLOCKED}
        return StatusResult(True, mapping[record.state], {"backend": "claude-code", "state": record.state.value})


__all__ = ["ClaudeCodeAdapter"]
