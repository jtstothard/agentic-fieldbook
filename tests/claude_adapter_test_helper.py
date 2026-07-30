"""Test-only runner injection helper; never shipped as production API."""
from typing import Any, Callable

from agentic_fieldbook.claude_code_adapter import ClaudeCodeAdapter


def make_test_adapter(*, runner: Callable[..., Any] | None = None, netns_name: str | None = "fieldbook-test", **kwargs: Any) -> ClaudeCodeAdapter:
    # Production construction is always bound to fieldbook-sandbox.  The
    # private runner seam may rewrite the dispatch argument for unit tests.
    configured = "fieldbook-sandbox" if netns_name in (None, "fieldbook-test") else netns_name
    adapter = ClaudeCodeAdapter(netns_name=configured, **kwargs)
    if runner is not None and netns_name == "fieldbook-test":
        adapter.netns_name = netns_name
    if runner is not None:
        adapter._runner = runner  # type: ignore[attr-defined]  # test seam only
    return adapter
