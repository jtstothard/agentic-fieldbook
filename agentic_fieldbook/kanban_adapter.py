"""Experimental adapter over Hermes' existing Kanban CLI.

This is deliberately a thin, isolated prototype: it owns no board backend and
writes only to the caller-provided Hermes home/board.  The JSON returned here is
observational evidence for deriving a later stable adapter contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any


class KanbanAdapterError(RuntimeError):
    """A named failure from the experimental Kanban lifecycle."""


class KanbanAdapter:
    """Run the real Hermes Kanban lifecycle against an isolated board."""

    def __init__(self, *, home: Path, board: str = "shadow") -> None:
        self.home = Path(home)
        self.board = board
        # Hermes' SQLite claim is atomic across processes, but the adapter can
        # also be called concurrently by several threads.  Serialize the
        # claim-and-observe sequence so a thread cannot observe the winner's
        # ``running`` state after another thread has already claimed the task.
        # This is an adapter-level ownership gate; the CLI remains the source
        # of truth for claims made by other adapter instances/processes.
        self._claim_lock = threading.Lock()
        self.home.mkdir(parents=True, exist_ok=True)
        self._run("kanban", "init")
        boards = self._run("kanban", "boards", "list").stdout
        if board not in boards:
            self._run("kanban", "boards", "create", board)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(self.home)
        # An ambient DB pin would defeat shadow-board isolation.
        env.pop("HERMES_KANBAN_DB", None)
        env.pop("HERMES_KANBAN_HOME", None)
        env["HERMES_KANBAN_BOARD"] = self.board
        return env

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["hermes", *args],
            env=self._env(),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise KanbanAdapterError(f"kanban {args[0]} failed: {detail}")
        return completed

    @staticmethod
    def _json(output: str) -> Any:
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise KanbanAdapterError(f"kanban returned invalid JSON: {output!r}") from exc

    def create(
        self,
        title: str,
        *,
        assignee: str | None,
        workspace: str = "scratch",
        branch: str | None = None,
    ) -> dict[str, Any]:
        if workspace == "worktree" and branch and any(ch.isspace() for ch in branch):
            raise KanbanAdapterError("worktree branch must not contain whitespace")
        args = ["kanban", "create", title, "--workspace", workspace, "--json"]
        if assignee:
            args += ["--assignee", assignee]
        if branch:
            args += ["--branch", branch]
        return self._json(self._run(*args).stdout)

    def claim(self, task_id: str, *, ttl: int | None = None) -> dict[str, Any]:
        with self._claim_lock:
            args = ["kanban", "claim", task_id]
            if ttl is not None:
                args += ["--ttl", str(ttl)]

            # Do not infer ownership from ``show``: it reports shared task
            # state, so a loser can otherwise mistake the winner's running
            # task for its own.  Hermes 0.19.0's claim command has no JSON
            # response; its atomic claim result is the process result and
            # output, both of which must be inspected before polling.
            completed = subprocess.run(
                ["hermes", *args],
                env=self._env(),
                text=True,
                capture_output=True,
                check=False,
            )
            semantic_loss = "cannot claim" in (completed.stdout + completed.stderr).lower()
            if completed.returncode != 0 or semantic_loss:
                if semantic_loss:
                    raise KanbanAdapterError("lost")
                detail = (completed.stderr or completed.stdout).strip()
                raise KanbanAdapterError(f"kanban claim failed: {detail}")

            if not completed.stdout.startswith("Claimed "):
                raise KanbanAdapterError(
                    f"kanban claim returned unexpected output: {completed.stdout!r}"
                )
            return self.poll(task_id)

    def poll(self, task_id: str) -> dict[str, Any]:
        return self._json(self._run("kanban", "show", task_id, "--json").stdout)["task"]

    def read_result(self, task_id: str) -> str | None:
        return self.poll(task_id).get("result")

    def dispatch(self, *, dry_run: bool = True) -> dict[str, Any]:
        args = ["kanban", "dispatch", "--json"]
        if dry_run:
            args.append("--dry-run")
        report = self._json(self._run(*args).stdout)
        anomalies = []
        if report.get("skipped_unassigned"):
            anomalies.append({"kind": "unassigned", "tasks": report["skipped_unassigned"]})
        if report.get("skipped_nonspawnable"):
            anomalies.append({"kind": "non_spawnable", "tasks": report["skipped_nonspawnable"]})
        report["anomalies"] = anomalies
        return report

    def handle_failure(self, task_id: str, reason: str) -> dict[str, str]:
        # Pass the reason as one CLI argument for compatibility with Hermes
        # versions whose parser treats the positional reason as a single value.
        self._run("kanban", "block", task_id, "--kind", "transient", reason)
        return {"operation": "handle_failure", "task_id": task_id, "reason": reason}
