"""Hermes ``pre_tool_call`` adapter for the Fieldbook HITL bridge.

The plugin is deliberately fail-open at the integration seam: bridge
availability failures return ``None`` so Hermes' existing approval path remains
responsible for the call.  A configured bridge may still return ``ABORT``,
which is translated into a veto.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

try:  # Keep plugin discovery safe when the optional package is unavailable.
    from ...gate_bridge import RouterTask
    from ...light_gate import LightGateRequest, compute_fork_signature, render_gate_message
    from ...router_bridge import evaluate_or_fallback
    from .detector import build_router_task, detect_destructive
except ImportError:  # pragma: no cover - exercised by loader smoke tests
    BridgeStatus = None  # type: ignore[assignment]
    RouterTask = Any  # type: ignore[misc,assignment]
    LightGateRequest = Any  # type: ignore[misc,assignment]
    compute_fork_signature = None  # type: ignore[assignment]
    render_gate_message = None  # type: ignore[assignment]
    evaluate_or_fallback = None  # type: ignore[assignment]
    build_router_task = None  # type: ignore[assignment]
    detect_destructive = None  # type: ignore[assignment]

_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _enabled(config: Any = None) -> bool:
    if os.environ.get("HITL_GATE_ENABLED", "").strip().lower() in _ENABLED_VALUES:
        return True
    if isinstance(config, Mapping):
        value = config.get("enabled", False)
    else:
        value = getattr(config, "enabled", False)
    return value is True or (isinstance(value, str) and value.lower() in _ENABLED_VALUES)


def _config_from_context(ctx: Any) -> Any:
    try:
        config = getattr(ctx, "config", None)
    except Exception:
        return None
    if isinstance(config, Mapping):
        plugins = config.get("plugins", {})
        if not isinstance(plugins, Mapping):
            plugins = {}
        return config.get("hitl_gate", plugins.get("hitl_gate", {}))
    return config


def _bridge_from_context(ctx: Any) -> Any:
    try:
        return getattr(ctx, "hitl_gate_bridge", getattr(ctx, "bridge", None))
    except Exception:
        return None


def _gate_message(task: Any) -> str:
    """Render the canonical recommendation-first message for a pending task."""
    signature = compute_fork_signature(
        task.fork_description, task.recommended_option, task.options,
        task.trade_off, task.revert_path, "2999-01-01T00:00:00Z",
    )
    request = LightGateRequest(
        gate_id=task.task_id,
        fork_description=task.fork_description,
        recommended_option=task.recommended_option,
        options=task.options,
        trade_off=task.trade_off,
        revert_path=task.revert_path,
        expires_at="2999-01-01T00:00:00Z",
        idempotency_key=task.idempotency_key or task.task_id,
        fork_signature=signature,
    )
    return render_gate_message(request)


def _on_pre_tool_call(tool_name: str = "", args: Any = None,
                      task_id: str = "", **kwargs: Any) -> dict[str, str] | None:
    """Route destructive shell calls to the bridge, otherwise pass through."""
    try:
        if not _enabled(kwargs.get("config")) or detect_destructive is None:
            return None
        match = detect_destructive(tool_name, args)
        if match is None:
            return None
        task = build_router_task(match, task_id=task_id)
        result = evaluate_or_fallback(
            task,
            fallback=lambda _task: None,
            bridge=kwargs.get("bridge"),
            gateway_context=kwargs.get("gateway_context"),
        )
        status_value = getattr(result, "status", None)
        status = getattr(status_value, "value", status_value)
        if status == "pending":
            message = _gate_message(task)
            if not isinstance(message, str):
                return None
            return {"action": "approve", "message": message}
        if status == "abort":
            reason = getattr(result, "reason", "destructive action rejected")
            if reason is None:
                reason = "destructive action rejected"
            if not isinstance(reason, str):
                return None
            return {"action": "block", "message": f"HITL gate blocked destructive action: {reason}"}
        # PROCEED and FALLBACK intentionally return None. FALLBACK hands control
        # to Hermes' established approval path rather than creating a second gate.
        return None
    except Exception:
        # The complete integration seam is fail-open: malformed context,
        # detector/task/result data, bridge failures, and rendering failures
        # all defer to Hermes' established approval path.
        return None


def register(ctx: Any) -> None:
    """Register the single pre-tool hook; disabled-by-default is enforced here."""
    try:
        if detect_destructive is None:
            return

        def on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> dict[str, str] | None:
            kwargs.setdefault("config", _config_from_context(ctx))
            kwargs.setdefault("bridge", _bridge_from_context(ctx))
            kwargs.setdefault("gateway_context", ctx)
            return _on_pre_tool_call(tool_name, args, **kwargs)

        ctx.register_hook("pre_tool_call", on_pre_tool_call)
    except Exception:
        # Plugin discovery/registration must not make the host fail closed.
        return


__all__ = ["register", "_on_pre_tool_call"]
