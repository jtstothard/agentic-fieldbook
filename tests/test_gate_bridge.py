from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass

from agentic_fieldbook.gate_bridge import (
    BridgeStatus, FieldbookGateBridge, RouterTask, SQLiteLearningStore,
)
from agentic_fieldbook.matrix_transport import HermesMatrixTransport, transport_from_gateway
from agentic_fieldbook.router_bridge import evaluate_or_fallback, get_bridge
from agentic_fieldbook.light_gate import LightGateDecision, LightGateOutcome, LightGatePresentation


def task(**overrides):
    values = dict(task_id="t1", objective="delete preview", scope=("item:1",),
                  exclusions=("production",), risk_class="high", capabilities=("delete",),
                  action_class="delete:item", fork_description="delete item", recommended_option="delete",
                  options=("delete", "abort"), trade_off="irreversible", revert_path="restore backup")
    values.update(overrides)
    return RouterTask.from_mapping(values)


def test_router_task_is_json_projection_and_digest_changes_with_scope():
    first = task()
    second = task(scope=("item:2",))
    assert isinstance(first.scope, tuple)
    assert first.contract_digest != second.contract_digest
    assert first.to_dict()["scope"] == ["item:1"]


def test_sqlite_store_wal_and_restart(tmp_path):
    path = tmp_path / "learning.sqlite"
    store = SQLiteLearningStore(path)
    store.record_resolution("delete:item", "fork", "approved", "delete", "actor", "t1", "digest")
    assert store.check_standing_approval("delete:item")
    store.close()
    again = SQLiteLearningStore(path)
    assert again.check_known_preference("fork", threshold=1)
    assert again._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    again.close()


def test_bridge_disabled_proceeds_without_adapter(tmp_path):
    result = FieldbookGateBridge(learning_store=SQLiteLearningStore(tmp_path / "x.db"),
                                 gate_adapter=None, fallback=lambda task: None).evaluate_and_maybe_gate(task())
    assert result.status is BridgeStatus.PROCEED


def test_bridge_gate_failure_falls_back(tmp_path):
    called = []
    class Broken:
        def create_request(self, *args): raise RuntimeError("down")
    result = FieldbookGateBridge(learning_store=SQLiteLearningStore(tmp_path / "x.db"),
                                 gate_adapter=Broken(), fallback=called.append, enabled=True,
                                 destructive_allowlist=("delete:item",)).evaluate_and_maybe_gate(task())
    assert result.status is BridgeStatus.FALLBACK
    assert called == [task()]


def test_lazy_loader_does_not_raise_when_loader_fails():
    assert get_bridge(loader=lambda **kwargs: (_ for _ in ()).throw(ImportError("optional"))) is None


def test_router_fallback_on_bridge_failure():
    called = []
    result = evaluate_or_fallback(task(), fallback=called.append,
                                  bridge=None, loader=lambda **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert result.status is BridgeStatus.FALLBACK
    assert called


def test_matrix_transport_uses_injected_live_adapter():
    @dataclass
    class Sent: success: bool = True; message_id: str = "$event"
    class Live:
        async def send(self, room, content):
            assert room == "!room:example"; assert content == "hello"
            return Sent()
    transport = transport_from_gateway({"matrix": Live()}, "!room:example")
    assert asyncio.run(transport.send("hello")) == "$event"


def test_real_bridge_reply_preserves_gate_id_for_native_resolution(tmp_path):
    """The production adapter decision must retain its gate identity."""
    from agentic_fieldbook.matrix_gate_adapter import MatrixGateAdapter

    class Transport:
        def send(self, _room, _message):
            return "$event"

        def receive(self):
            return ()

    store = SQLiteLearningStore(tmp_path / "replies.db")
    adapter = MatrixGateAdapter(Transport(), "!room:test")
    bridge = FieldbookGateBridge(
        learning_store=store, gate_adapter=adapter, fallback=lambda _task: None,
        enabled=True, destructive_allowlist=("delete:item",),
    )
    pending = bridge.evaluate_and_maybe_gate(task())
    resolved = bridge.process_reply(f"/gate approve {pending.gate_id}")

    assert resolved is not None
    assert resolved.gate_id == pending.gate_id
    assert resolved.task_id == pending.task_id


def test_reply_learning_failure_keeps_pending_for_retry(tmp_path):
    """A transient durable-store failure must not consume the gate."""
    from agentic_fieldbook.matrix_gate_adapter import MatrixGateAdapter

    class Transport:
        def send(self, _room, _message):
            return "$event"

        def receive(self):
            return ()

    class FlakyStore(SQLiteLearningStore):
        def __init__(self, path):
            super().__init__(path)
            self.fail = True

        def record_resolution(self, *args, **kwargs):
            if self.fail:
                self.fail = False
                raise OSError("temporary learning-store outage")
            return super().record_resolution(*args, **kwargs)

    store = FlakyStore(tmp_path / "retry.db")
    adapter = MatrixGateAdapter(Transport(), "!room:test")
    bridge = FieldbookGateBridge(
        learning_store=store, gate_adapter=adapter, fallback=lambda _task: None,
        enabled=True, destructive_allowlist=("delete:item",),
    )
    pending = bridge.evaluate_and_maybe_gate(task())
    message = f"/gate approve {pending.gate_id}"

    assert bridge.process_reply(message) is None
    assert pending.gate_id in bridge._pending
    retry = bridge.process_reply(message)
    assert retry is not None
    assert retry.gate_id == pending.gate_id
    assert pending.gate_id not in bridge._pending


def test_presentation_reentrant_reply_resolves_after_bind(tmp_path):
    """A synchronous adapter callback cannot outrun the gate/task binding."""
    store = SQLiteLearningStore(tmp_path / "reentrant.db")
    bridge = None

    class ReentrantAdapter:
        def create_request(self, *args):
            del args
            return type("Request", (), {"gate_id": "gate-reentrant", "outcome": LightGateOutcome.PENDING})()

        def present(self, gate_id):
            resolved.append(bridge.process_reply(f"/gate approve {gate_id}"))
            return LightGatePresentation(LightGateOutcome.PRESENTED, gate_id, "", "", (), "", "")

        def process_reply(self, _raw_text, _subject_ref):
            return LightGateDecision("gate-reentrant", LightGateOutcome.APPROVED, "delete", "actor", "now")

    resolved = []
    bridge = FieldbookGateBridge(
        learning_store=store, gate_adapter=ReentrantAdapter(), fallback=lambda _task: None,
        enabled=True, destructive_allowlist=("delete:item",),
    )
    result = bridge.evaluate_and_maybe_gate(task())
    assert resolved[0] is not None
    assert resolved[0].status is BridgeStatus.PROCEED
    assert result.status is BridgeStatus.PENDING
    assert "gate-reentrant" not in bridge._pending
