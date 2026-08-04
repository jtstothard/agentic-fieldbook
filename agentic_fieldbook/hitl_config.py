"""Feature-gated HITL bridge configuration.

The bridge is deliberately disabled unless explicitly enabled.  The first
rollout is limited to named destructive action classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GateBridgeConfig:
    enabled: bool = False
    destructive_allowlist: tuple[str, ...] = ()
    room_id: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "GateBridgeConfig":
        data = data or {}
        allowlist = data.get("destructive_allowlist", ())
        if isinstance(allowlist, str):
            allowlist = (allowlist,)
        return cls(enabled=data.get("enabled", False) is True,
                   destructive_allowlist=tuple(str(item) for item in allowlist),
                   room_id=str(data.get("room_id", "")))


__all__ = ["GateBridgeConfig"]
