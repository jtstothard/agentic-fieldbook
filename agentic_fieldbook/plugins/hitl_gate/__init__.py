"""Hermes ``pre_tool_call`` adapter for the Fieldbook HITL bridge.

The plugin is deliberately fail-open at the integration seam: bridge
availability failures return ``None`` so Hermes' existing approval path remains
responsible for the call.  A configured bridge may still return ``ABORT``,
which is translated into a veto.
"""
from __future__ import annotations

import logging
import os
import hashlib
import threading
from collections import deque
from typing import Any, Mapping

_LOG = logging.getLogger(__name__)
_PENDING_NATIVE_APPROVALS: dict[str, str] = {}
_NATIVE_APPROVAL_BRIDGES: dict[str, Any] = {}
# Native approval callbacks may run on a different executor than pre_tool_call.
# Keep the association in a process-wide, lock-protected request index instead
# of context/thread-local state. Values are immutable (gate id + bridge).
_PENDING_NATIVE_REQUESTS: dict[str, deque[tuple[str, Any]]] = {}
_GATE_REQUEST_KEYS: dict[str, str] = {}
_SEEN_GATE_EVENTS: set[str] = set()
_SEEN_GATE_EVENTS_ORDER: deque[str] = deque()
_PENDING_LOCK = threading.Lock()

# Kept as a compatibility sentinel for older plugin tests; it is deliberately
# never used for association.
class _LegacyGateState:
    pass

_GATE_THREAD_STATE = _LegacyGateState()

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
    """Get an injected bridge or lazily attach the live gateway bridge.

    Every construction failure is an availability failure, never a host-hook
    failure.  Successful construction is cached on the gateway context so the
    SQLite store and gate adapter are stable for the process lifetime.
    """
    try:
        bridge = getattr(ctx, "hitl_gate_bridge", None)
        if bridge is not None:
            return bridge
        bridge = getattr(ctx, "bridge", None)
        if bridge is not None:
            return bridge
        from .live_bridge import build_live_bridge
        bridge = build_live_bridge(ctx)
        try:
            setattr(ctx, "hitl_gate_bridge", bridge)
        except Exception:
            # Some host contexts are immutable.  The constructed bridge is
            # still valid for this hook invocation; a later call may rebuild.
            pass
        return bridge
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


def _authorized_sender(sender: str) -> bool:
    """Apply the Matrix approval allow-list used by the native adapter."""
    if not isinstance(sender, str) or not sender.strip():
        return False
    allow_all = os.environ.get("GATEWAY_ALLOW_ALL_USERS", "").strip().lower() in _ENABLED_VALUES
    if allow_all:
        return True
    configured = (
        os.environ.get("MATRIX_ALLOWED_USERS", "")
        or os.environ.get("MATRIX_APPROVAL_SENDER", "")
        or os.environ.get("MATRIX_OWNER_USER", "")
    )
    allowed = {item.strip() for item in configured.split(",") if item.strip()}
    return bool(allowed) and sender in allowed


def _native_request_key(*parts: Any) -> str:
    """Return a stable, non-sensitive key for one native approval request."""
    payload = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approval_request_identity(kwargs: Mapping[str, Any]) -> str:
    explicit = kwargs.get("approval_id") or kwargs.get("request_id") or kwargs.get("approval_key")
    if explicit:
        return f"id:{explicit}"
    return "request:" + _native_request_key(
        kwargs.get("command"), kwargs.get("description"), kwargs.get("pattern_key"),
        kwargs.get("session_key"), kwargs.get("surface"),
    )


def _queue_native_request(gate_id: str, bridge: Any, command: str, identity: str = "") -> None:
    if not gate_id:
        return
    key = identity or ("command:" + _native_request_key(command))
    with _PENDING_LOCK:
        _PENDING_NATIVE_REQUESTS.setdefault(key, deque()).append((gate_id, bridge))
        _GATE_REQUEST_KEYS[gate_id] = key
        if bridge is not None:
            _NATIVE_APPROVAL_BRIDGES[gate_id] = bridge


def _dequeue_native_request(kwargs: Mapping[str, Any]) -> tuple[str, Any] | None:
    identity = _approval_request_identity(kwargs)
    command_key = "command:" + _native_request_key(kwargs.get("command"))
    with _PENDING_LOCK:
        for key in (identity, command_key):
            queue = _PENDING_NATIVE_REQUESTS.get(key)
            if queue:
                gate_id, bridge = queue.popleft()
                if not queue:
                    _PENDING_NATIVE_REQUESTS.pop(key, None)
                _GATE_REQUEST_KEYS[gate_id] = identity
                return gate_id, bridge
    return None


def _forget_native_request(gate_id: str) -> None:
    with _PENDING_LOCK:
        key = _GATE_REQUEST_KEYS.pop(gate_id, None)
        if key:
            queue = _PENDING_NATIVE_REQUESTS.get(key)
            if queue:
                _PENDING_NATIVE_REQUESTS[key] = deque(item for item in queue if item[0] != gate_id)
                if not _PENDING_NATIVE_REQUESTS[key]:
                    _PENDING_NATIVE_REQUESTS.pop(key, None)
        _NATIVE_APPROVAL_BRIDGES.pop(gate_id, None)


def _native_session_for_gate(gate_id: str) -> str | None:
    with _PENDING_LOCK:
        return _PENDING_NATIVE_APPROVALS.get(gate_id)


def _remember_native_approval(gate_id: str, session_key: str, bridge: Any = None) -> None:
    if gate_id and session_key:
        with _PENDING_LOCK:
            _PENDING_NATIVE_APPROVALS[gate_id] = session_key
            if bridge is not None:
                _NATIVE_APPROVAL_BRIDGES[gate_id] = bridge


def _forget_native_approval(gate_id: str) -> str | None:
    _forget_native_request(gate_id)
    with _PENDING_LOCK:
        return _PENDING_NATIVE_APPROVALS.pop(gate_id, None)


def _retire_native_approvals(session_key: str) -> None:
    """Expire Fieldbook gates when Hermes' native approval timed out."""
    with _PENDING_LOCK:
        gate_ids = [gate_id for gate_id, session in _PENDING_NATIVE_APPROVALS.items()
                    if session == session_key]
        bridges = [(gate_id, _NATIVE_APPROVAL_BRIDGES.pop(gate_id, None))
                   for gate_id in gate_ids]
        for gate_id in gate_ids:
            _PENDING_NATIVE_APPROVALS.pop(gate_id, None)
            key = _GATE_REQUEST_KEYS.pop(gate_id, None)
            if key:
                queue = _PENDING_NATIVE_REQUESTS.get(key)
                if queue:
                    remaining = deque(item for item in queue if item[0] != gate_id)
                    if remaining:
                        _PENDING_NATIVE_REQUESTS[key] = remaining
                    else:
                        _PENDING_NATIVE_REQUESTS.pop(key, None)
    for gate_id, bridge in bridges:
        expire = getattr(bridge, "expire_gate", None)
        if callable(expire):
            expire(gate_id)


def _on_pre_gateway_dispatch(event: Any = None, **kwargs: Any) -> dict[str, str] | None:
    """Resolve gate-room commands before they reach the agent dispatcher.

    This is the Hermes inbound-event hook, rather than a Matrix transport poller.
    It is deliberately fail-open: malformed events, unavailable bridges, and
    approval resolver errors are logged and never break gateway dispatch.
    """
    try:
        text = getattr(event, "text", None)
        source = getattr(event, "source", None)
        platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", None))
        room_id = getattr(source, "chat_id", None)
        gate_room = os.environ.get("MATRIX_GATE_ROOM")
        if str(platform).lower() != "matrix" or not gate_room or room_id != gate_room:
            return None

        # Gate rooms are notification/control rooms, never ordinary agent input.
        if not isinstance(text, str) or not text.lstrip().startswith("/gate"):
            return {"action": "skip", "reason": "hitl gate room is notification-only"}
        sender = getattr(source, "user_id", None) or getattr(source, "user_id_alt", None)
        event_id = getattr(event, "message_id", None) or getattr(event, "event_id", None)
        if isinstance(event_id, str) and event_id:
            with _PENDING_LOCK:
                if event_id in _SEEN_GATE_EVENTS:
                    return {"action": "skip", "reason": "replayed hitl gate event"}
        if not _authorized_sender(sender):
            _LOG.info("Ignoring unauthorized /gate command from %s", sender)
            return {"action": "skip", "reason": "unauthorized hitl gate sender"}

        context = kwargs.get("gateway") or kwargs.get("gateway_context")
        bridge = _bridge_from_context(context) if context is not None else None
        if bridge is None:
            return {"action": "skip", "reason": "hitl gate bridge unavailable"}
        result = bridge.process_reply({"text": text, "sender": sender})
        if result is None:
            # ``None`` also represents a bridge exception/unavailability. Do
            # not retire the transport event in that case: Matrix may retry
            # the same event after the transient failure clears.
            return {"action": "skip", "reason": "unknown or malformed hitl gate command"}
        status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
        gate_id = getattr(result, "gate_id", None) or ""
        session_key = _native_session_for_gate(gate_id)
        if session_key and status in {"proceed", "abort"}:
            from tools.approval import resolve_gateway_approval
            choice = "once" if status == "proceed" else "deny"
            resolved = resolve_gateway_approval(session_key, choice)
            _forget_native_approval(gate_id)
            if resolved == 0:
                _LOG.info("Stale /gate decision ignored for %s", gate_id)
        if isinstance(event_id, str) and event_id:
            with _PENDING_LOCK:
                if len(_SEEN_GATE_EVENTS_ORDER) >= 4096:
                    _SEEN_GATE_EVENTS.discard(_SEEN_GATE_EVENTS_ORDER.popleft())
                _SEEN_GATE_EVENTS.add(event_id)
                _SEEN_GATE_EVENTS_ORDER.append(event_id)
        return {"action": "skip", "reason": f"hitl gate {status or 'ignored'}"}
    except Exception:
        _LOG.warning("HITL gate inbound listener failed open", exc_info=True)
        return {"action": "skip", "reason": "hitl gate listener unavailable"}


def _on_pre_tool_call(tool_name: str = "", args: Any = None,
                      task_id: str = "", **kwargs: Any) -> dict[str, str] | None:
    """Route destructive shell calls to the bridge, otherwise pass through."""
    preserve_request = False
    gate_id = ""
    try:
        if not _enabled(kwargs.get("config")) or detect_destructive is None:
            return None
        match = detect_destructive(tool_name, args)
        if match is None:
            return None
        task = build_router_task(match, task_id=task_id)
        result = evaluate_or_fallback(
            task, fallback=lambda _task: None, bridge=kwargs.get("bridge"),
            gateway_context=kwargs.get("gateway_context"),
        )
        status_value = getattr(result, "status", None)
        status = getattr(status_value, "value", status_value)
        if status == "pending":
            gate_id = getattr(result, "gate_id", None) or ""
            if isinstance(gate_id, str) and gate_id:
                command = args.get("command", "") if isinstance(args, Mapping) else str(args or "")
                _queue_native_request(gate_id, kwargs.get("bridge"), command)
                preserve_request = True
            message = _gate_message(task)
            if not isinstance(message, str):
                return None
            return {"action": "approve", "message": message}
        if status == "abort":
            reason = getattr(result, "reason", "destructive action rejected") or "destructive action rejected"
            return {"action": "block", "message": f"HITL gate blocked destructive action: {reason}"} if isinstance(reason, str) else None
        return None
    except Exception:
        return None
    finally:
        if not preserve_request and gate_id:
            _forget_native_request(gate_id)


def _on_pre_approval_request(**kwargs: Any) -> None:
    """Associate Hermes' approval entry with our gate across executors."""
    try:
        association = _dequeue_native_request(kwargs)
        session_key = kwargs.get("session_key")
        if association and isinstance(session_key, str):
            gate_id, bridge = association
            _remember_native_approval(gate_id, session_key, bridge)
    except Exception:
        _LOG.debug("Unable to associate native approval with HITL gate", exc_info=True)


def _on_post_approval_response(**kwargs: Any) -> None:
    """Retire Fieldbook state when Hermes' native approval expires."""
    if kwargs.get("choice") == "timeout":
        session_key = kwargs.get("session_key")
        if isinstance(session_key, str):
            _retire_native_approvals(session_key)


def register(ctx: Any) -> None:
    """Register the complete hook set, rolling back a partial registration."""
    if detect_destructive is None:
        return

    def on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> dict[str, str] | None:
        kwargs.setdefault("config", _config_from_context(ctx))
        kwargs.setdefault("bridge", _bridge_from_context(ctx))
        kwargs.setdefault("gateway_context", ctx)
        return _on_pre_tool_call(tool_name, args, **kwargs)

    hooks = [
        ("pre_tool_call", on_pre_tool_call),
        ("pre_gateway_dispatch", _on_pre_gateway_dispatch),
        ("pre_approval_request", _on_pre_approval_request),
        ("post_approval_response", _on_post_approval_response),
    ]
    registered: list[tuple[str, Any]] = []
    try:
        for name, callback in hooks:
            # Track before calling the host: a host may append the callback and
            # then raise while finalizing registration.
            registered.append((name, callback))
            ctx.register_hook(name, callback)
    except Exception:
        # PluginContext currently has no public unregister API; remove only
        # callbacks registered by this attempt, then leave discovery healthy.
        manager = getattr(ctx, "_manager", None)
        registry = getattr(manager, "_hooks", None)
        if isinstance(registry, dict):
            for name, callback in registered:
                callbacks = registry.get(name, [])
                registry[name] = [item for item in callbacks if item is not callback]
                if not registry[name]:
                    registry.pop(name, None)
        unregister = getattr(ctx, "unregister_hook", None)
        if callable(unregister):
            for name, callback in reversed(registered):
                try:
                    unregister(name, callback)
                except Exception:
                    pass
        _LOG.warning("HITL gate hook registration rolled back", exc_info=True)


__all__ = ["register", "_on_pre_tool_call"]
