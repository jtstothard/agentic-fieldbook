"""Test-only runner injection helper; never shipped as production API."""
from typing import Any, Callable

from agentic_fieldbook.claude_code_adapter import ClaudeCodeAdapter


def make_test_adapter(*, runner: Callable[..., Any] | None = None, **kwargs: Any) -> ClaudeCodeAdapter:
    adapter = ClaudeCodeAdapter(**kwargs)
    if runner is not None:
        adapter._runner = runner  # type: ignore[attr-defined]  # test seam only
    return adapter
