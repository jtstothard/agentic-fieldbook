"""Adapter wrapper for the already-running Hermes Matrix gateway object."""
from __future__ import annotations

import inspect
from typing import Any


class MatrixUnavailable(RuntimeError):
    pass


class HermesMatrixTransport:
    """Async wrapper; never constructs a Matrix client or polling loop."""
    def __init__(self, live_adapter: Any, room_id: str):
        if live_adapter is None:
            raise MatrixUnavailable("live Matrix adapter is not running")
        if not room_id:
            raise ValueError("room_id is required")
        self.live_adapter = live_adapter
        self.room_id = room_id

    async def send(self, content: str) -> str:
        try:
            result = self.live_adapter.send(self.room_id, content)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise MatrixUnavailable("live Matrix send failed") from exc
        success = getattr(result, "success", True)
        if success is False:
            raise MatrixUnavailable(str(getattr(result, "error", "live Matrix send failed")))
        return str(getattr(result, "message_id", "") or "")


def _resolve_matrix_adapter(adapters: Any) -> Any:
    """Resolve the live Matrix adapter from the gateway adapter registry.

    The registry is keyed by ``Platform`` enum members (e.g.
    ``Platform.MATRIX``), not by bare strings, so a plain ``adapters.get("matrix")``
    misses. Try, in order: the string, the enum member, and any key whose
    ``value``/``name`` matches ``"matrix"``.
    """
    if not hasattr(adapters, "get"):
        return None
    # 1. Direct string lookup (works if a future Hermes change widens the surface)
    live = adapters.get("matrix")
    if live is not None:
        return live
    # 2. Enum member lookup (the canonical path as of gateway/config.py Platform)
    try:
        from gateway.config import Platform
        live = adapters.get(Platform.MATRIX)
    except Exception:
        pass
    if live is not None:
        return live
    # 3. Fallback: scan keys for a matrix-like member (str, Enum, or .value)
    for key in list(getattr(adapters, "keys", lambda: [])()):
        val = getattr(key, "value", key)
        name = getattr(key, "name", "")
        if val == "matrix" or name == "MATRIX":
            live = adapters.get(key)
            if live is not None:
                return live
    return None


def transport_from_gateway(adapters: Any, room_id: str, matrix_key: Any = "matrix") -> HermesMatrixTransport:
    """Resolve the existing registry entry, accepting enum or string keys."""
    live = _resolve_matrix_adapter(adapters)
    if live is None:
        raise MatrixUnavailable("live Matrix adapter is not running")
    return HermesMatrixTransport(live, room_id)


__all__ = ["HermesMatrixTransport", "MatrixUnavailable", "transport_from_gateway"]
