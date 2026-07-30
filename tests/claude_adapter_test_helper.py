"""Test-only runner injection helper; never shipped as production API."""
from typing import Any, Callable

from agentic_fieldbook.claude_code_adapter import ClaudeCodeAdapter


def make_test_adapter(*, runner: Callable[..., Any] | None = None, netns_name: str = "fieldbook-test", **kwargs: Any) -> ClaudeCodeAdapter:
    adapter = ClaudeCodeAdapter(netns_name=netns_name, **kwargs)
    if runner is not None:
        adapter._runner = runner  # type: ignore[attr-defined]  # test seam only
    return adapter
