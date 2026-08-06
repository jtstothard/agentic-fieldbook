"""Hermes ``pre_tool_call`` adapter for the Fieldbook HITL bridge.

Bridge availability failures before a destructive gate is required return
``None`` so Hermes' existing approval path remains responsible for the call.
Once a destructive gate has been required, failures are fail-closed and return
an explicit block directive.  A configured bridge may still return ``ABORT``,
which is translated into a veto.
"""
from __future__ import annotations

import logging
import os
import hashlib
import threading
import uuid
from collections import deque
from typing import Any, Mapping

from ...hitl_config import effective_matrix_room
from ...light_gate import validate_gate_id

_LOG = logging.getLogger(__name__)
_PENDING_NATIVE_APPROVALS: dict[tuple[str, str], str] = {}
_NATIVE_APPROVAL_BRIDGES: dict[tuple[str, str], Any] = {}
# Native approval callbacks may run on a different executor than pre_tool_call.
# Keep the association in a process-wide, lock-protected request index instead
# of context/thread-local state. Values are immutable (gate id + bridge).
_PENDING_NATIVE_REQUESTS: dict[tuple[str, str], deque[tuple[str, Any]]] = {}
_GATE_REQUEST_KEYS: dict[tuple[str, str], tuple[str, str]] = {}
_SEEN_GATE_EVENTS: set[str] = set()
_SEEN_GATE_EVENTS_ORDER: deque[str] = deque()
_PENDING_LOCK = threading.Lock()
_REGISTRATION_NAMESPACES: dict[int, str] = {}

# Kept as a compatibility sentinel for older plugin tests; it is deliberately
# never used for association.
class _LegacyGateState:
    pass

_GATE_THREAD_STATE = _LegacyGateState()

try:  # Keep plugin discovery safe when the optional package is unavailable.
    from ...gate_bridge import RouterTask
    from ...light_gate import LightGateRequest, compute_fork_signature
    from ...matrix_gate_adapter import render_gate_control_message
    from ...router_bridge import evaluate_or_fallback
    from .detector import build_router_task, detect_destructive
except ImportError:  # pragma: no cover - exercised by loader smoke tests
    BridgeStatus = None  # type: ignore[assignment]
    RouterTask = Any  # type: ignore[misc,assignment]
    LightGateRequest = Any  # type: ignore[misc,assignment]
    compute_fork_signature = None  # type: ignore[assignment]
    render_gate_control_message = None  # type: ignore[assignment]
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


def _gate_message(task: Any, gate_id: str) -> str:
    """Render the canonical recommendation-first message for a pending task."""
    if not validate_gate_id(gate_id):
        raise ValueError("pending gate has no safe gate_id")
    signature = compute_fork_signature(
        task.fork_description, task.recommended_option, task.options,
        task.trade_off, task.revert_path, "2999-01-01T00:00:00Z",
    )
    request = LightGateRequest(
        gate_id=gate_id,
        fork_description=task.fork_description,
        recommended_option=task.recommended_option,
        options=task.options,
        trade_off=task.trade_off,
        revert_path=task.revert_path,
        expires_at="2999-01-01T00:00:00Z",
        idempotency_key=task.idempotency_key or task.task_id,
        fork_signature=signature,
    )
    return render_gate_control_message(request)


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


def _context_namespace(kwargs: Mapping[str, Any] | None = None, bridge: Any = None) -> str:
    """Derive the stable lifecycle/profile/bridge namespace for one callback."""
    source = kwargs or {}
    explicit_namespace = source.get("context_namespace")
    if explicit_namespace is not None and str(explicit_namespace):
        return str(explicit_namespace)
    values: list[str] = []
    context = source.get("gateway_context") or source.get("gateway")
    for item in ("context_namespace", "lifecycle_id", "profile_id", "profile",
                 "bridge_namespace", "bridge_id"):
        value = source.get(item)
        if value is None and context is not None:
            value = getattr(context, item, None)
        if value is None and bridge is not None:
            value = getattr(bridge, item, None)
        if value is not None and str(value):
            values.append(f"{item}={value}")
    # Existing callers do not pass lifecycle metadata.  Keep them in one
    # explicit, stable compatibility namespace; never use a command-only key.
    return "namespace:" + "|".join(values) if values else "namespace:legacy"


def _registration_namespace(ctx: Any) -> str:
    """Return the namespace persisted for one registered lifecycle context."""
    existing = getattr(ctx, "_hitl_gate_namespace", None)
    if isinstance(existing, str) and existing:
        return existing
    cached = _REGISTRATION_NAMESPACES.get(id(ctx))
    if cached:
        return cached
    metadata_namespace = _context_namespace({"gateway_context": ctx})
    namespace = metadata_namespace
    if metadata_namespace == "namespace:legacy":
        namespace = "namespace:registration:" + uuid.uuid4().hex
    try:
        setattr(ctx, "_hitl_gate_namespace", namespace)
    except Exception:
        _REGISTRATION_NAMESPACES[id(ctx)] = namespace
    return namespace


def _native_key(namespace: str, identity: str) -> tuple[str, str]:
    return namespace, identity


def _queue_native_request(gate_id: str, bridge: Any, command: str,
                          identity: str = "", namespace: str = "namespace:legacy") -> None:
    if not gate_id:
        return
    key = _native_key(namespace, identity or ("command:" + _native_request_key(command)))
    with _PENDING_LOCK:
        _PENDING_NATIVE_REQUESTS.setdefault(key, deque()).append((gate_id, bridge))
        _GATE_REQUEST_KEYS[(namespace, gate_id)] = key
        if bridge is not None:
            _NATIVE_APPROVAL_BRIDGES[(namespace, gate_id)] = bridge


def _dequeue_native_request(kwargs: Mapping[str, Any]) -> tuple[str, Any] | None:
    namespace = _context_namespace(kwargs, kwargs.get("bridge"))
    identity = _approval_request_identity(kwargs)
    command_key = "command:" + _native_request_key(kwargs.get("command"))
    with _PENDING_LOCK:
        for key in (_native_key(namespace, identity), _native_key(namespace, command_key)):
            queue = _PENDING_NATIVE_REQUESTS.get(key)
            if queue:
                gate_id, bridge = queue.popleft()
                if not queue:
                    _PENDING_NATIVE_REQUESTS.pop(key, None)
                _GATE_REQUEST_KEYS[(namespace, gate_id)] = key
                return gate_id, bridge
    return None


def _forget_native_request(gate_id: str, namespace: str = "namespace:legacy") -> None:
    with _PENDING_LOCK:
        key = _GATE_REQUEST_KEYS.pop((namespace, gate_id), None)
        if key:
            queue = _PENDING_NATIVE_REQUESTS.get(key)
            if queue:
                _PENDING_NATIVE_REQUESTS[key] = deque(item for item in queue if item[0] != gate_id)
                if not _PENDING_NATIVE_REQUESTS[key]:
                    _PENDING_NATIVE_REQUESTS.pop(key, None)
        _NATIVE_APPROVAL_BRIDGES.pop((namespace, gate_id), None)


def _native_session_for_gate(gate_id: str, namespace: str = "namespace:legacy") -> str | None:
    with _PENDING_LOCK:
        return _PENDING_NATIVE_APPROVALS.get((namespace, gate_id))


def _remember_native_approval(gate_id: str, session_key: str, bridge: Any = None,
                              namespace: str = "namespace:legacy") -> None:
    if gate_id and session_key:
        with _PENDING_LOCK:
            _PENDING_NATIVE_APPROVALS[(namespace, gate_id)] = session_key
            if bridge is not None:
                _NATIVE_APPROVAL_BRIDGES[(namespace, gate_id)] = bridge


def _forget_native_approval(gate_id: str, namespace: str = "namespace:legacy") -> str | None:
    _forget_native_request(gate_id, namespace)
    with _PENDING_LOCK:
        return _PENDING_NATIVE_APPROVALS.pop((namespace, gate_id), None)


def _retire_native_approvals(session_key: str, namespace: str = "namespace:legacy") -> None:
    """Expire Fieldbook gates when Hermes' native approval timed out."""
    with _PENDING_LOCK:
        gate_ids = [gate_id for (key_namespace, gate_id), session in _PENDING_NATIVE_APPROVALS.items()
                    if key_namespace == namespace and session == session_key]
        bridges = [(gate_id, _NATIVE_APPROVAL_BRIDGES.pop((namespace, gate_id), None))
                   for gate_id in gate_ids]
        for gate_id in gate_ids:
            _PENDING_NATIVE_APPROVALS.pop((namespace, gate_id), None)
            key = _GATE_REQUEST_KEYS.pop((namespace, gate_id), None)
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


def _cleanup_bridge_gate(bridge: Any, gate_id: str) -> None:
    """Remove a presented gate when native approval presentation failed."""
    if bridge is None or not gate_id:
        return
    expire = getattr(bridge, "expire_gate", None)
    if callable(expire):
        try:
            expire(gate_id)
            return
        except Exception:
            pass
    pending = getattr(bridge, "_pending", None)
    lock = getattr(bridge, "_pending_lock", None)
    try:
        if pending is not None:
            if lock is not None:
                with lock:
                    pending.pop(gate_id, None)
            else:
                pending.pop(gate_id, None)
    except Exception:
        _LOG.debug("Unable to clean failed native gate", exc_info=True)


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
        room_id = getattr(source, "chat_id", None) or getattr(event, "room_id", None)
        gate_room = effective_matrix_room()
        if str(platform).lower() != "matrix" or not gate_room or room_id != gate_room:
            return None

        event_type = getattr(event, "event_type", None) or getattr(event, "type", None)
        is_reaction = event_type in {"m.reaction", "reaction"}
        # Gate rooms are notification/control rooms, never ordinary agent input.
        if not is_reaction and (not isinstance(text, str) or not text.lstrip().startswith("/gate")):
            return {"action": "skip", "reason": "hitl gate room is notification-only"}
        sender = getattr(source, "user_id", None) or getattr(source, "user_id_alt", None) or getattr(event, "sender", None)
        event_id = getattr(event, "message_id", None) or getattr(event, "event_id", None)
        event_namespace = getattr(event, "context_namespace", None)
        requested_namespace = kwargs.get("context_namespace")
        if event_namespace and requested_namespace and event_namespace != requested_namespace:
            return {"action": "skip", "reason": "wrong hitl gate namespace"}
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
        result = bridge.process_reply(
            {
                "text": text if isinstance(text, str) else "",
                "sender": sender,
                "event_id": event_id or "",
                "room_id": room_id,
                "event_type": event_type or "m.room.message",
                "content": getattr(event, "content", None),
                "relates_to": getattr(event, "relates_to", None),
                "context_namespace": requested_namespace or "",
            }
        )
        if result is None:
            # ``None`` also represents a bridge exception/unavailability. Do
            # not retire the transport event in that case: Matrix may retry
            # the same event after the transient failure clears.
            return {"action": "skip", "reason": "unknown or malformed hitl gate command"}
        status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
        gate_id = getattr(result, "gate_id", None) or ""
        namespace = _context_namespace(kwargs, bridge)
        session_key = _native_session_for_gate(gate_id, namespace)
        if session_key and status in {"proceed", "abort"}:
            from tools.approval import resolve_gateway_approval
            choice = "once" if status == "proceed" else "deny"
            resolved = resolve_gateway_approval(session_key, choice)
            if not resolved:
                # Keep the native association and inbound event unseen so a
                # transient/failed native resolution can retry the same event.
                _LOG.warning("Native /gate decision was not resolved for %s", gate_id)
                return {"action": "skip", "reason": "native approval unresolved"}
            _forget_native_approval(gate_id, namespace)
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
            if not validate_gate_id(gate_id):
                return {"action": "block", "message": "HITL gate blocked: bridge returned no safe gate_id"}
            bridge = kwargs.get("bridge")
            is_bound = getattr(bridge, "is_pending_for", None)
            if not callable(is_bound) or not is_bound(gate_id, task.task_id):
                return {"action": "block", "message": "HITL gate blocked: gate/task binding failed"}
            command = args.get("command", "") if isinstance(args, Mapping) else str(args or "")
            explicit_identity = kwargs.get("approval_id") or kwargs.get("request_id") or kwargs.get("approval_key")
            identity = f"id:{explicit_identity}" if explicit_identity else ""
            namespace = _context_namespace(kwargs, bridge)
            _queue_native_request(gate_id, bridge, command, identity, namespace)
            message = _gate_message(task, gate_id)
            if not isinstance(message, str) or not message.strip():
                return {
                    "action": "block",
                    "message": "HITL gate blocked: gate presentation failed",
                }
            preserve_request = True
            return {"action": "approve", "message": message}
        if status == "abort":
            reason = getattr(result, "reason", "destructive action rejected") or "destructive action rejected"
            return {"action": "block", "message": f"HITL gate blocked destructive action: {reason}"} if isinstance(reason, str) else None
        return None
    except Exception:
        if gate_id:
            _LOG.warning("HITL destructive gate failed closed", exc_info=True)
            return {"action": "block", "message": "HITL gate blocked: gate handling failed"}
        return None
    finally:
        if not preserve_request and gate_id:
            namespace = _context_namespace(kwargs, kwargs.get("bridge"))
            _forget_native_request(gate_id, namespace)
            _cleanup_bridge_gate(kwargs.get("bridge"), gate_id)


def _on_pre_approval_request(**kwargs: Any) -> None:
    """Associate Hermes' approval entry with our gate across executors."""
    try:
        association = _dequeue_native_request(kwargs)
        session_key = kwargs.get("session_key")
        if association and isinstance(session_key, str):
            gate_id, bridge = association
            _remember_native_approval(gate_id, session_key, bridge,
                                       _context_namespace(kwargs, bridge))
    except Exception:
        _LOG.debug("Unable to associate native approval with HITL gate", exc_info=True)


def _on_post_approval_response(**kwargs: Any) -> None:
    """Retire Fieldbook state when Hermes' native approval expires."""
    if kwargs.get("choice") == "timeout":
        session_key = kwargs.get("session_key")
        if isinstance(session_key, str):
            _retire_native_approvals(session_key, _context_namespace(kwargs, kwargs.get("bridge")))


def register(ctx: Any) -> None:
    """Register the complete hook set, rolling back a partial registration."""
    if detect_destructive is None:
        return
    namespace = _registration_namespace(ctx)

    def on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> dict[str, str] | None:
        kwargs.setdefault("config", _config_from_context(ctx))
        kwargs["bridge"] = _bridge_from_context(ctx)
        kwargs["gateway_context"] = ctx
        kwargs["context_namespace"] = namespace
        return _on_pre_tool_call(tool_name, args, **kwargs)

    def on_pre_gateway_dispatch(event: Any = None, **kwargs: Any) -> dict[str, str] | None:
        # The host may invoke inbound hooks with a different callback context.
        # Keep the registered PluginContext as the profile/gateway lifecycle
        # owner so inbound replies use the bridge and adapter created by the
        # outbound hook, rather than constructing a fresh empty bridge.
        kwargs["gateway"] = ctx
        kwargs["gateway_context"] = ctx
        kwargs["context_namespace"] = namespace
        return _on_pre_gateway_dispatch(event, **kwargs)

    def on_pre_approval_request(**kwargs: Any) -> None:
        # Native approval callbacks may execute later and on another executor.
        # Reinject the context captured at registration so their namespace is
        # identical to the outbound pre_tool_call namespace.  Approval fields
        # (session_key, request_id, command, etc.) remain caller-owned.
        kwargs["gateway_context"] = ctx
        kwargs["bridge"] = _bridge_from_context(ctx)
        kwargs["context_namespace"] = namespace
        return _on_pre_approval_request(**kwargs)

    def on_post_approval_response(**kwargs: Any) -> None:
        # As above, force lifecycle identity while preserving the host's
        # response choice and session key.
        kwargs["gateway_context"] = ctx
        kwargs["bridge"] = _bridge_from_context(ctx)
        kwargs["context_namespace"] = namespace
        return _on_post_approval_response(**kwargs)

    hooks = [
        ("pre_tool_call", on_pre_tool_call),
        ("pre_gateway_dispatch", on_pre_gateway_dispatch),
        ("pre_approval_request", on_pre_approval_request),
        ("post_approval_response", on_post_approval_response),
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
