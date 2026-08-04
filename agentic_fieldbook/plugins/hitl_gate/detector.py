"""Destructive tool-call detection for the HITL gate plugin."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from ...router_bridge import RouterTask


@dataclass(frozen=True)
class DestructiveMatch:
    """A normalized destructive command match."""

    action_class: str
    command: str
    pattern: str


# Ordered from most specific to least specific so a command has a stable class.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rm-rf", re.compile(r"\brm\s+(?:-[^\s]*[rR][^\s]*\s+)*-[^\s]*[fF][^\s]*(?:\s|$)", re.I)),
    ("drop", re.compile(r"\bdrop\s+(?:database|schema|table|index|view|materialized\s+view)\b", re.I)),
    ("truncate", re.compile(r"\btruncate\s+(?:table|schema|database)\b", re.I)),
    # Narrowed: require "destroy" adjacent to a managed object (either
    # "destroy <object>" or "<object> destroy") to avoid false positives.
    ("destroy", re.compile(r"\b(?:destroy\s+(?:volume|container|image|network|service|instance|vm|disk|pool|namespace)|(?:volume|container|image|network|service|instance|vm|disk|pool|namespace)\s+destroy)\b", re.I)),
)

# Commands whose entire purpose is to produce text output. Scanning their
# arguments for destructive keywords produces false positives (echoing
# "DROP TABLE" for documentation). These are excluded from detection when
# they are the command in a segment, not when they merely begin a compound
# command.
_OUTPUT_COMMANDS: re.Pattern[str] = re.compile(
    r"^\s*(?:echo|printf|cat|tee|wall)\b", re.I,
)


def _heredoc_free(command: str) -> str:
    """Remove here-document bodies while retaining the shell command lines.

    This deliberately handles the common ``<<WORD``/``<<-WORD`` form only.
    Full shell parsing is out of scope, but treating an obvious here-document
    as data is preferable to scanning its contents as a command.
    """
    lines = command.splitlines(keepends=True)
    result: list[str] = []
    skip_until: str | None = None
    strip_tabs = False
    for line in lines:
        if skip_until is not None:
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == skip_until:
                skip_until = None
            continue
        result.append(line)
        # Find a here-doc operator outside quotes on this command line.  The
        # delimiter grammar is intentionally conservative; unsupported forms
        # fail open rather than pretending to be parsed.
        quote: str | None = None
        operator: int | None = None
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\" and quote == '"':
                    index += 2
                    continue
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif line.startswith("<<", index):
                operator = index
                break
            index += 1
        if operator is not None:
            rest = line[operator + 2:]
            delimiter = re.match(r"(-?)\s*(['\"]?)([^\s'\"]+)\2", rest)
            if delimiter:
                skip_until = delimiter.group(3)
                strip_tabs = bool(delimiter.group(1))
    return "".join(result)


def _substitution_end(text: str, start: int) -> int | None:
    """Return the closing parenthesis for ``$(`` at *start*, if balanced."""
    depth = 1
    quote: str | None = None
    escaped = False
    index = start + 2
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif text.startswith("$(", index):
            depth += 1
            index += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _shell_segments(command: str) -> tuple[str, ...]:
    """Lex command segments, excluding quoted data and extracting ``$(...)``.

    This is a deliberately small lexer, not a shell interpreter.  It knows
    quoting, escapes, separators, here-document bodies, and command
    substitution.  Aliases, variables, functions, arithmetic expansion, and
    other shell semantics remain outside this detector's supported boundary.
    """
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    text = _heredoc_free(command)
    index = 0

    def finish() -> None:
        segment = "".join(current).strip()
        if segment:
            segments.append(segment)
        current.clear()

    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if char == "\\":
                escaped = True
                index += 1
                continue
            if text.startswith("$(", index):
                end = _substitution_end(text, index)
                if end is None:
                    # An incomplete expansion is not reliable evidence.
                    return tuple(segments)
                segments.extend(_shell_segments(text[index + 2:end]))
                index = end + 1
                continue
            if char == '"':
                quote = None
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            continue
        if text.startswith("$(", index):
            end = _substitution_end(text, index)
            if end is None:
                return tuple(segments)
            segments.extend(_shell_segments(text[index + 2:end]))
            index = end + 1
            continue
        # Treat all shell compound-command separators alike.  In particular,
        # split both ``&&`` (logical AND) and ``&`` (background execution) so
        # an output-only command cannot hide a destructive trailing segment.
        # Repeated separators naturally produce an empty segment, which is
        # ignored by ``finish``.
        if char in ";|&\n":
            finish()
        else:
            current.append(char)
        index += 1
    if quote is not None or escaped:
        # Fail open for malformed shell syntax.
        return tuple(segments)
    finish()
    return tuple(segments)


def _command_text(tool_name: str, args: Any) -> str:
    """Extract shell/SQL text without treating arbitrary tool metadata as code."""
    if not isinstance(args, Mapping):
        return ""
    if tool_name not in {"terminal", "shell", "execute", "run", "exec"}:
        return ""
    for key in ("command", "cmd", "script"):
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def detect_destructive(tool_name: str, args: Any) -> DestructiveMatch | None:
    """Return the first destructive pattern matched by a shell-like call.

    Known limitation: this small lexer cannot catch all obfuscated destructive
    commands (aliases, variables, functions, and unsupported shell semantics).
    Command substitution is supported and scanned recursively. This is a
    best-effort first line of defense — the fail-open design ensures unknown
    patterns pass through to Hermes' existing approval gate rather than
    executing silently. Do not rely on this as a security boundary.
    """
    command = _command_text(tool_name, args)
    if not command:
        return None
    for segment in _shell_segments(command):
        if _OUTPUT_COMMANDS.match(segment):
            continue
        for action_class, pattern in _PATTERNS:
            if pattern.search(segment):
                return DestructiveMatch(action_class, command, action_class)
    return None


def build_router_task(match: DestructiveMatch, *, task_id: str = "") -> RouterTask:
    """Project a detector match into the bridge's transport-safe task shape."""
    task_id = task_id.strip() if isinstance(task_id, str) else ""
    if not task_id:
        # The hook normally receives a task id.  This deterministic fallback is
        # only for direct callers and keeps the detector useful in unit tests.
        task_id = f"hitl-gate:{match.action_class}:{abs(hash(match.command))}"
    return RouterTask.from_mapping({
        "task_id": task_id,
        "objective": match.command,
        "scope": ("destructive-command",),
        "exclusions": (),
        "risk_class": "high",
        "capabilities": ("delete",),
        "action_class": match.action_class,
        "fork_description": f"Execute destructive {match.action_class} command: {match.command}",
        "recommended_option": "Require explicit human approval before execution",
        "options": ("Require explicit human approval before execution", "Abort"),
        "trade_off": "Approval preserves operator control; abort leaves the target unchanged",
        "revert_path": "Abort the command and restore from the relevant backup or rollback path",
        "idempotency_key": task_id,
    })


__all__ = ["DestructiveMatch", "build_router_task", "detect_destructive"]
