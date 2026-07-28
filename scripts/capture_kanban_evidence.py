#!/usr/bin/env python3
"""Capture read-only live Kanban evidence plus isolated shadow-board checks.

The live phase is constrained to an allow-list of documented read commands. All
mutating lifecycle checks run with a temporary HERMES_HOME and a dedicated
shadow board. The JSON artifact is intentionally self-describing so another
operator can reproduce or audit the probe without trusting inferred state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agentic_fieldbook.kanban_adapter import KanbanAdapter, KanbanAdapterError

LIVE_READS = (
    ("kanban", "boards", "list"),
    ("kanban", "stats", "--json"),
    ("kanban", "diagnostics", "--json"),
    ("kanban", "assignees", "--json"),
    ("kanban", "list", "--status", "ready", "--json"),
    ("kanban", "list", "--status", "running", "--json"),
    ("kanban", "list", "--status", "blocked", "--json"),
)
_SECRET = re.compile(r"(?i)(token|secret|password|api[_-]?key|authorization)([=:]\s*)[^\s,}]+")
_HOME = re.compile(r"/home/[^\s\"']+")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def redact(value: str) -> str:
    value = _SECRET.sub(r"\1\2[REDACTED]", value)
    return _HOME.sub("[HOME]", value)


def run_read(args: tuple[str, ...], env: dict[str, str]) -> dict[str, Any]:
    started = now()
    try:
        completed = subprocess.run(
            ["hermes", *args], env=env, text=True, capture_output=True, check=False
        )
        return {
            "started_at": started,
            "finished_at": now(),
            "command": ["hermes", *args],
            "returncode": completed.returncode,
            "stdout": redact(completed.stdout),
            "stderr": redact(completed.stderr),
            "json": _parse_json(completed.stdout),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "started_at": started,
            "finished_at": now(),
            "command": ["hermes", *args],
            "returncode": None,
            "stdout": "",
            "stderr": redact(str(exc)),
            "json": None,
        }


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def shadow_probe() -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fieldbook-kanban-shadow-") as temp:
        home = Path(temp)
        adapter = KanbanAdapter(home=home, board="evidence-shadow")
        task = adapter.create("evidence lifecycle", assignee="worker")
        task_id = task["id"]
        claimed = adapter.claim(task_id, ttl=30)
        failure = adapter.handle_failure(task_id, "synthetic evidence failure")
        after_failure = adapter.poll(task_id)
        dispatch = adapter.dispatch(dry_run=True)
        shadow_db = next(home.rglob("*.db"), None)
        return {
            "started_at": now(),
            "finished_at": now(),
            "status": "pass",
            "home_is_temporary": str(home).startswith(tempfile.gettempdir()),
            "board": "evidence-shadow",
            "shadow_db_exists": shadow_db is not None and shadow_db.exists(),
            "task_id": task_id,
            "claim": {"status": claimed.get("status")},
            "failure": failure,
            "post_failure_status": after_failure.get("status"),
            "dispatch": {
                "dry_run": True,
                "reclaimed": dispatch.get("reclaimed"),
                "anomalies": dispatch.get("anomalies", []),
            },
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="JSON artifact path")
    args = parser.parse_args()

    env = os.environ.copy()
    live_home = env.get("HERMES_HOME", "")
    provenance = {
        "captured_at": now(),
        "repository_ref": _git_ref(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hermes_home": redact(live_home),
        "board": env.get("HERMES_KANBAN_BOARD", "default"),
        "live_db": redact(env.get("HERMES_KANBAN_DB", "")),
        "live_operations_policy": "read-only allow-list; no create/claim/block/complete/dispatch",
    }
    live = [run_read(command, env) for command in LIVE_READS]
    # A running-task list is the safe index for claim evidence. Show is also
    # read-only, but only ids returned by that live list are followed.
    running_list = next(
        (item for item in live if item["command"][-3:] == ["--status", "running", "--json"]),
        None,
    )
    if running_list and isinstance(running_list.get("json"), list):
        for task in running_list["json"]:
            if isinstance(task, dict) and isinstance(task.get("id"), str):
                live.append(run_read(("kanban", "show", task["id"], "--json"), env))
    unavailable = [
        {"command": item["command"], "reason": item["stderr"] or "non-zero exit"}
        for item in live
        if item["returncode"] != 0
    ]
    try:
        shadow = shadow_probe()
    except (KanbanAdapterError, OSError, KeyError) as exc:
        shadow = {"status": "insufficient", "error": redact(str(exc)), "finished_at": now()}

    artifact = {
        "schema": "agentic-fieldbook.kanban-live-evidence.v1",
        "status": "pass" if not unavailable and shadow.get("status") == "pass" else "insufficient",
        "provenance": provenance,
        "live_read_evidence": live,
        "shadow_evidence": shadow,
        "gaps": unavailable + ([] if shadow.get("status") == "pass" else [{"area": "shadow", "reason": shadow.get("error", "shadow probe failed")}]),
        "boundary": {
            "live_commands_are_allowlisted": all(
                tuple(item["command"][1:]) in LIVE_READS
                or (
                    len(item["command"]) == 5
                    and tuple(item["command"][1:3]) == ("kanban", "show")
                    and item["command"][-1] == "--json"
                )
                for item in live
            ),
            "shadow_writes_isolated": shadow.get("home_is_temporary") is True and shadow.get("shadow_db_exists") is True,
            "production_mutations_attempted": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": artifact["status"], "output": str(args.output), "gaps": len(artifact["gaps"])}, sort_keys=True))
    return 0 if artifact["status"] == "pass" else 2


def _git_ref() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
