"""Router-to-Fieldbook HITL bridge primitives and durable resolution store.

This module is intentionally transport-neutral.  Router integrations should use
``RouterTask`` and ``BridgeResult`` rather than passing lifecycle objects across
the process/plugin boundary.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .gate_evaluator import GateDisposition, GateLearningStore, GateTask, evaluate_gate
from .governance import detect_always_ask_capabilities
from .light_gate import LightGateDecision
from .receipt import canonical_digest

_LOG = logging.getLogger(__name__)
SCHEMA_VERSION = 1


class BridgeStatus(str, Enum):
    PROCEED = "proceed"
    ABORT = "abort"
    PENDING = "pending"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class RouterTask:
    """Immutable JSON-shaped projection of a router task."""
    task_id: str
    objective: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    risk_class: str
    capabilities: tuple[str, ...]
    action_class: str
    fork_description: str = ""
    recommended_option: str = ""
    options: tuple[str, ...] = ()
    trade_off: str = ""
    revert_path: str = ""
    idempotency_key: str = ""
    contract_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("task_id", "objective", "action_class"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("scope", "exclusions", "capabilities", "options"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
                raise TypeError(f"{name} must be a tuple of strings")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RouterTask":
        """Copy a mapping into a boundary-safe projection; never retain its lists."""
        if not isinstance(data, Mapping):
            raise TypeError("task must be a mapping")
        values = dict(data)
        for name in ("scope", "exclusions", "capabilities", "options"):
            value = values.get(name, ())
            if isinstance(value, str) or not isinstance(value, Sequence):
                raise TypeError(f"{name} must be a sequence of strings")
            values[name] = tuple(value)
        task = cls(**values)
        if not task.contract_digest:
            object.__setattr__(task, "contract_digest", task.compute_contract_digest())
        return task

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "objective": self.objective,
                "scope": list(self.scope), "exclusions": list(self.exclusions),
                "risk_class": self.risk_class, "capabilities": list(self.capabilities),
                "action_class": self.action_class, "fork_description": self.fork_description,
                "recommended_option": self.recommended_option, "options": list(self.options),
                "trade_off": self.trade_off, "revert_path": self.revert_path,
                "idempotency_key": self.idempotency_key, "contract_digest": self.contract_digest}

    def compute_contract_digest(self) -> str:
        data = self.to_dict()
        data.pop("contract_digest", None)
        return canonical_digest(data)


@dataclass(frozen=True)
class BridgeResult:
    status: BridgeStatus | str
    task_id: str
    gate_id: str | None = None
    reason: str = ""
    disposition: str | None = None
    outcome: str | None = None
    degradation_code: str | None = None
    contract_digest: str | None = None

    def __post_init__(self) -> None:
        status = self.status if isinstance(self.status, BridgeStatus) else BridgeStatus(self.status)
        object.__setattr__(self, "status", status)
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {k: v.value if isinstance(v, Enum) else v for k, v in self.__dict__.items() if v is not None}


class GateBridge(Protocol):
    def evaluate_and_maybe_gate(self, task: RouterTask) -> BridgeResult: ...
    def process_reply(self, message: Any) -> BridgeResult | None: ...


class LearningStore(GateLearningStore, Protocol):
    def record_resolution(self, action_class: str, fork_signature: str, outcome: str,
                          chosen_option: str, actor: str, task_id: str,
                          contract_digest: str, timestamp: str | None = None) -> None: ...


class SQLiteLearningStore:
    """Append-only SQLite store implementing the evaluator's learning protocol."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=10000;")
        self._migrate()

    def _migrate(self) -> None:
        self._db.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        current = self._db.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        if current is None:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS resolution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_class TEXT NOT NULL, fork_signature TEXT NOT NULL,
                    outcome TEXT NOT NULL, chosen_option TEXT NOT NULL,
                    actor TEXT NOT NULL, task_id TEXT NOT NULL,
                    contract_digest TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resolution_action ON resolution_events(action_class);
                CREATE INDEX IF NOT EXISTS idx_resolution_fork ON resolution_events(fork_signature);
            """)
            self._db.execute("INSERT INTO schema_meta(key,value) VALUES ('version',?)", (str(SCHEMA_VERSION),))
            self._db.commit()
        elif int(current[0]) != SCHEMA_VERSION:
            raise RuntimeError(f"unsupported LearningStore schema version: {current[0]}")

    def check_standing_approval(self, action_class: str) -> bool:
        row = self._db.execute("SELECT 1 FROM resolution_events WHERE action_class=? AND outcome='approved' LIMIT 1", (action_class,)).fetchone()
        return row is not None

    def check_known_preference(self, fork_signature: str, threshold: int = 3) -> bool:
        if not fork_signature or threshold < 1:
            return False
        row = self._db.execute("""SELECT chosen_option, COUNT(*) AS n FROM resolution_events
            WHERE fork_signature=? AND outcome='approved' AND chosen_option<>''
            GROUP BY chosen_option ORDER BY n DESC LIMIT 1""", (fork_signature,)).fetchone()
        return row is not None and row["n"] >= threshold

    def record_resolution(self, action_class: str, fork_signature: str, outcome: str,
                          chosen_option: str, actor: str, task_id: str,
                          contract_digest: str, timestamp: str | None = None) -> None:
        stamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._db:
            self._db.execute("""INSERT INTO resolution_events
                (action_class,fork_signature,outcome,chosen_option,actor,task_id,contract_digest,timestamp)
                VALUES (?,?,?,?,?,?,?,?)""", (action_class, fork_signature, outcome, chosen_option,
                                                actor, task_id, contract_digest, stamp))

    def close(self) -> None:
        self._db.close()


class FieldbookGateBridge:
    """Small production bridge with fail-open fallback callback."""
    handles_fallback = True
    def __init__(self, *, learning_store: LearningStore, gate_adapter: Any,
                 fallback: Any, enabled: bool = False,
                 destructive_allowlist: Sequence[str] = ()):
        self.learning_store = learning_store
        self.gate_adapter = gate_adapter
        self.fallback = fallback
        self.enabled = enabled
        self.destructive_allowlist = frozenset(destructive_allowlist)
        self._pending: dict[str, RouterTask] = {}

    def _fallback(self, task: RouterTask, code: str, exc: Exception | None = None) -> BridgeResult:
        _LOG.warning("gate bridge degraded", extra={"event": code, "task_id": task.task_id,
                                                    "component": "gate_bridge",
                                                    "exception_class": type(exc).__name__ if exc else None,
                                                    "fallback": "legacy_telegram"})
        try:
            self.fallback(task)
        except Exception as fallback_exc:
            _LOG.warning("legacy Telegram fallback failed", extra={"task_id": task.task_id,
                                                                    "exception_class": type(fallback_exc).__name__})
        return BridgeResult(BridgeStatus.FALLBACK, task.task_id, reason=code,
                            degradation_code=code, contract_digest=task.contract_digest)

    def evaluate_and_maybe_gate(self, task: RouterTask) -> BridgeResult:
        if not self.enabled:
            return BridgeResult(BridgeStatus.PROCEED, task.task_id, reason="feature disabled",
                                disposition=GateDisposition.AUTONOMOUS.value, contract_digest=task.contract_digest)
        if "delete" in task.capabilities or "destroy" in task.capabilities:
            if self.destructive_allowlist and task.action_class not in self.destructive_allowlist:
                return self._fallback(task, "gate_bridge_unavailable")
        elif detect_always_ask_capabilities(task.capabilities):
            # First rollout is intentionally destructive-only.  Preserve the
            # established Telegram path for every other always-ask category.
            return self._fallback(task, "gate_bridge_unavailable")
        try:
            decision = evaluate_gate(GateTask(risk_class=task.risk_class, capabilities=task.capabilities,
                                              action_class=task.action_class), self.learning_store)
            if decision.disposition in (GateDisposition.AUTONOMOUS, GateDisposition.REPORT_ONLY):
                return BridgeResult(BridgeStatus.PROCEED, task.task_id, reason=decision.reason,
                                    disposition=decision.disposition.value, contract_digest=task.contract_digest)
            request = self.gate_adapter.create_request(task.fork_description or task.objective,
                task.recommended_option, list(task.options), task.trade_off, task.revert_path,
                "2999-01-01T00:00:00Z", task.idempotency_key or task.task_id)
            request_outcome = getattr(request, "outcome", None)
            request_outcome_value = getattr(request_outcome, "value", request_outcome)
            if request_outcome_value not in (None, "pending"):
                return self._fallback(task, "gate_malformed")
            self.gate_adapter.present(request.gate_id)
            self._pending[request.gate_id] = task
            return BridgeResult(BridgeStatus.PENDING, task.task_id, gate_id=request.gate_id,
                                disposition=decision.disposition.value, reason=decision.reason,
                                contract_digest=task.contract_digest)
        except Exception as exc:
            return self._fallback(task, "gate_bridge_unavailable", exc)

    def _unpack_reply(self, message: Any) -> tuple[str, str]:
        """Unpack an inbound Matrix event/message into (raw_text, subject_ref).

        Handles three shapes:
        1. Raw string (text event) — use string as raw_text, derive subject_ref.
        2. Object/dict with .text/["text"] and .sender/["sender"] (structured event).
        3. LightGateDecision object (already resolved by adapter).

        Returns:
            (raw_text, subject_ref) tuple.

        Raises:
            ValueError: If message shape is unrecognizable.
        """
        # Case 1: Already-resolved decision (external routing)
        if isinstance(message, LightGateDecision):
            # For already-resolved decisions, we need to reconstruct raw_text
            # This is a fallback path; prefer passing the original message.
            raise ValueError("LightGateDecision passed to _unpack_reply; use original message")

        # Case 2: Raw string (most common from Matrix text event)
        if isinstance(message, str):
            raw_text = message
            # Derive subject_ref from context if available, otherwise default
            # The bridge doesn't have access to Matrix sender context for raw strings
            subject_ref = "matrix:user"
            return raw_text, subject_ref

        # Case 3: Structured object with text and sender attributes
        # Try object attributes first
        text = getattr(message, "text", None)
        sender = getattr(message, "sender", None)

        # Fall back to dict access
        if text is None and isinstance(message, dict):
            text = message.get("text")
            sender = message.get("sender")

        if text is not None:
            if not isinstance(text, str):
                raise ValueError(f"Message text must be string, got {type(text).__name__}")
            raw_text = text
            subject_ref = sender if isinstance(sender, str) and sender.strip() else "matrix:user"
            return raw_text, subject_ref

        raise ValueError(f"Unrecognized message shape: {type(message).__name__}")

    def process_reply(self, message: Any) -> BridgeResult | None:
        try:
            raw_text, subject_ref = self._unpack_reply(message)
            result = self.gate_adapter.process_reply(raw_text, subject_ref)
            if result is None:
                return None
            outcome = getattr(result, "outcome", result)
            value = getattr(outcome, "value", outcome)
            gate_id = getattr(result, "gate_id", "")
            task = self._pending.pop(gate_id, None)
            task_id = getattr(result, "task_id", "") or (task.task_id if task else "")
            digest = task.contract_digest if task else None
            if task is not None:
                self.learning_store.record_resolution(
                    task.action_class, task.fork_description, str(value),
                    str(getattr(result, "chosen_option", "") or ""),
                    str(getattr(result, "subject_ref", "") or "unknown"), task.task_id,
                    task.contract_digest,
                )
            if value == "approved":
                return BridgeResult(BridgeStatus.PROCEED, task_id, outcome=value,
                                    contract_digest=digest)
            if value in {"rejected", "expired", "revoked"}:
                return BridgeResult(BridgeStatus.ABORT, task_id, outcome=value,
                                    contract_digest=digest)
            return BridgeResult(BridgeStatus.FALLBACK, task_id, outcome=value,
                                degradation_code="gate_malformed", contract_digest=digest)
        except Exception:
            return None


def load_bridge(*, gateway_context: Any = None, **kwargs: Any) -> GateBridge:
    """Construction hook used by a lazy Hermes-side loader."""
    return FieldbookGateBridge(**kwargs)


__all__ = ["BridgeResult", "BridgeStatus", "FieldbookGateBridge", "GateBridge", "LearningStore",
           "RouterTask", "SCHEMA_VERSION", "SQLiteLearningStore", "load_bridge"]
