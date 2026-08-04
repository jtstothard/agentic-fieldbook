from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agentic_fieldbook.gate_bridge import BridgeResult, BridgeStatus, RouterTask
from agentic_fieldbook.plugins.hitl_gate.detector import (
    build_router_task,
    detect_destructive,
)
from agentic_fieldbook.plugins.hitl_gate import _bridge_from_context, _on_pre_tool_call, register


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
