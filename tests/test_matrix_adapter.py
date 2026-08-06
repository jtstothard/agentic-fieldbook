"""Contract tests for the Matrix light-gate adapter (issue #78).

Covers every acceptance criterion:
- create_request / present / record_decision / revoke (all four ABC methods)
- present() sends the rendered message to the control room; returns
  presentation with matrix event ID
- record_decision() parses /gate approve|reject|pick <id> and returns
  LightGateDecision
- Free-text replies do not resolve gates (only structured commands)
- revoke() sends a follow-up message marking the gate expired/superseded
- The adapter takes a MatrixTransport protocol (send/receive) — no direct
  gateway import
- Expiry: an expired gate cannot be decided
"""
from __future__ import annotations

import pytest

from agentic_fieldbook.light_gate import (
    LightGateAdapter,
    LightGateDecision,
    LightGateOutcome,
    LightGatePresentation,
    LightGateRequest,
    LightGateRevocation,
    validate_gate_id,
)
from agentic_fieldbook.matrix_gate_adapter import (
    MatrixGateAdapter,
    MatrixMessage,
    MatrixTransport,
    ParsedGateCommand,
    parse_gate_command,
    render_gate_control_message,
)


# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #

EXPIRES_FUTURE = "2099-01-01T00:00:00Z"
EXPIRES_PAST = "2000-01-01T00:00:00Z"

ROOM = "!gate:matrix.org"


class FakeTransport:
    """In-memory MatrixTransport: records sent messages, yields event IDs."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self._counter = 0

    def send(self, room_id: str, message: str) -> str:
        self._counter += 1
        self.sent.append((room_id, message))
        return f"$evt-{self._counter:04d}"

    def receive(self) -> tuple[MatrixMessage, ...]:
        return ()


def make_adapter(
    *, validity_window=None, expires_at=EXPIRES_FUTURE,
) -> tuple[MatrixGateAdapter, FakeTransport]:
    transport = FakeTransport()
    adapter = MatrixGateAdapter(transport, ROOM, allowed_senders={"@jay:example"})
    return adapter, transport


def make_inputs(**changes: str) -> dict:
    base = dict(
        fork_description="deploy v2 to prod",
        recommended_option="blue-green",
        options=["blue-green", "rolling", "halt"],
        trade_off="blue-green needs capacity headroom",
        revert_path="rollback to v1 via deploy button",
        expires_at=EXPIRES_FUTURE,
        idempotency_key="gate-1",
    )
    base.update(changes)
    return base


# =========================================================================== #
# AC: implements LightGateAdapter ABC
# =========================================================================== #

class TestABCConformance:

    def test_is_light_gate_adapter_subclass(self):
        adapter, _ = make_adapter()
        assert isinstance(adapter, LightGateAdapter)

    def test_all_four_abc_methods_present(self):
        adapter, _ = make_adapter()
        for method in ("create_request", "present", "record_decision", "revoke"):
            assert callable(getattr(adapter, method))


# =========================================================================== #
# AC: create_request lifecycle
# =========================================================================== #

class TestCreateRequest:

    def test_creates_pending_request(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        assert request.outcome is LightGateOutcome.PENDING
        assert request.gate_id.startswith("matrix-gate-")
        assert request.fork_description == "deploy v2 to prod"
        assert request.options == ("blue-green", "rolling", "halt")
        assert request.fork_signature

    def test_idempotent_replay_same_fork(self):
        adapter, _ = make_adapter()
        first = adapter.create_request(**make_inputs())
        second = adapter.create_request(**make_inputs())
        assert second.gate_id == first.gate_id
        assert second.fork_signature == first.fork_signature

    def test_idempotency_conflict_on_mutated_fork(self):
        adapter, _ = make_adapter()
        first = adapter.create_request(**make_inputs())
        mutated = adapter.create_request(
            **make_inputs(fork_description="deploy v3 to prod"),
        )
        assert mutated.outcome is LightGateOutcome.IDEMPOTENCY_CONFLICT
        assert mutated.gate_id == first.gate_id

    def test_malformed_inputs_fail_closed(self):
        adapter, _ = make_adapter()
        empty = adapter.create_request(**make_inputs(fork_description=""))
        assert empty.outcome is LightGateOutcome.MALFORMED
        assert empty.gate_id == ""

    def test_concurrent_create_same_key_is_stable(self):
        from concurrent.futures import ThreadPoolExecutor
        adapter, _ = make_adapter()
        results = list(ThreadPoolExecutor(max_workers=8).map(
            lambda _: adapter.create_request(**make_inputs()), range(8),
        ))
        gate_ids = {r.gate_id for r in results}
        assert len(gate_ids) == 1
        assert next(iter(gate_ids)).startswith("matrix-gate-")
        assert all(r.outcome is LightGateOutcome.PENDING for r in results)


# =========================================================================== #
# AC: present() sends rendered message; returns presentation with event ID
# =========================================================================== #

class TestPresent:

    def test_present_sends_to_control_room(self):
        adapter, transport = make_adapter()
        request = adapter.create_request(**make_inputs())
        presentation = adapter.present(request.gate_id)

        assert presentation.outcome is LightGateOutcome.PRESENTED
        assert presentation.gate_id == request.gate_id
        assert len(transport.sent) == 1
        assert transport.sent[0][0] == ROOM

    def test_present_returns_matrix_event_id(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        event_id = adapter.get_matrix_event_id(request.gate_id)
        assert event_id.startswith("$evt-")
        assert event_id

    def test_present_content_is_rendered_message(self):
        """The Matrix path uses the control renderer, not the native-only body."""
        adapter, transport = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)

        sent_body = transport.sent[0][1]
        expected = render_gate_control_message(request)
        assert sent_body == expected
        assert f"Gate ID: {request.gate_id}" in sent_body
        assert f"/gate approve {request.gate_id}" in sent_body
        assert f"/gate reject {request.gate_id}" in sent_body
        assert f"/gate pick <index> {request.gate_id}" in sent_body
        assert "Options:\n1: blue-green" in sent_body

    def test_present_unknown_gate_returns_malformed(self):
        adapter, _ = make_adapter()
        presentation = adapter.present("nonexistent")
        assert presentation.outcome is LightGateOutcome.MALFORMED

    def test_present_rejects_unusable_transport_event_id(self):
        """A send without a string event ID cannot create a reaction binding."""
        class UnusableTransport(FakeTransport):
            def __init__(self, result):
                super().__init__()
                self.result = result

            def send(self, room_id: str, message: str):
                self.sent.append((room_id, message))
                return self.result

        for result in (None, "", "   ", 42):
            transport = UnusableTransport(result)
            adapter = MatrixGateAdapter(
                transport, ROOM, allowed_senders={"@jay:example"}
            )
            request = adapter.create_request(**make_inputs())
            presentation = adapter.present(request.gate_id)
            assert presentation.outcome is LightGateOutcome.MALFORMED
            assert presentation.reason == "transport returned no usable event id"
            assert adapter.get_matrix_event_id(request.gate_id) == ""

    def test_present_expired_gate_returns_expired(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs(expires_at=EXPIRES_PAST))
        presentation = adapter.present(request.gate_id)
        assert presentation.outcome is LightGateOutcome.EXPIRED
        # No message sent for an expired gate
        assert len(adapter._transport.sent) == 0  # type: ignore[attr-defined]


# =========================================================================== #
# AC: record_decision() + command parsing
# =========================================================================== #

class TestRecordDecision:

    def test_approve_via_direct_record(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.record_decision(
            request.gate_id, "blue-green", "jay",
        )
        assert decision.outcome is LightGateOutcome.APPROVED
        assert decision.chosen_option == "blue-green"
        assert decision.subject_ref == "jay"

    def test_reject_via_empty_option(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.record_decision(request.gate_id, "", "jay")
        assert decision.outcome is LightGateOutcome.REJECTED

    def test_invalid_option_is_malformed(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.record_decision(
            request.gate_id, "nonexistent", "jay",
        )
        assert decision.outcome is LightGateOutcome.MALFORMED

    def test_expired_gate_cannot_be_decided(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs(expires_at=EXPIRES_PAST))
        decision = adapter.record_decision(
            request.gate_id, "blue-green", "jay",
        )
        assert decision.outcome is LightGateOutcome.EXPIRED

    def test_revoked_gate_cannot_be_decided(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.revoke(request.gate_id, "wrong fork")
        decision = adapter.record_decision(
            request.gate_id, "blue-green", "jay",
        )
        assert decision.outcome is LightGateOutcome.REVOKED

    def test_reaction_approve_binds_to_prompt_event(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        decision = adapter.process_reaction({
            "event_type": "m.reaction", "event_id": "$reaction-1",
            "sender": "@jay:example", "room_id": ROOM,
            "content": {"m.relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "✅"}},
        })
        assert decision is not None
        assert decision.outcome is LightGateOutcome.APPROVED
        assert decision.chosen_option == request.recommended_option

    def test_unauthorized_reaction_sender_is_ignored(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        decision = adapter.process_reaction({
            "event_type": "m.reaction", "event_id": "$unauthorized",
            "sender": "@attacker:example", "room_id": ROOM,
            "relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "✅"},
        }, subject_ref="@jay:example")
        assert decision is None

    def test_reaction_without_room_is_ignored(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        decision = adapter.process_reaction({
            "event_type": "m.reaction", "event_id": "$missing-room",
            "sender": "@jay:example",
            "relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "✅"},
        }, subject_ref="@jay:example")
        assert decision is None

    def test_reaction_authorization_configuration_is_required(self):
        with pytest.raises(ValueError, match="reaction authorization"):
            MatrixGateAdapter(FakeTransport(), ROOM)

    def test_reaction_authorization_callback_is_used(self):
        transport = FakeTransport()
        adapter = MatrixGateAdapter(
            transport, ROOM, authorize_sender=lambda sender: sender == "@jay:example"
        )
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        decision = adapter.process_reaction({
            "event_type": "m.reaction", "event_id": "$callback",
            "sender": "@jay:example", "room_id": ROOM,
            "relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "✅"},
        })
        assert decision is not None
        assert decision.outcome is LightGateOutcome.APPROVED

    def test_reaction_reject_binds_to_prompt_event(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        decision = adapter.process_reaction({
            "type": "m.reaction", "event_id": "$reaction-2", "sender": "@jay:example",
            "room_id": ROOM, "relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "❌"},
        })
        assert decision is not None
        assert decision.outcome is LightGateOutcome.REJECTED

    def test_typed_mautrix_reaction_event_binds_to_prompt_event(self):
        """The live gateway shape uses typed event and relation objects."""
        from types import SimpleNamespace

        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        event = SimpleNamespace(
            type="m.reaction",
            event_id="$typed-reaction",
            sender="@jay:example",
            room_id=ROOM,
            content=SimpleNamespace(
                relates_to=SimpleNamespace(
                    rel_type="m.annotation",
                    event_id=adapter.get_matrix_event_id(request.gate_id),
                    key="✅",
                ),
            ),
        )
        decision = adapter.process_reaction(event)
        assert decision is not None
        assert decision.outcome is LightGateOutcome.APPROVED

    @pytest.mark.parametrize("event", [None, object(), {"type": "m.reaction"}])
    def test_malformed_or_empty_reaction_event_is_ignored(self, event):
        adapter, _ = make_adapter()
        assert adapter.process_reaction(event) is None

    @pytest.mark.parametrize("event_id", [None, "", "   "])
    def test_reaction_without_event_id_is_ignored(self, event_id):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        assert adapter.process_reaction({
            "event_type": "m.reaction", "event_id": event_id,
            "room_id": ROOM, "relates_to": {"rel_type": "m.annotation",
                "event_id": adapter.get_matrix_event_id(request.gate_id), "key": "✅"},
        }) is None

    @pytest.mark.parametrize("relation", [
        {"rel_type": "m.annotation", "event_id": "$unrelated", "key": "✅"},
        {"rel_type": "m.annotation", "event_id": "$prompt", "key": "👍"},
    ])
    def test_unrelated_or_arbitrary_reaction_is_ignored(self, relation):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)
        if relation["event_id"] == "$prompt":
            relation = {**relation, "event_id": adapter.get_matrix_event_id(request.gate_id)}
        assert adapter.process_reaction({"event_type": "m.reaction", "event_id": "$r",
                                          "room_id": ROOM, "relates_to": relation}) is None


# =========================================================================== #
# AC: revoke() sends follow-up message
# =========================================================================== #

class TestRevoke:

    def test_revoke_sends_followup_message(self):
        adapter, transport = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.present(request.gate_id)  # one message sent
        revocation = adapter.revoke(request.gate_id, "superseded by newer plan")

        assert revocation.outcome is LightGateOutcome.REVOKED
        assert revocation.reason == "superseded by newer plan"
        # Second message is the follow-up
        assert len(transport.sent) == 2
        assert request.gate_id in transport.sent[1][1]
        assert "revoked" in transport.sent[1][1].lower()

    def test_revoke_unknown_gate_returns_malformed(self):
        adapter, _ = make_adapter()
        revocation = adapter.revoke("nope", "reason")
        assert revocation.outcome is LightGateOutcome.MALFORMED

    def test_revoke_requires_reason(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        assert adapter.revoke(request.gate_id, "").outcome is LightGateOutcome.MALFORMED


# =========================================================================== #
# AC: command parsing (/gate approve|reject|pick <id>)
# =========================================================================== #

class TestCommandParsing:

    @pytest.mark.parametrize("gate_id", ["", " gate-1", "gate 1", "gate\n1", "gate;$x", "gate`id`"])
    def test_gate_id_validation_rejects_ambiguous_or_substitutable_tokens(self, gate_id):
        assert not validate_gate_id(gate_id)

    def test_adapter_namespaces_gate_ids_per_instance(self):
        first, _ = make_adapter()
        second, _ = make_adapter()
        a = first.create_request(**make_inputs())
        b = second.create_request(**make_inputs())
        assert a.gate_id != b.gate_id

    def test_parse_approve(self):
        parsed = parse_gate_command("/gate approve matrix-gate-1")
        assert parsed is not None
        assert parsed.verb == "approve"
        assert parsed.gate_id == "matrix-gate-1"
        assert parsed.picked_option == ""

    def test_parse_reject(self):
        parsed = parse_gate_command("/gate reject matrix-gate-1")
        assert parsed is not None
        assert parsed.verb == "reject"
        assert parsed.gate_id == "matrix-gate-1"

    def test_parse_pick(self):
        parsed = parse_gate_command("/gate pick rolling matrix-gate-1")
        assert parsed is not None
        assert parsed.verb == "pick"
        assert parsed.picked_option == "rolling"
        assert parsed.gate_id == "matrix-gate-1"

    def test_free_text_returns_none(self):
        assert parse_gate_command("yeah that looks good") is None
        assert parse_gate_command("approve matrix-gate-1") is None
        assert parse_gate_command("") is None

    def test_non_string_returns_none(self):
        assert parse_gate_command(None) is None  # type: ignore[arg-type]
        assert parse_gate_command(42) is None  # type: ignore[arg-type]

    def test_malformed_pick_missing_option(self):
        assert parse_gate_command("/gate pick matrix-gate-1") is None

    def test_malformed_approve_missing_id(self):
        assert parse_gate_command("/gate approve") is None

    def test_unknown_verb_ignored(self):
        assert parse_gate_command("/gate maybe matrix-gate-1") is None

    @pytest.mark.parametrize("command", [
        "/gate approve matrix-gate-1 extra",
        "/gate reject matrix-gate-1 junk",
        "/gate pick rolling matrix-gate-1 extra",
        "/gate pick two words matrix-gate-1",
        "/gate approve bad/id",
        "/gate pick rolling bad id",
    ])
    def test_trailing_tokens_and_invalid_shapes_are_rejected(self, command):
        assert parse_gate_command(command) is None

    def test_leading_whitespace_tolerated(self):
        parsed = parse_gate_command("  /gate approve matrix-gate-1")
        assert parsed is not None
        assert parsed.verb == "approve"

    def test_static_method_on_adapter(self):
        """parse_gate_command is exposed as a staticmethod on the adapter."""
        parsed = MatrixGateAdapter.parse_gate_command("/gate reject g-1")
        assert parsed is not None
        assert parsed.verb == "reject"


# =========================================================================== #
# AC: process_reply — command parsing drives record_decision; free text ignored
# =========================================================================== #

class TestProcessReply:

    def test_approve_command_resolves_gate(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.process_reply(
            f"/gate approve {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.outcome is LightGateOutcome.APPROVED
        # approve picks the recommended option
        assert decision.chosen_option == request.recommended_option

    def test_reject_command_resolves_gate(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.process_reply(
            f"/gate reject {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.outcome is LightGateOutcome.REJECTED

    def test_pick_command_chooses_option(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.process_reply(
            f"/gate pick rolling {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.outcome is LightGateOutcome.APPROVED
        assert decision.chosen_option == "rolling"

    def test_pick_index_chooses_multi_word_option(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs(
            recommended_option="blue green", options=["blue green", "halt now"],
        ))
        decision = adapter.process_reply(
            f"/gate pick 2 {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.chosen_option == "halt now"

    def test_pick_invalid_option_is_malformed(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.process_reply(
            f"/gate pick nonexistent {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.outcome is LightGateOutcome.MALFORMED

    def test_free_text_ignored(self):
        """Free-text replies do not resolve gates."""
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        decision = adapter.process_reply("looks good to me", "jay")
        assert decision is None

    def test_command_for_unknown_gate_is_malformed(self):
        adapter, _ = make_adapter()
        decision = adapter.process_reply("/gate approve nope", "jay")
        assert decision is not None
        assert decision.outcome is LightGateOutcome.MALFORMED

    def test_command_for_revoked_gate_is_revoked(self):
        adapter, _ = make_adapter()
        request = adapter.create_request(**make_inputs())
        adapter.revoke(request.gate_id, "superseded")
        decision = adapter.process_reply(
            f"/gate approve {request.gate_id}", "jay",
        )
        assert decision is not None
        assert decision.outcome is LightGateOutcome.REVOKED


# =========================================================================== #
# AC: deployment neutrality — MatrixTransport protocol
# =========================================================================== #

class TestDeploymentNeutrality:

    def test_takes_matrix_transport_protocol(self):
        """The adapter accepts any object with send/receive methods."""
        transport = FakeTransport()
        adapter = MatrixGateAdapter(transport, ROOM, allowed_senders={"@jay:example"})
        assert isinstance(transport, MatrixTransport)

    def test_no_direct_gateway_import(self):
        """The adapter module must not import a gateway client library."""
        import agentic_fieldbook.matrix_gate_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        # Protocol reference is fine; a concrete gateway import is not.
        assert "from hermes" not in source.lower()
        assert "import matrix_client" not in source
        assert "from matrix_client" not in source
