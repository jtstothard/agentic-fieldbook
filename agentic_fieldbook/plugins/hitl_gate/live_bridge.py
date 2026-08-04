"""Live gateway-context construction for the destructive HITL bridge.

This module is intentionally defensive: a missing Matrix adapter, malformed
gateway context, or unavailable Fieldbook persistence must leave Hermes on its
existing approval path rather than making the host unavailable.
"""
from __future__ import annotations

import os
import asyncio
import threading
from pathlib import Path
from typing import Any, Callable


_DESTRUCTIVE_ALLOWLIST = ("rm-rf", "drop", "truncate", "destroy")


def _state_path() -> Path:
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    return hermes_home / "plugins" / "agentic-fieldbook" / "hitl-gate.sqlite"


def _telegram_fallback(context: Any) -> Callable[[Any], None]:
    """Return the host's legacy Telegram callback, or a harmless no-op."""
    for name in ("telegram_fallback", "legacy_telegram_confirmation", "send_telegram_confirmation"):
        try:
            callback = getattr(context, name, None)
        except Exception:
            continue
        if callable(callback):
            def fallback(task: Any) -> None:
                callback(task)
            return fallback
    return lambda _task: None


class _SynchronousMatrixTransport:
    """Adapt the gateway's async transport to the synchronous gate adapter."""
    def __init__(self, transport: Any) -> None:
        self._transport = transport

    def send(self, room_id: str, message: str) -> str:
        del room_id  # The wrapped Hermes transport owns the configured room.
        coroutine = self._transport.send(message)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        result: list[str] = []
        failure: list[BaseException] = []

        def run() -> None:
            try:
                result.append(asyncio.run(coroutine))
            except BaseException as exc:  # returned through the bridge fallback
                failure.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        return result[0]

    def receive(self) -> tuple[Any, ...]:
        # Gateway event dispatch owns inbound Matrix traffic; this adapter is
        # outbound-only for the pre-tool hook path.
        return ()


def _resolve_adapters(context: Any) -> Any:
    """Resolve the gateway adapter registry from the plugin context.

    Hermes' ``PluginContext`` does not expose ``.adapters`` directly — it wraps
    a ``PluginManager``, not the ``GatewayRunner``.  The canonical path (used by
    ``send_message_tool``) is the module-global weakref
    ``gateway.run._gateway_runner_ref``, set in ``GatewayRunner.__init__``.

    A direct ``context.adapters`` attribute (injected by tests or by a future
    Hermes change that widens the plugin surface) still wins, preserving the
    original contract.
    """
    adapters = getattr(context, "adapters", None)
    if adapters is not None:
        return adapters
    runner = None
    try:
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
    except Exception:
        runner = None
    return getattr(runner, "adapters", None)


def build_live_bridge(context: Any) -> Any:
    """Build the production bridge from a running gateway context.

    Raises only to the caller; ``_bridge_from_context`` owns the public
    fail-open policy so this builder remains directly testable.
    """
    from ...gate_bridge import FieldbookGateBridge, SQLiteLearningStore
    from ...matrix_gate_adapter import MatrixGateAdapter
    from ...matrix_transport import transport_from_gateway

    room_id = os.environ.get("MATRIX_GATE_ROOM") or os.environ.get("MATRIX_HOME_ROOM")
    if not room_id:
        raise ValueError("MATRIX_HOME_ROOM or MATRIX_GATE_ROOM is required")
    adapters = _resolve_adapters(context)
    transport = transport_from_gateway(adapters, room_id)
    gate_adapter = MatrixGateAdapter(_SynchronousMatrixTransport(transport), room_id)
    return FieldbookGateBridge(
        learning_store=SQLiteLearningStore(_state_path()),
        gate_adapter=gate_adapter,
        fallback=_telegram_fallback(context),
        enabled=True,
        destructive_allowlist=_DESTRUCTIVE_ALLOWLIST,
    )


__all__ = ["build_live_bridge"]