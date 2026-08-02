"""Contract tests for the recommendation-first gate-message renderer.

The renderer defines the SHAPE of what Jay sees: every gate message leads
with the recommendation, followed by the fork, the one material trade-off,
and the revert/abort path.  Mirrors the contract-test shape of
tests/test_light_gate.py.
"""
from __future__ import annotations

import pytest

from agentic_fieldbook.light_gate import (
    LightGateRequest,
    compute_fork_signature,
    render_gate_message,
)


# Minimal valid inputs --------------------------------------------------------

EXPIRES_FUTURE = "2099-01-01T00:00:00Z"

BASE_FIELDS = dict(
    gate_id="gate-001",
    fork_description="deploy v2 to prod",
    recommended_option="blue-green",
    options=("blue-green", "rolling", "halt"),
    trade_off="blue-green needs capacity headroom",
    revert_path="rollback to v1 via deploy button",
    expires_at=EXPIRES_FUTURE,
    idempotency_key="gate-1",
    fork_signature=compute_fork_signature(
        "deploy v2 to prod",
        "blue-green",
        ["blue-green", "rolling", "halt"],
        "blue-green needs capacity headroom",
        "rollback to v1 via deploy button",
        EXPIRES_FUTURE,
    ),
)


def make_request(**changes: object) -> LightGateRequest:
    """Return a valid ``LightGateRequest`` with optional field overrides."""
    fields: dict[str, object] = dict(BASE_FIELDS)
    fields.update(changes)
    return LightGateRequest(**fields)  # type: ignore[arg-type]


# Recommendation-first ordering ----------------------------------------------


class TestRecommendationFirstOrdering:
    """The recommended option must appear before fork/context detail."""

    def test_recommendation_is_first_line(self):
        request = make_request()
        message = render_gate_message(request)
        first_line = message.splitlines()[0]
        assert first_line.startswith("Recommendation: ")
        assert request.recommended_option in first_line

    def test_recommendation_precedes_fork(self):
        request = make_request()
        message = render_gate_message(request)
        rec_pos = message.index("Recommendation:")
        fork_pos = message.index("Fork:")
        assert rec_pos < fork_pos

    def test_recommendation_precedes_tradeoff(self):
        request = make_request()
        message = render_gate_message(request)
        rec_pos = message.index("Recommendation:")
        trade_pos = message.index("Trade-off:")
        assert rec_pos < trade_pos

    def test_recommendation_precedes_revert(self):
        request = make_request()
        message = render_gate_message(request)
        rec_pos = message.index("Recommendation:")
        revert_pos = message.index("Revert:")
        assert rec_pos < revert_pos

    def test_canonical_line_order(self):
        """Lines appear in canonical order: recommendation, fork, trade-off, revert."""
        request = make_request()
        message = render_gate_message(request)
        labels = [
            line.split(":", 1)[0] for line in message.splitlines()
        ]
        assert labels == ["Recommendation", "Fork", "Trade-off", "Revert"]


# All four required fields present -------------------------------------------


class TestRequiredFieldsPresent:
    """The rendered message must contain exactly the four required fields."""

    def test_contains_fork(self):
        request = make_request(fork_description="spec-fork on deploy strategy")
        message = render_gate_message(request)
        assert "Fork: spec-fork on deploy strategy" in message

    def test_contains_recommendation(self):
        request = make_request(recommended_option="halt")
        message = render_gate_message(request)
        assert "Recommendation: halt" in message

    def test_contains_tradeoff(self):
        request = make_request(trade_off="halt delays the release window")
        message = render_gate_message(request)
        assert "Trade-off: halt delays the release window" in message

    def test_contains_revert_path(self):
        request = make_request(revert_path="abort via git revert HEAD")
        message = render_gate_message(request)
        assert "Revert: abort via git revert HEAD" in message

    def test_message_has_exactly_four_lines(self):
        """No context, no options list — exactly one line per required field."""
        request = make_request()
        message = render_gate_message(request)
        assert len(message.splitlines()) == 4

    def test_options_not_in_message(self):
        """Options list is context — not rendered in the canonical message."""
        request = make_request(
            options=("blue-green", "rolling", "halt", "canary"),
        )
        message = render_gate_message(request)
        assert "canary" not in message
        assert "Options" not in message

    def test_renderer_is_pure_no_transport_fields(self):
        """No gate_id, idempotency_key, expires_at, or fork_signature leak in."""
        request = make_request()
        message = render_gate_message(request)
        assert request.gate_id not in message
        assert request.idempotency_key not in message
        assert request.fork_signature not in message

    def test_returns_string(self):
        request = make_request()
        message = render_gate_message(request)
        assert isinstance(message, str)


# Validation-error path ------------------------------------------------------


class TestValidationErrors:
    """A request with an empty required field raises at render time.

    In production, ``validate_light_gate_fields`` rejects these at adapter
    request creation, so the renderer never sees them.  The renderer defends
    in depth: if handed a malformed request (e.g. constructed directly), it
    raises ``ValueError`` rather than rendering a misleading message.
    """

    def test_empty_recommendation_raises(self):
        request = make_request(recommended_option="")
        with pytest.raises(ValueError, match="recommended_option"):
            render_gate_message(request)

    def test_whitespace_recommendation_raises(self):
        request = make_request(recommended_option="   ")
        with pytest.raises(ValueError):
            render_gate_message(request)

    def test_empty_fork_raises(self):
        request = make_request(fork_description="")
        with pytest.raises(ValueError, match="fork_description"):
            render_gate_message(request)

    def test_empty_tradeoff_raises(self):
        request = make_request(trade_off="")
        with pytest.raises(ValueError, match="trade_off"):
            render_gate_message(request)

    def test_empty_revert_raises(self):
        request = make_request(revert_path="")
        with pytest.raises(ValueError, match="revert_path"):
            render_gate_message(request)

    def test_error_names_all_missing_fields(self):
        request = make_request(
            recommended_option="",
            fork_description="",
            trade_off="",
        )
        with pytest.raises(ValueError) as exc_info:
            render_gate_message(request)
        message = str(exc_info.value)
        assert "recommended_option" in message
        assert "fork_description" in message
        assert "trade_off" in message


# Embedded-newline / label-injection rejection (repair for review findings M1+M2)


class TestMultilineRejection:
    """Embedded newlines break the one-line-per-field contract.

    A malicious or buggy caller could inject fake labels via
    "\\n[Recommendation] ..." — the renderer must reject embedded newlines
    and carriage returns rather than sanitize (reject is safer for a gate
    message).
    """

    def test_newline_in_recommendation_raises(self):
        request = make_request(
            recommended_option="blue-green\n[Revert] fake revert path"
        )
        with pytest.raises(ValueError, match="embedded newlines"):
            render_gate_message(request)

    def test_newline_in_fork_raises(self):
        request = make_request(fork_description="deploy\n[Recommendation] inject")
        with pytest.raises(ValueError, match="embedded newlines"):
            render_gate_message(request)

    def test_newline_in_tradeoff_raises(self):
        request = make_request(trade_off="cost\n[Revert] inject")
        with pytest.raises(ValueError, match="embedded newlines"):
            render_gate_message(request)

    def test_newline_in_revert_raises(self):
        request = make_request(revert_path="git revert\n[Recommendation] inject")
        with pytest.raises(ValueError, match="embedded newlines"):
            render_gate_message(request)

    def test_carriage_return_raises(self):
        request = make_request(recommended_option="blue-green\r[Revert] inject")
        with pytest.raises(ValueError, match="embedded newlines"):
            render_gate_message(request)

    def test_label_injection_attempt_rejected(self):
        """A newline-then-fake-label must not produce a fake line."""
        request = make_request(
            recommended_option="safe\nRecommendation: EVIL"
        )
        with pytest.raises(ValueError):
            render_gate_message(request)


class TestNonStringInputRejection:
    """Non-str fields (e.g. None from an adapter bug) raise ValueError, not
    AttributeError.  Repair for review finding M2."""

    def test_none_recommendation_raises_value_error(self):
        request = make_request(recommended_option=None)
        with pytest.raises(ValueError, match="must be str"):
            render_gate_message(request)

    def test_none_fork_raises_value_error(self):
        request = make_request(fork_description=None)
        with pytest.raises(ValueError, match="must be str"):
            render_gate_message(request)

    def test_int_input_raises_value_error(self):
        request = make_request(recommended_option=42)
        with pytest.raises(ValueError, match="must be str"):
            render_gate_message(request)
