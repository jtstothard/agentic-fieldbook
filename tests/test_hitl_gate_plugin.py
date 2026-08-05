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
    _GATE_THREAD_STATE,
    register,
)


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


@pytest.mark.parametrize("status", [BridgeStatus.PROCEED, BridgeStatus.FALLBACK])
def test_hook_passes_through_proceed_and_fallback(monkeypatch, status):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(status)):
        assert _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1") is None


def test_hook_translates_pending_to_approval(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING)):
        directive = _on_pre_tool_call("terminal", {"command": "DROP TABLE users"}, task_id="call-1")
    assert directive["action"] == "approve"
    assert directive["message"].startswith("Recommendation: ")
    assert "Fork:" in directive["message"]


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


def test_hook_fail_open_on_rendering_exception(monkeypatch):
    """R1 MEDIUM: _gate_message raising must return None (fail-open), not escape."""
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    with patch("agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
               return_value=_result(BridgeStatus.PENDING)), \
         patch("agentic_fieldbook.plugins.hitl_gate._gate_message",
               side_effect=ValueError("malformed task")):
        result = _on_pre_tool_call("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1")
    assert result is None


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


def test_registered_hook_fails_open_to_passthrough_without_live_matrix(monkeypatch):
    monkeypatch.setenv("HITL_GATE_ENABLED", "1")
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    callbacks = {}
    context = SimpleNamespace(adapters={},
                              register_hook=lambda name, callback: callbacks.update({name: callback}))
    register(context)
    assert callbacks["pre_tool_call"]("terminal", {"command": "rm -rf /tmp/x"}, task_id="call-1") is None


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
        transport, "!room:test", validity_window=timedelta(seconds=300)
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
    def __init__(self, text, room="!gate:example", sender="@jay:example", event_id=None):
        self.text = text
        self.message_id = event_id
        self.source = SimpleNamespace(
            platform=SimpleNamespace(value="matrix"),
            chat_id=room,
            user_id=sender,
        )


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
    bridge = SimpleNamespace(expire_gate=lambda value: expired.append(value))
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
    with patch(
        "agentic_fieldbook.plugins.hitl_gate.evaluate_or_fallback",
        return_value=pending,
    ), patch(
        "agentic_fieldbook.plugins.hitl_gate._gate_message",
        side_effect=RuntimeError("render failed"),
    ):
        assert _on_pre_tool_call(
            "terminal", {"command": "DROP TABLE users"}, task_id="call-1",
        ) is None
    assert not hasattr(_GATE_THREAD_STATE, "gate_id")


def test_home_room_is_not_an_inbound_gate_room(monkeypatch):
    monkeypatch.delenv("MATRIX_GATE_ROOM", raising=False)
    monkeypatch.setenv("MATRIX_HOME_ROOM", "!home:example")
    bridge = SimpleNamespace(process_reply=pytest.fail)
    assert _on_pre_gateway_dispatch(
        _GateEvent("/gate approve gate-1", room="!home:example"),
        gateway=SimpleNamespace(hitl_gate_bridge=bridge),
    ) is None
