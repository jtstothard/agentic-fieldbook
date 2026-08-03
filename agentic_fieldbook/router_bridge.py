"""Hermes-side lazy bridge seam.

Importing this module is safe when Agentic Fieldbook is not installed.  The
optional package is resolved only inside ``get_bridge``.
"""
from __future__ import annotations

import logging
from typing import Any

from .gate_bridge import BridgeResult, GateBridge, RouterTask

_LOG = logging.getLogger(__name__)


def get_bridge(*, gateway_context: Any = None, loader: Any = None, logger: Any = None, **kwargs: Any) -> GateBridge | None:
    """Lazily load an optional bridge; construction failures are availability failures."""
    log = logger or _LOG
    try:
        if loader is None:
            from .gate_bridge import load_bridge
            loader = load_bridge
        return loader(gateway_context=gateway_context, **kwargs)
    except Exception as exc:
        log.warning("gate bridge unavailable", extra={"event": "gate_bridge_unavailable",
                                                      "component": "gate_bridge",
                                                      "exception_class": type(exc).__name__})
        return None


def evaluate_or_fallback(task: RouterTask, *, fallback: Any, bridge: GateBridge | None = None,
                         gateway_context: Any = None, logger: Any = None, **kwargs: Any) -> BridgeResult:
    """Invoke the bridge without allowing integration failures into the executor."""
    if bridge is None:
        bridge = get_bridge(gateway_context=gateway_context, logger=logger, **kwargs)
    if bridge is None:
        fallback(task)
        return BridgeResult("fallback", task.task_id, reason="gate_bridge_unavailable",
                            degradation_code="gate_bridge_unavailable", contract_digest=task.contract_digest)
    try:
        result = bridge.evaluate_and_maybe_gate(task)
        if not isinstance(result, BridgeResult):
            raise TypeError("bridge returned invalid result")
        status_value = getattr(result.status, "value", result.status)
        if status_value == "fallback" and not getattr(bridge, "handles_fallback", False):
            fallback(task)
        return result
    except Exception as exc:
        (logger or _LOG).warning("gate bridge degraded", extra={"event": "gate_bridge_unavailable",
                                                                  "task_id": task.task_id,
                                                                  "exception_class": type(exc).__name__})
        fallback(task)
        return BridgeResult("fallback", task.task_id, reason="gate_bridge_unavailable",
                            degradation_code="gate_bridge_unavailable", contract_digest=task.contract_digest)


__all__ = ["BridgeResult", "GateBridge", "RouterTask", "evaluate_or_fallback", "get_bridge"]
