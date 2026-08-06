from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agentic_fieldbook.gate_bridge import BridgeResult, BridgeStatus, RouterTask
from agentic_fieldbook.plugins.hitl_gate.detector import (
    build_router_task,
    detect_destructive,
)
from agentic_fieldbook.plugins.hitl_gate import (
    _bridge_from_context,
    _on_pre_gateway_dispatch,
    _on_pre_tool_call,
    _on_post_approval_response,
    _forget_native_approval,
    _native_session_for_gate,
    _on_pre_approval_request,
    _remember_native_approval,
    _queue_native_request,
    _dequeue_native_request,
    _forget_native_request,
    _PENDING_NATIVE_APPROVALS,
    _NATIVE_APPROVAL_BRIDGES,
    _PENDING_NATIVE_REQUESTS,
    _GATE_REQUEST_KEYS,
    _SEEN_GATE_EVENTS,
    _SEEN_GATE_EVENTS_ORDER,
    _GATE_THREAD_STATE,
    register,
)


@pytest.fixture(autouse=True)
def isolate_native_callback_state(monkeypatch):
    """Keep process-global callback indexes isolated between tests."""
    # The production callback imports Hermes' optional ``tools.approval``
    # module lazily.  Provide the smallest test seam when Hermes is not
    # installed in this standalone checkout; individual tests patch it.
    import sys
    import types
    if "tools.approval" not in sys.modules:
        approval_module = types.ModuleType("tools.approval")
        setattr(approval_module, "resolve_gateway_approval", lambda *_args: 1)
        tools_module = types.ModuleType("tools")
        setattr(tools_module, "approval", approval_module)
        monkeypatch.setitem(sys.modules, "tools", tools_module)
        monkeypatch.setitem(sys.modules, "tools.approval", approval_module)

    for mapping in (_PENDING_NATIVE_APPROVALS, _NATIVE_APPROVAL_BRIDGES,
                    _PENDING_NATIVE_REQUESTS, _GATE_REQUEST_KEYS):
        mapping.clear()
    _SEEN_GATE_EVENTS.clear()
    _SEEN_GATE_EVENTS_ORDER.clear()
    yield
    for mapping in (_PENDING_NATIVE_APPROVALS, _NATIVE_APPROVAL_BRIDGES,
                    _PENDING_NATIVE_REQUESTS, _GATE_REQUEST_KEYS):
        mapping.clear()
    _SEEN_GATE_EVENTS.clear()
    _SEEN_GATE_EVENTS_ORDER.clear()


@pytest.mark.parametrize(
    ("command", "action_class"),
    [
        ("rm -rf /tmp/preview", "rm-rf"),
        ("DROP TABLE users", "drop"),
        ("truncate table audit_log", "truncate"),
        ("docker volume destroy old-preview", "destroy"),
    ],
)
def test_detector_matches_destructive_patterns(command, action_class):
    match = detect_destructive("terminal", {"command": command})
    assert match is not None
    assert match.action_class == action_class
    assert build_router_task(match).capabilities == ("delete",)
    assert build_router_task(match).action_class == action_class


@pytest.mark.parametrize("tool_name,args", [
    ("terminal", {"command": "ls -la"}),
    ("terminal", {"command": "rm /tmp/file"}),
    ("write_file", {"content": "destroy is a word in documentation"}),
    ("terminal", {"command": 123}),
])
def test_detector_ignores_non_destructive_or_non_shell_calls(tool_name, args):
    assert detect_destructive(tool_name, args) is None


def _result(status: BridgeStatus, task_id: str = "call-1", **kwargs):
    return BridgeResult(status, task_id, **kwargs)


def test_hook_passes_through_proceed(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PROCEED)):
        assert _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1") is None


def test_hook_blocks_when_bridge_construction_degrades(monkeypatch):
    """A missing live bridge cannot authorize a destructive command."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    result = _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/hitl"}, task_id="call-1")
    assert result == {
        "action": "block",
        "message": "HITL gate blocked: destructive gate unavailable (gate_bridge_unavailable)",
    }


def test_hook_blocks_when_bridge_persistence_degrades(monkeypatch):
    """A bridge FALLBACK is degradation, not permission to execute."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.FALLBACK,
                                     reason="gate_bridge_unavailable")):
        result = _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/hitl"}, task_id="call-1")
    assert result == {
        "action": "block",
        "message": "HITL gate blocked: destructive gate unavailable (gate_bridge_unavailable)",
    }


def test_hook_translates_pending_to_approval(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    bridge = SimpleNamespace(is_pending_for=lambda _gate_id, _task_id: True)
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING, gate_id="matrix-gate-42")):
        directive = _on_pre_tool_call("terminal", {"command": "DROP TABLE users"},
                                      task_id="call-1", bridge=bridge)
    assert directive["action"] == "approve"
    assert directive["message"].startswith("Recommendation: ")
    assert "Fork:" in directive["message"]
    assert "Gate ID: matrix-gate-42" in directive["message"]
    assert "/gate approve matrix-gate-42" in directive["message"]
    assert "/gate reject matrix-gate-42" in directive["message"]
    assert "/gate pick <index> matrix-gate-42" in directive["message"]
    _forget_native_request("matrix-gate-42")


def test_pending_without_validator_fails_closed(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING, gate_id="gate-no-validator")):
        result = _on_pre_tool_call("terminal", {"command": "DROP TABLE users"},
                                   task_id="call-1", bridge=SimpleNamespace())
    assert result["action"] == "block"
    assert "binding failed" in result["message"]


def test_hook_blocks_without_gate_id_and_leaves_no_native_pending_state(monkeypatch):
    """A native approval must never advertise a missing/wrong gate identity."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING)):
        result = _on_pre_tool_call(
            "terminal", {"command": "DROP TABLE users"}, task_id="call-1"
        )
    assert result["action"] == "block"
    assert "no safe gate_id" in result["message"]


def test_hook_translates_abort_to_block(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.ABORT, reason="rejected by policy")):
        directive = _on_pre_tool_call("terminal", {"command": "truncate table users"}, task_id="call-1")
    assert directive == {"action": "block", "message": "HITL gate blocked destructive action: rejected by policy"}


def test_hook_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HITL_GATE_ENABLED", raising=False)
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback") as bridge:
        assert _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}) is None
    bridge.assert_not_called()


def test_register_wires_hook_and_context_config_enables(monkeypatch):
    monkeypatch.delenv("HITL_GATE_ENABLED", raising=False)
    callbacks = {}
    ctx = SimpleNamespace(config={"hitl_gate": {"enabled": True}}, register_hook=lambda name, cb: callbacks.update({name: cb}))
    register(ctx)
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PROCEED)):
        assert callbacks["pre_tool_call"]("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1") is None


def test_loader_imports_without_optional_runtime():
    # Importing the standalone package does not import Hermes CLI modules.
    import agentic_fieldbook.plugins.hitl_gate as plugin
    assert callable(plugin.register)


# --- R1 adversarial review regression tests ---


@pytest.mark.parametrize("command", [
    'echo "destroy is a word in documentation"',
    "printf 'DROP TABLE users'",
    'cat README.md',
    'tee /tmp/out <<< "destroy"',
])
def test_output_commands_do_not_trigger_gate(command):
    """R1 MEDIUM: echo/printf/cat/tee with destructive words must not trigger."""
    assert detect_destructive("terminal", {"command": command}) is None


@pytest.mark.parametrize("command", [
    "echo ok; rm -rf /tmp/x",
    "echo ok\nDROP TABLE users",
    "echo ok | rm -rf /tmp/x",
    "sudo echo DROP TABLE users",
    "cat README; DROP TABLE users",
])
def test_compound_commands_still_detect_destructive_segments(command):
    """R2 M1: output suppression must not hide later or prefixed commands."""
    assert detect_destructive("terminal", {"command": command}) is not None


@pytest.mark.parametrize("command", [
    "echo ok && rm -rf /tmp/x",
    "echo ok && sudo rm -rf /tmp/x",
    "echo ok && DROP TABLE users",
    "echo ok & rm -rf /tmp/x",
    "echo ok & DROP TABLE users",
])
def test_logical_and_and_background_split_output_from_destructive(command):
    """R4: compound ampersands must not hide a destructive trailing command."""
    assert detect_destructive("terminal", {"command": command}) is not None


@pytest.mark.parametrize("command", [
    "echo ok && echo more",
    "echo ok & echo more",
])
def test_logical_and_and_background_keep_pure_output_suppressed(command):
    """R4: splitting compound commands must preserve output-only suppression."""
    assert detect_destructive("terminal", {"command": command}) is None


@pytest.mark.parametrize("command", [
    'echo "DROP TABLE users; rm -rf /tmp/x"',
    "printf '%s' 'ok; DROP TABLE users'",
    'printf "%s" "ok; DROP TABLE users"',
    "echo 'DROP TABLE users'",
    r'''cat <<'EOF'
DROP TABLE users
rm -rf /tmp/x
EOF''',
    "cat <<-EOF\n\tDROP TABLE users\n\trm -rf /tmp/x\n\tEOF",
])
def test_quoted_and_heredoc_data_is_not_scanned(command):
    """R3: shell data must not become a destructive command segment."""
    assert detect_destructive("terminal", {"command": command}) is None


@pytest.mark.parametrize(
    ("command", "matches"),
    [
        ('echo "$(rm -rf /tmp/x)"', True),
        ('printf "%s" "$(DROP TABLE users)"', True),
        ("echo '$(rm -rf /tmp/x)'", False),  # single quotes make it literal data
    ],
)
def test_command_substitution_is_scanned_but_single_quote_data_is_not(command, matches):
    """R3: executable command substitutions cannot hide behind output guards."""
    assert (detect_destructive("terminal", {"command": command}) is not None) is matches


@pytest.mark.parametrize("command", [
    "destroy database prod",       # 'database' not in destroy object list
    "destroy",                     # bare word
    "the destroy command",         # prose
])
def test_destroy_requires_managed_object(command):
    """R1 MEDIUM: bare 'destroy' must not false-positive."""
    assert detect_destructive("terminal", {"command": command}) is None


@pytest.mark.parametrize("command", [
    "docker volume destroy old-preview",
    "docker container destroy stale",
    "docker image destroy dangling",
])
def test_destroy_with_managed_object_still_matches(command):
    """R1 MEDIUM fix: 'destroy <object>' still detected after narrowing."""
    match = detect_destructive("terminal", {"command": command})
    assert match is not None
    assert match.action_class == "destroy"


def test_hook_fails_closed_on_rendering_exception(monkeypatch):
    """A required destructive gate must block if rendering it fails."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    bridge = SimpleNamespace(is_pending_for=lambda _gate_id, _task_id: True,
                             _pending={"gate-render": object()})
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING, gate_id="gate-render")), \
         patch("agentic_fieldbook.plugins.hitl_gate._gate_message",
               side_effect=ValueError("malformed task")):
        result = _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"},
                                   task_id="call-1", bridge=bridge)
    assert result == {"action": "block", "message": "HITL gate blocked: gate handling failed"}
    assert not _PENDING_NATIVE_REQUESTS
    assert not _GATE_REQUEST_KEYS
    assert not _NATIVE_APPROVAL_BRIDGES
    assert not bridge._pending


@pytest.mark.parametrize("rendered", [None, "", 42])
def test_hook_fails_closed_on_non_presented_gate_message(monkeypatch, rendered):
    """A required gate never passes through without a usable presentation."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    bridge = SimpleNamespace(is_pending_for=lambda _gate_id, _task_id: True,
                             _pending={"gate-rendered": object()})
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING, gate_id="gate-rendered")), \
         patch("agentic_fieldbook.plugins.hitl_gate._gate_message", return_value=rendered):
        result = _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"},
                                   task_id="call-1", bridge=bridge)
    assert result == {"action": "block", "message": "HITL gate blocked: gate presentation failed"}
    assert not _PENDING_NATIVE_REQUESTS
    assert not _GATE_REQUEST_KEYS
    assert not _NATIVE_APPROVAL_BRIDGES
    assert not bridge._pending


@pytest.mark.parametrize("config", [object(), {"plugins": []}])
def test_hook_fail_open_on_malformed_config(monkeypatch, config):
    monkeypatch.delenv("HITL_GATE_ENABLED", raising=False)
    assert _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}, config=config) is None


@pytest.mark.parametrize("result", [
    object(),
    SimpleNamespace(status=object()),
    SimpleNamespace(status=BridgeStatus.ABORT, reason=object()),
])
def test_hook_fail_open_on_malformed_result(monkeypatch, result):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback", return_value=result):
        assert _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}) is None


def test_register_fail_open_on_malformed_context():
    class BrokenContext:
        def register_hook(self, *_args):
            raise RuntimeError("broken host integration")

    register(BrokenContext())


# --- Live bridge wiring (#91) ---


def test_bridge_from_context_constructs_and_caches_live_matrix_bridge(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    sent = []

    class LiveMatrix:
        async def send(self, room_id, content):
            sent.append((room_id, content))
            return SimpleNamespace(success=True, message_id="$matrix-event")

    context = SimpleNamespace(adapters={"matrix": LiveMatrix()})
    bridge = _bridge_from_context(context)

    assert bridge is context.hitl_gate_bridge
    assert bridge.enabled is True
    assert bridge.destructive_allowlist == frozenset(("rm-rf", "drop", "truncate", "destroy"))
    assert bridge.gate_adapter._room == "!home:example"
    match = detect_destructive("terminal", {"command": "rm -rf /tmp/x"})
    assert match is not None
    result = bridge.evaluate_and_maybe_gate(build_router_task(match, task_id="call-1"))
    assert result.status is BridgeStatus.PENDING
    assert sent and sent[0][0] == "!home:example"
    assert _bridge_from_context(context) is bridge


def test_bridge_from_context_prefers_gate_room_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    context = SimpleNamespace(adapters={"matrix": object()})
    bridge = _bridge_from_context(context)
    assert bridge.gate_adapter._room == "!gate:example"


@pytest.mark.parametrize("context", [
    SimpleNamespace(adapters={}),
    SimpleNamespace(),
])
def test_bridge_from_context_fails_open_without_live_matrix(monkeypatch, context):
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    assert _bridge_from_context(context) is None


def test_registered_hook_routes_destructive_call_to_live_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    callbacks = {}

    class LiveMatrix:
        async def send(self, _room_id, _content):
            return SimpleNamespace(success=True, message_id="$matrix-event")

    context = SimpleNamespace(adapters={"matrix": LiveMatrix()},
                              register_hook=lambda name, callback: callbacks.update({name: callback}))
    register(context)
    directive = callbacks["pre_tool_call"]("terminal", {"command": "DROP TABLE users"}, task_id="call-1")
    assert directive is not None
    assert directive["action"] == "approve"
    gate_id = next(iter(context.hitl_gate_bridge._pending))
    assert gate_id in directive["message"]
    assert context.hitl_gate_bridge.is_pending_for(gate_id, "call-1")


def test_registered_hook_blocks_without_live_matrix(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    callbacks = {}
    context = SimpleNamespace(adapters={},
                              register_hook=lambda name, callback: callbacks.update({name: callback}))
    register(context)
    result = callbacks["pre_tool_call"]("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1")
    assert result["action"] == "block"
    assert "destructive gate unavailable" in result["message"]


def test_live_bridge_routes_non_destructive_always_ask_to_telegram(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    fallback = []
    context = SimpleNamespace(adapters={"matrix": object()}, telegram_fallback=fallback.append)
    bridge = _bridge_from_context(context)
    task = RouterTask.from_mapping({
        "task_id": "secret-1", "objective": "rotate API key", "scope": ("key:example",),
        "exclusions": (), "risk_class": "high", "capabilities": ("secret-rotate",),
        "action_class": "secret-rotate",
    })
    result = bridge.evaluate_and_maybe_gate(task)
    assert result.status is BridgeStatus.FALLBACK
    assert fallback == [task]


# ---------------------------------------------------------------------------
# Bridge inbound-reply round-trip regression tests.
#
# These exercise the REAL bridge → adapter → transport path (fake transport,
# no live Matrix) to guard against the seam gap where bridge.process_reply(msg)
# passed one arg to an adapter that expected two (raw_text, subject_ref),
# silently swallowing the TypeError and leaving gates PENDING forever.
# ---------------------------------------------------------------------------


class _FakeReplyTransport:
    """Records sends; optionally fails to simulate Matrix outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self._fail = fail
        self._counter = 0

    def send(self, _room_id: str, message: str) -> str:
        if self._fail:
            raise ConnectionError("simulated matrix outage")
        self._counter += 1
        event_id = f"$fake-event-{self._counter}"
        self.sent.append(message)
        return event_id


def _make_destructive_task(task_id: str = "rt-1") -> RouterTask:
    return RouterTask(
        task_id=task_id,
        objective="delete /tmp/test",
        scope=("/tmp/test",),
        exclusions=(),
        risk_class="destructive",
        capabilities=("delete", "destroy"),
        action_class="rm-rf",
        fork_description="Delete /tmp/test dir",
        recommended_option="proceed",
        options=("proceed", "abort"),
        trade_off="irreversible delete vs needed cleanup",
        revert_path="restore from backup",
        idempotency_key="key-" + task_id,
        contract_digest="digest-" + task_id,
    )


def _build_round_trip_bridge(tmp_path, *, transport_fail: bool = False, enabled: bool = True):
    """Build a real bridge/adapter/store with a fake transport."""
    from datetime import timedelta

    from agentic_fieldbook.gate_bridge import FieldbookGateBridge, SQLiteLearningStore
    from agentic_fieldbook.matrix_gate_adapter import MatrixGateAdapter

    store = SQLiteLearningStore(tmp_path / "hitl-roundtrip.sqlite")
    transport = _FakeReplyTransport(fail=transport_fail)
    fallback_calls: list = []
    adapter = MatrixGateAdapter(
        transport, "!room:test", validity_window=timedelta(seconds=300),
        allowed_senders={"@jay:example"},
    )
    bridge = FieldbookGateBridge(
        learning_store=store,
        gate_adapter=adapter,
        fallback=fallback_calls.append,
        enabled=enabled,
        destructive_allowlist=("rm-rf", "drop", "truncate", "destroy"),
    )
    return bridge, transport, fallback_calls, store, adapter


@pytest.fixture
def _round_trip(tmp_path):
    bridge, transport, fallback, store, adapter = _build_round_trip_bridge(tmp_path)
    return bridge, transport, fallback, store, adapter


def test_round_trip_approve_raw_string(_round_trip):
    """approve via /gate command as a raw string resolves to PROCEED."""
    bridge, transport, _fallback, store, _adapter = _round_trip
    task = _make_destructive_task("approve-rt")
    result = bridge.evaluate_and_maybe_gate(task)
    assert result.status is BridgeStatus.PENDING
    assert len(transport.sent) == 1

    reply = bridge.process_reply(f"/gate approve {result.gate_id}")
    assert reply is not None
    assert reply.status is BridgeStatus.PROCEED
    assert reply.outcome == "approved"
    # Resolution must be persisted.
    assert store.check_known_preference(task.fork_description, threshold=1)


def test_round_trip_parses_emitted_control_message_independently(_round_trip):
    """The emitted bridge control message itself drives the reply round-trip."""
    bridge, transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("independent-control")
    pending = bridge.evaluate_and_maybe_gate(task)
    assert pending.status is BridgeStatus.PENDING
    assert len(transport.sent) == 1

    from agentic_fieldbook.matrix_gate_adapter import parse_gate_command
    control = next(line.strip() for line in transport.sent[0].splitlines()
                   if line.strip().startswith("/gate "))
    parsed = parse_gate_command(control)
    assert parsed is not None
    assert parsed.gate_id == pending.gate_id
    assert parsed.verb == "approve"
    reply = bridge.process_reply(control)
    assert reply is not None
    assert reply.status is BridgeStatus.PROCEED


def test_round_trip_reject_raw_string(_round_trip):
    """reject via /gate command resolves to ABORT."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("reject-rt")
    result = bridge.evaluate_and_maybe_gate(task)
    assert result.status is BridgeStatus.PENDING

    reply = bridge.process_reply(f"/gate reject {result.gate_id}")
    assert reply is not None
    assert reply.status is BridgeStatus.ABORT
    assert reply.outcome == "rejected"


def test_round_trip_reaction_record_failure_is_retryable(tmp_path):
    """A durable learning failure must not consume the Matrix reaction."""
    from datetime import timedelta

    from agentic_fieldbook.gate_bridge import FieldbookGateBridge, SQLiteLearningStore
    from agentic_fieldbook.matrix_gate_adapter import MatrixGateAdapter

    store = SQLiteLearningStore(tmp_path / "reaction-retry.sqlite")
    original_record = store.record_resolution
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("durable store unavailable")
        return original_record(*args, **kwargs)

    store.record_resolution = fail_once
    transport = _FakeReplyTransport()
    adapter = MatrixGateAdapter(
        transport, "!room:test", validity_window=timedelta(seconds=300),
        allowed_senders={"@jay:example"},
    )
    bridge = FieldbookGateBridge(
        learning_store=store, gate_adapter=adapter, fallback=lambda _task: None,
        enabled=True, destructive_allowlist=("rm-rf",),
    )
    task = _make_destructive_task("reaction-retry")
    pending = bridge.evaluate_and_maybe_gate(task)
    event = {
        "event_type": "m.reaction", "event_id": "$reaction-retry",
        "text": "", "sender": "@jay:example", "room_id": "!room:test",
        "relates_to": {"rel_type": "m.annotation",
            "event_id": adapter.get_matrix_event_id(pending.gate_id), "key": "✅"},
    }

    assert bridge.process_reply(event) is None
    retry = bridge.process_reply(event)

    assert retry is not None
    assert retry.status is BridgeStatus.PROCEED
    assert attempts == 2


def test_round_trip_expiry(_round_trip):
    """an expired gate resolves to ABORT with outcome=expired."""
    from datetime import datetime, timezone

    bridge, _transport, _fallback, _store, adapter = _round_trip
    task = _make_destructive_task("expire-rt")
    result = bridge.evaluate_and_maybe_gate(task)
    assert result.status is BridgeStatus.PENDING

    # Force expiry by mutating the stored request's expires_at.
    request = adapter._requests[result.gate_id]
    object.__setattr__(request, "expires_at", "2000-01-01T00:00:00Z")

    reply = bridge.process_reply(f"/gate approve {result.gate_id}")
    assert reply is not None
    assert reply.status is BridgeStatus.ABORT
    assert reply.outcome == "expired"


def test_round_trip_pick_option(_round_trip):
    """pick of a valid non-recommended option resolves."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("pick-rt")
    result = bridge.evaluate_and_maybe_gate(task)

    reply = bridge.process_reply(f"/gate pick abort {result.gate_id}")
    assert reply is not None
    # 'abort' is a valid option → adapter records APPROVED, bridge maps to PROCEED
    # (the option was valid, not the recommendation).
    assert reply.outcome == "approved"


def test_round_trip_structured_dict_message(_round_trip):
    """a dict with text+sender is unpacked correctly."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("dict-rt")
    result = bridge.evaluate_and_maybe_gate(task)

    msg = {"text": f"/gate approve {result.gate_id}", "sender": "@jay:test"}
    reply = bridge.process_reply(msg)
    assert reply is not None
    assert reply.status is BridgeStatus.PROCEED


def test_round_trip_subject_ref_recorded(tmp_path):
    """subject_ref from a structured message is persisted as actor in SQLite."""
    import sqlite3

    bridge, _transport, _fallback, _store, _adapter = _build_round_trip_bridge(tmp_path)
    task = _make_destructive_task("subject-rt")
    result = bridge.evaluate_and_maybe_gate(task)

    sender = "@jay:trshpotato.win"
    msg = {"text": f"/gate approve {result.gate_id}", "sender": sender}
    bridge.process_reply(msg)

    conn = sqlite3.connect(tmp_path / "hitl-roundtrip.sqlite")
    row = conn.execute(
        "SELECT actor FROM resolution_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == sender


def test_round_trip_free_text_ignored(_round_trip):
    """free text (not a /gate command) returns None — no resolution."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("freetext-rt")
    result = bridge.evaluate_and_maybe_gate(task)

    reply = bridge.process_reply("just chatting, not a gate command")
    assert reply is None


def test_round_trip_malformed_option(_round_trip):
    """a /gate pick with an invalid option yields FALLBACK (MALFORMED)."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    task = _make_destructive_task("malformed-rt")
    result = bridge.evaluate_and_maybe_gate(task)

    reply = bridge.process_reply(f"/gate pick nonexistent-opt {result.gate_id}")
    assert reply is not None
    assert reply.status is BridgeStatus.FALLBACK


def test_round_trip_matrix_failure_falls_back(tmp_path):
    """transport failure during present triggers Telegram fallback."""
    bridge, _transport, fallback, _store, _adapter = _build_round_trip_bridge(
        tmp_path, transport_fail=True
    )
    task = _make_destructive_task("fail-rt")
    result = bridge.evaluate_and_maybe_gate(task)
    assert result.status is BridgeStatus.FALLBACK
    assert len(fallback) == 1
    assert fallback[0].task_id == "fail-rt"


def test_round_trip_unknown_gate_id(_round_trip):
    """a /gate command referencing an unknown gate is safely ignored (None)."""
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    reply = bridge.process_reply("/gate approve matrix-gate-9999")
    # Unknown gate → MALFORMED decision, but bridge has no pending task for it.
    # The bridge returns None rather than fabricating a BridgeResult with an
    # empty task_id (which would violate BridgeResult's non-empty invariant).
    assert reply is None


def test_round_trip_unknown_gate_id_is_clean(caplog, _round_trip):
    """unknown gate_id must return None WITHOUT raising or logging a warning.

    Regression for a bug found during live integration testing: the broad
    except in process_reply was swallowing a ValueError caused by building a
    BridgeResult with task_id="" for an unknown gate.  The None return is
    correct, but it must be a clean early-return, not a swallowed exception
    that emits "hitl gate reply failed to resolve" log noise on every
    malformed reply.
    """
    bridge, _transport, _fallback, _store, _adapter = _round_trip
    import logging

    with caplog.at_level(logging.WARNING, logger="agentic_fieldbook.gate_bridge"):
        reply = bridge.process_reply("/gate approve matrix-gate-9999")

    assert reply is None
    # No warning should be logged — the None is now an explicit early return,
    # not a swallowed ValueError from the broad except handler.
    assert not any(
        "failed to resolve" in record.message
        for record in caplog.records
        if record.name == "agentic_fieldbook.gate_bridge"
    ), f"unexpected warning logged: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Live-bridge adapter resolution regression tests.
#
# PluginContext (the ctx passed to register()) does NOT expose .adapters.
# The bridge must fall back to the module-global weakref
# gateway.run._gateway_runner_ref — the same path send_message_tool uses.
# These guard against regressions in that resolution path.
# ---------------------------------------------------------------------------


def test_resolve_adapters_prefers_direct_context_attr():
    """context.adapters wins when present (test-injected or future Hermes surface)."""
    from agentic_fieldbook.plugins.hitl_gate.live_bridge import _resolve_adapters

    sentinel = {"matrix": object()}
    ctx = SimpleNamespace(adapters=sentinel)
    assert _resolve_adapters(ctx) is sentinel


def test_resolve_adapters_falls_back_to_gateway_runner_ref(monkeypatch):
    """When context.adapters is absent, resolve via _gateway_runner_ref()."""
    from agentic_fieldbook.plugins.hitl_gate import live_bridge as lb_mod

    fake_adapters = {"matrix": object()}
    fake_runner = SimpleNamespace(adapters=fake_adapters)

    # The global lives in gateway.run; patch the weakref callable.
    import sys
    fake_gateway_run = SimpleNamespace(_gateway_runner_ref=lambda: fake_runner)
    monkeypatch.setitem(sys.modules, "gateway.run", fake_gateway_run)

    ctx = SimpleNamespace()  # no .adapters attribute
    result = _resolve_adapters_of(lb_mod, ctx)
    assert result is fake_adapters


def _resolve_adapters_of(lb_mod, ctx):
    """Call _resolve_adapters from the module under test."""
    return lb_mod._resolve_adapters(ctx)


def test_resolve_adapters_returns_none_when_neither_path_available(monkeypatch):
    """No context.adapters AND no gateway runner → None (fail-open contract)."""
    from agentic_fieldbook.plugins.hitl_gate import live_bridge as lb_mod
    import sys

    # gateway.run absent or _gateway_runner_ref returns None
    fake_gateway_run = SimpleNamespace(_gateway_runner_ref=lambda: None)
    monkeypatch.setitem(sys.modules, "gateway.run", fake_gateway_run)

    ctx = SimpleNamespace()
    assert lb_mod._resolve_adapters(ctx) is None


def test_resolve_adapters_returns_none_when_gateway_import_fails(monkeypatch):
    """ImportError on gateway.run → None (fail-open contract)."""
    from agentic_fieldbook.plugins.hitl_gate import live_bridge as lb_mod

    # Make the lazy import inside _resolve_adapters fail
    import builtins
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "gateway.run":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    ctx = SimpleNamespace()
    assert lb_mod._resolve_adapters(ctx) is None


def test_build_live_bridge_uses_gateway_runner_ref(monkeypatch, tmp_path):
    """build_live_bridge succeeds when only the gateway runner ref is available,
    not a direct context.adapters attribute. This is the real production path."""
    from agentic_fieldbook.plugins.hitl_gate import live_bridge as lb_mod
    import sys

    # Build a fake adapter that the transport wrapper will use
    class _FakeAdapter:
        async def send(self, room_id, content):
            class R:
                success = True
                message_id = "$fake:1"
            return R()

    fake_adapters = {"matrix": _FakeAdapter()}
    fake_runner = SimpleNamespace(adapters=fake_adapters)
    fake_gateway_run = SimpleNamespace(_gateway_runner_ref=lambda: fake_runner)
    monkeypatch.setitem(sys.modules, "gateway.run", fake_gateway_run)

    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    # context has NO .adapters — simulates real PluginContext
    ctx = SimpleNamespace()
    bridge = lb_mod.build_live_bridge(ctx)
    assert bridge is not None
    assert bridge.enabled is True


def test_hook_fires_approve_via_gateway_runner_ref(monkeypatch, tmp_path):
    """End-to-end: the pre_tool_call hook returns an 'approve' directive when
    the bridge is built through the gateway runner ref path (no context.adapters).

    This is the regression test for the original production bug: the hook
    returned None (fail-open) because PluginContext had no .adapters, so the
    bridge was None and destructive commands passed through ungated."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    # Stand up a fake gateway runner with a Matrix adapter
    import sys

    class _FakeAdapter:
        async def send(self, room_id, content):
            class R:
                success = True
                message_id = "$fake:e2e"
            return R()

    fake_adapters = {"matrix": _FakeAdapter()}
    fake_runner = SimpleNamespace(adapters=fake_adapters)
    fake_gateway_run = SimpleNamespace(_gateway_runner_ref=lambda: fake_runner)
    monkeypatch.setitem(sys.modules, "gateway.run", fake_gateway_run)

    # Register the plugin with a context that has NO .adapters (like PluginContext)
    callbacks = {}
    context = SimpleNamespace(
        register_hook=lambda name, callback: callbacks.update({name: callback})
    )
    register(context)

    # Fire the hook on a destructive command
    result = callbacks["pre_tool_call"](
        "terminal", {"command": "rm -rf /tmp/e2e-test"}, task_id="e2e-1"
    )
    assert result is not None
    assert result["action"] == "approve"
    assert isinstance(result["message"], str)
    assert result["message"]


class _GateEvent:
    def __init__(self, text, room="!gate:example", sender="@jay:example", event_id=None,
                 event_type="m.room.message", relates_to=None, content=None, namespace=None):
        self.text = text
        self.message_id = event_id
        self.event_type = event_type
        self.relates_to = relates_to
        self.content = content
        self.context_namespace = namespace
        self.source = SimpleNamespace(
            platform=SimpleNamespace(value="matrix"),
            chat_id=room,
            user_id=sender,
        )


def test_registered_callbacks_share_live_bridge_across_callback_contexts(monkeypatch, tmp_path):
    """Outbound and inbound hooks must use one lifecycle-owned bridge/adapter."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class LiveMatrix:
        async def send(self, _room_id, _content):
            return SimpleNamespace(success=True, message_id="$fieldbook-gate")

    callbacks = {}
    registered_context = SimpleNamespace(
        adapters={"matrix": LiveMatrix()},
        register_hook=lambda name, callback: callbacks.update({name: callback}),
    )
    register(registered_context)

    command = "rm -rf /tmp/separate-callback-contexts"
    directive = callbacks["pre_tool_call"](
        "terminal", {"command": command}, task_id="separate-context-call",
        gateway_context=SimpleNamespace(),
    )
    assert directive is not None and directive["action"] == "approve"
    bridge = registered_context.hitl_gate_bridge
    gate_id = next(iter(bridge._pending))

    callbacks["pre_approval_request"](
        command=command, description="destructive command", pattern_key="rm-rf",
        session_key="native-separate-context",
    )
    event = _GateEvent(f"/gate approve {gate_id}", event_id="$separate-context-event")
    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        result = callbacks["pre_gateway_dispatch"](
            event, gateway=SimpleNamespace(hitl_gate_bridge=SimpleNamespace()),
        )

    assert result == {"action": "skip", "reason": "hitl gate proceed"}
    assert resolve.call_args.args == ("native-separate-context", "once")
    assert bridge.process_reply({"text": f"/gate approve {gate_id}", "sender": "@jay:example"}) is None
    assert registered_context.hitl_gate_bridge is bridge



def test_gate_room_approve_resolves_native_approval(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    gate_id = "gate-approve"
    _remember_native_approval(gate_id, "session-1")
    bridge = SimpleNamespace(
        process_reply=lambda message: _result(BridgeStatus.PROCEED, "call-1", gate_id=gate_id)
    )
    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        result = _on_pre_gateway_dispatch(_GateEvent(f"/gate approve {gate_id}"), gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    assert result["action"] == "skip"
    resolve.assert_called_once_with("session-1", "once")


def test_gate_room_reject_resolves_native_deny(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    gate_id = "gate-reject"
    _remember_native_approval(gate_id, "session-2")
    bridge = SimpleNamespace(
        process_reply=lambda message: _result(BridgeStatus.ABORT, "call-1", gate_id=gate_id)
    )
    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        _on_pre_gateway_dispatch(_GateEvent(f"/gate reject {gate_id}"), gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    resolve.assert_called_once_with("session-2", "deny")


def test_reaction_approval_resolves_native_approval(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    gate_id = "gate-reaction"
    _remember_native_approval(gate_id, "session-reaction")
    bridge = SimpleNamespace(
        process_reply=lambda message: _result(BridgeStatus.PROCEED, "call-1", gate_id=gate_id)
    )
    event = _GateEvent("", event_id="$reaction", event_type="m.reaction",
                       relates_to={"rel_type": "m.annotation", "event_id": "$prompt", "key": "✅"})
    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        result = _on_pre_gateway_dispatch(event, gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    assert result["reason"] == "hitl gate proceed"
    resolve.assert_called_once_with("session-reaction", "once")


def test_reaction_native_resolution_failure_is_retryable(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    gate_id = "gate-reaction-retry"
    _remember_native_approval(gate_id, "session-reaction-retry")
    bridge = SimpleNamespace(
        process_reply=lambda message: _result(BridgeStatus.PROCEED, "call-1", gate_id=gate_id)
    )
    event = _GateEvent("", event_id="$reaction-retry", event_type="m.reaction",
                       relates_to={"rel_type": "m.annotation", "event_id": "$prompt", "key": "✅"})
    with patch("tools.approval.resolve_gateway_approval", side_effect=[0, 1]) as resolve:
        first = _on_pre_gateway_dispatch(event, gateway=SimpleNamespace(hitl_gate_bridge=bridge))
        assert first["reason"] == "native approval unresolved"
        assert "$reaction-retry" not in _SEEN_GATE_EVENTS

        second = _on_pre_gateway_dispatch(event, gateway=SimpleNamespace(hitl_gate_bridge=bridge))

    assert second["reason"] == "hitl gate proceed"
    assert _native_session_for_gate(gate_id) is None
    assert "$reaction-retry" in _SEEN_GATE_EVENTS
    assert resolve.call_count == 2


def test_real_bridge_reaction_native_retry_cleans_up_without_duplicate_learning(tmp_path, monkeypatch):
    """The real bridge path retries native resolution and records learning once."""
    import sqlite3
    from datetime import timedelta
    from agentic_fieldbook.gate_bridge import FieldbookGateBridge, SQLiteLearningStore
    from agentic_fieldbook.matrix_gate_adapter import MatrixGateAdapter

    monkeypatch.setenv("MATRIX_GATE_ROOM", "!room:test")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    store = SQLiteLearningStore(tmp_path / "native-retry.sqlite")
    transport = _FakeReplyTransport()
    adapter = MatrixGateAdapter(transport, "!room:test", validity_window=timedelta(minutes=5),
                                allowed_senders={"@jay:example"})
    bridge = FieldbookGateBridge(learning_store=store, gate_adapter=adapter,
                                 fallback=lambda _task: None, enabled=True,
                                 destructive_allowlist=("rm-rf",))
    task = _make_destructive_task("native-retry-real")
    pending = bridge.evaluate_and_maybe_gate(task)
    _remember_native_approval(pending.gate_id, "native-real-session", bridge)
    event = _GateEvent("", room="!room:test", event_id="$native-real-reaction",
                       event_type="m.reaction", relates_to={
                           "rel_type": "m.annotation",
                           "event_id": adapter.get_matrix_event_id(pending.gate_id),
                           "key": "✅"})

    with patch("tools.approval.resolve_gateway_approval", side_effect=[0, 1]) as resolve:
        first = _on_pre_gateway_dispatch(event, gateway=SimpleNamespace(hitl_gate_bridge=bridge))
        assert first["reason"] == "native approval unresolved"
        assert bridge.is_pending_for(pending.gate_id, task.task_id)
        second = _on_pre_gateway_dispatch(event, gateway=SimpleNamespace(hitl_gate_bridge=bridge))

    assert second["reason"] == "hitl gate proceed"
    assert resolve.call_count == 2
    assert not bridge.is_pending_for(pending.gate_id, task.task_id)
    assert _native_session_for_gate(pending.gate_id) is None
    with sqlite3.connect(tmp_path / "native-retry.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM resolution_events").fetchone()[0] == 1


def test_reaction_unauthorized_wrong_room_and_replay_are_ignored(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    calls = []
    bridge = SimpleNamespace(process_reply=lambda message: calls.append(message) or _result(
        BridgeStatus.FALLBACK, "call-1", gate_id="gate-reaction-safe"))
    base = dict(event_type="m.reaction", event_id="$reaction-safe",
                relates_to={"rel_type": "m.annotation", "event_id": "$prompt", "key": "❌"})
    assert _on_pre_gateway_dispatch(_GateEvent("", sender="@intruder:example", **base), gateway=SimpleNamespace(hitl_gate_bridge=bridge))["action"] == "skip"
    assert _on_pre_gateway_dispatch(_GateEvent("", room="!other:example", **base)) is None
    first = _on_pre_gateway_dispatch(_GateEvent("", **base), gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    second = _on_pre_gateway_dispatch(_GateEvent("", **base), gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    assert first["reason"] == "hitl gate fallback"
    assert second["reason"] == "replayed hitl gate event"
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["👍", "✅"])
def test_reaction_namespace_mismatch_or_unrelated_shape_does_not_resolve(monkeypatch, key):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    bridge = SimpleNamespace(process_reply=pytest.fail)
    event = _GateEvent("", event_id="$bad-shape", event_type="m.reaction",
                       namespace="other", relates_to={"rel_type": "m.annotation",
                       "event_id": "$unrelated", "key": key})
    result = _on_pre_gateway_dispatch(event, context_namespace="current",
                                      gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    assert result["action"] == "skip"


@pytest.mark.parametrize("sender", ["@intruder:example", None])
def test_gate_room_unauthorized_sender_is_ignored(monkeypatch, sender):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    bridge = SimpleNamespace(process_reply=pytest.fail)
    result = _on_pre_gateway_dispatch(_GateEvent("/gate approve gate-1", sender=sender), gateway=SimpleNamespace(hitl_gate_bridge=bridge))
    assert result["action"] == "skip"


def test_gate_room_free_text_and_stale_gate_are_noops(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    bridge = SimpleNamespace(process_reply=lambda message: None)
    context = SimpleNamespace(hitl_gate_bridge=bridge)
    assert _on_pre_gateway_dispatch(_GateEvent("hello"), gateway=context)["action"] == "skip"
    with patch("tools.approval.resolve_gateway_approval") as resolve:
        assert _on_pre_gateway_dispatch(_GateEvent("/gate approve stale"), gateway=context)["action"] == "skip"
    resolve.assert_not_called()


def test_gate_room_replay_is_idempotent(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    calls = []
    bridge = SimpleNamespace(
        process_reply=lambda message: calls.append(message) or _result(
            BridgeStatus.FALLBACK, "call-1", gate_id="gate-replayed"
        )
    )
    context = SimpleNamespace(hitl_gate_bridge=bridge)
    event = _GateEvent("/gate approve gate-replayed", event_id="$matrix-replay")
    _on_pre_gateway_dispatch(event, gateway=context)
    result = _on_pre_gateway_dispatch(event, gateway=context)
    assert isinstance(result, dict)
    assert result["reason"] == "replayed hitl gate event"
    assert len(calls) == 1


def test_gate_event_is_retryable_after_transient_bridge_failure(monkeypatch):
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    calls = []

    def process(message):
        calls.append(message)
        if len(calls) == 1:
            return None
        return _result(BridgeStatus.FALLBACK, "call-1", gate_id="gate-retry")

    event = _GateEvent("/gate approve gate-retry", event_id="$matrix-retry")
    context = SimpleNamespace(hitl_gate_bridge=SimpleNamespace(process_reply=process))
    _on_pre_gateway_dispatch(event, gateway=context)
    result = _on_pre_gateway_dispatch(event, gateway=context)
    assert result["reason"] == "hitl gate fallback"
    assert len(calls) == 2


def test_native_timeout_retires_fieldbook_gate(monkeypatch):
    gate_id = "gate-timeout"
    expired = []
    bridge = SimpleNamespace(expire_gate=lambda value: expired.append(value))
    _remember_native_approval(gate_id, "session-timeout", bridge)
    _on_post_approval_response(choice="timeout", session_key="session-timeout")
    assert expired == [gate_id]


def test_native_association_survives_cross_thread_callbacks_and_timeout(monkeypatch):
    """Hook callbacks are allowed to execute on different host executors."""
    import threading

    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    command = "rm -rf /tmp/cross-executor"
    gate_id = "gate-cross-executor"
    expired = []
    bridge = SimpleNamespace(expire_gate=lambda value: expired.append(value),
                             is_pending_for=lambda _gate_id, _task_id: True)
    with patch(
        "agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
        return_value=_result(BridgeStatus.PENDING, "call-cross", gate_id=gate_id),
    ):
        first = threading.Thread(
            target=_on_pre_tool_call,
            kwargs={"tool_name": "terminal", "args": {"command": command},
                    "task_id": "call-cross", "bridge": bridge},
        )
        first.start(); first.join()

    second = threading.Thread(
        target=_on_pre_approval_request,
        kwargs={"command": command, "description": "destructive command",
                "pattern_key": "rm-rf", "session_key": "native-cross"},
    )
    second.start(); second.join()
    assert _native_session_for_gate(gate_id) == "native-cross"

    _on_post_approval_response(choice="timeout", session_key="native-cross")
    assert expired == [gate_id]
    assert _native_session_for_gate(gate_id) is None
    _forget_native_approval(gate_id)


def test_native_request_queues_are_concurrently_namespace_isolated():
    """Identical request values in two contexts cannot consume each other."""
    from concurrent.futures import ThreadPoolExecutor

    command = "rm -rf /tmp/same-command"
    bridge_a = SimpleNamespace(name="bridge-a")
    bridge_b = SimpleNamespace(name="bridge-b")

    def round_trip(namespace, gate_id, bridge):
        _queue_native_request(gate_id, bridge, command, namespace=namespace)
        return _dequeue_native_request({"command": command,
                                        "context_namespace": namespace})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda values: round_trip(*values),
            (("profile-a/lifecycle-a/bridge-a", "gate-a", bridge_a),
             ("profile-b/lifecycle-b/bridge-b", "gate-b", bridge_b)),
        ))
    assert {item[0] for item in results if item} == {"gate-a", "gate-b"}
    assert {item[1].name for item in results if item} == {"bridge-a", "bridge-b"}
    _forget_native_request("gate-a", "profile-a/lifecycle-a/bridge-a")
    _forget_native_request("gate-b", "profile-b/lifecycle-b/bridge-b")
    assert not _PENDING_NATIVE_APPROVALS


def test_registered_approval_callbacks_propagate_namespace_through_gate_resolution(monkeypatch):
    """Registered lifecycle context binds queue, association, and /gate lookup."""
    import sys
    import types

    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    resolved = []
    approval_module = types.ModuleType("tools.approval")
    setattr(approval_module, "resolve_gateway_approval",
            lambda session, choice: resolved.append((session, choice)) or 1)
    tools_module = types.ModuleType("tools")
    setattr(tools_module, "approval", approval_module)

    bridge = SimpleNamespace(
        is_pending_for=lambda _gate_id, _task_id: True,
        process_reply=lambda _message: _result(BridgeStatus.PROCEED, "call-namespace", gate_id=gate_id),
        expire_gate=lambda value: expired.append(value),
    )
    callbacks = {}
    ctx = SimpleNamespace(
        config={}, bridge=bridge, profile_id="profile-a", lifecycle_id="lifecycle-a",
        bridge_id="bridge-a", register_hook=lambda name, callback: callbacks.update({name: callback}),
    )
    command = "rm -rf /tmp/namespace-round-trip"
    gate_id = "gate-namespace-round-trip"
    expired = []

    with patch.dict(sys.modules, {"tools": tools_module, "tools.approval": approval_module}):
        register(ctx)
        with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
                   return_value=_result(BridgeStatus.PENDING, "call-namespace", gate_id=gate_id)):
            directive = callbacks["pre_tool_call"](
                "terminal", {"command": command}, task_id="call-namespace",
                gateway_context=SimpleNamespace(),
            )
        assert directive["action"] == "approve"
        callbacks["pre_approval_request"](
            command=command, description="destructive command", pattern_key="rm-rf",
            session_key="native-namespace", gateway_context=SimpleNamespace(),
        )
        namespace = "namespace:lifecycle_id=lifecycle-a|profile_id=profile-a|bridge_id=bridge-a"
        assert _native_session_for_gate(gate_id, namespace) == "native-namespace"
        result = callbacks["pre_gateway_dispatch"](
            _GateEvent(f"/gate approve {gate_id}"), gateway=SimpleNamespace(),
            gateway_context=SimpleNamespace(),
        )

    assert result == {"action": "skip", "reason": "hitl gate proceed"}
    assert resolved == [("native-namespace", "once")]
    assert not _native_session_for_gate(gate_id, namespace)


def test_registered_timeout_callback_retires_namespace_bound_gate():
    expired = []
    gate_id = "gate-namespace-timeout"
    bridge = SimpleNamespace(expire_gate=lambda value: expired.append(value))
    callbacks = {}
    ctx = SimpleNamespace(
        bridge=bridge, profile_id="profile-timeout", lifecycle_id="lifecycle-timeout",
        bridge_id="bridge-timeout",
        register_hook=lambda name, callback: callbacks.update({name: callback}),
    )
    register(ctx)
    namespace = "namespace:lifecycle_id=lifecycle-timeout|profile_id=profile-timeout|bridge_id=bridge-timeout"
    _remember_native_approval(gate_id, "native-timeout", bridge, namespace)
    callbacks["post_approval_response"](
        choice="timeout", session_key="native-timeout", gateway_context=SimpleNamespace(),
    )
    assert expired == [gate_id]
    assert _native_session_for_gate(gate_id, namespace) is None


def test_metadata_free_registered_contexts_keep_reverse_callbacks_isolated(monkeypatch):
    """Registration supplies unique identity when the host supplies no metadata."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_GATE_ROOM", "!gate:example")
    monkeypatch.setenv("MATRIX_ALLOWED_USERS", "@jay:example")
    command = "rm -rf /tmp/identical-command"
    contexts = []
    callbacks = []
    bridges = []
    reply_calls = []
    for name, gate_id in (("a", "gate-metadata-free-a"), ("b", "gate-metadata-free-b")):
        bridge = SimpleNamespace(
            is_pending_for=lambda _gate, _task: True,
            _pending={gate_id: object()},
            process_reply=lambda _message, gate_id=gate_id: (reply_calls.append(gate_id), _result(
                BridgeStatus.PROCEED, gate_id, gate_id=gate_id
            ))[1],
            expire_gate=lambda _gate: None,
        )
        registered = {}
        context = SimpleNamespace(
            bridge=bridge,
            config={"hitl_gate": {"enabled": True}},
            register_hook=lambda hook, callback, registered=registered: registered.update({hook: callback}),
        )
        register(context)
        contexts.append(context); callbacks.append(registered); bridges.append(bridge)

    assert contexts[0]._hitl_gate_namespace != contexts[1]._hitl_gate_namespace
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback", side_effect=[
        _result(BridgeStatus.PENDING, "call-a", gate_id="gate-metadata-free-a"),
        _result(BridgeStatus.PENDING, "call-b", gate_id="gate-metadata-free-b"),
    ]):
        for callback, task_id in zip(callbacks, ("call-a", "call-b")):
            assert callback["pre_tool_call"]("terminal", {"command": command}, task_id=task_id)["action"] == "approve"

    # Deliver native callbacks and inbound gate events in reverse context order.
    for callback, session in zip(reversed(callbacks), ("native-b", "native-a")):
        callback["pre_approval_request"](
            command=command, description="destructive command", pattern_key="rm-rf",
            session_key=session,
        )
    with patch("tools.approval.resolve_gateway_approval", return_value=1) as resolve:
        for callback, gate_id in zip(reversed(callbacks), ("gate-metadata-free-b", "gate-metadata-free-a")):
            result = callback["pre_gateway_dispatch"](_GateEvent(f"/gate approve {gate_id}"))
            assert result is not None, (reply_calls, contexts[0]._hitl_gate_namespace, contexts[1]._hitl_gate_namespace, dict(_PENDING_NATIVE_APPROVALS))
            assert result["reason"] == "hitl gate proceed"
    assert resolve.call_args_list == [(("native-b", "once"),), (("native-a", "once"),)]



def test_register_rolls_back_hooks_after_partial_failure():
    """A failed registration must not leave earlier callbacks active."""
    class Manager:
        def __init__(self):
            self._hooks = {}

    manager = Manager()
    ctx = SimpleNamespace(_manager=manager)
    calls = 0

    def register_hook(name, callback):
        nonlocal calls
        calls += 1
        manager._hooks.setdefault(name, []).append(callback)
        if calls == 2:
            raise RuntimeError("host rejected hook")

    ctx.register_hook = register_hook
    register(ctx)
    assert manager._hooks == {}


def test_failed_gate_message_does_not_leak_thread_association(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    pending = _result(BridgeStatus.PENDING, "call-1", gate_id="gate-failed-render")
    bridge = SimpleNamespace(is_pending_for=lambda _gate_id, _task_id: True,
                             _pending={"gate-failed-render": object()})
    with patch(
        "agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
        return_value=pending,
    ), patch(
        "agentic_fieldbook.plugins.hitl_gate._gate_message",
        side_effect=RuntimeError("render failed"),
    ):
        result = _on_pre_tool_call(
            "terminal", {"command": "DROP TABLE users"}, task_id="call-1",
            bridge=bridge,
        )
    assert result == {"action": "block", "message": "HITL gate blocked: gate handling failed"}
    assert not hasattr(_GATE_THREAD_STATE, "gate_id")


def test_home_room_is_an_inbound_gate_room_when_no_override(monkeypatch):
    monkeypatch.delenv("MATRIX_GATE_ROOM", raising=False)
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    bridge = SimpleNamespace(process_reply=lambda message: _result(BridgeStatus.FALLBACK, "call-1", gate_id="gate-1"))
    result = _on_pre_gateway_dispatch(
        _GateEvent("/gate approve gate-1", room="!home:example"),
        gateway=SimpleNamespace(hitl_gate_bridge=bridge),
    )
    assert result["action"] == "skip"
