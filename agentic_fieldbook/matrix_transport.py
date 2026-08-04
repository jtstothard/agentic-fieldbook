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


def transport_from_gateway(adapters: Any, room_id: str, matrix_key: Any = "matrix") -> HermesMatrixTransport:
    """Resolve the existing registry entry, accepting enum or string keys."""
    live = adapters.get(matrix_key) if hasattr(adapters, "get") else None
    if live is None and matrix_key != "matrix" and hasattr(adapters, "get"):
        live = adapters.get("matrix")
    if live is None:
        raise MatrixUnavailable("live Matrix adapter is not running")
    return HermesMatrixTransport(live, room_id)


__all__ = ["HermesMatrixTransport", "MatrixUnavailable", "transport_from_gateway"]
