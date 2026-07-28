"""Experimental adapter over Hermes' existing Kanban CLI.

This is deliberately a thin, isolated prototype: it owns no board backend and
writes only to the caller-provided Hermes home/board.  The JSON returned here is
observational evidence for deriving a later stable adapter contract.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class KanbanAdapterError(RuntimeError):
    """A named failure from the experimental Kanban lifecycle."""


class KanbanAdapter:
    """Run the real Hermes Kanban lifecycle against an isolated board."""

    def __init__(self, *, home: Path, board: str = "shadow") -> None:
        self.home = Path(home)
        self.board = board
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
        args = ["kanban", "claim", task_id]
        if ttl is not None:
            args += ["--ttl", str(ttl)]
        try:
            completed = self._run(*args)
        except KanbanAdapterError as exc:
            # Older Hermes CLI versions report a rejected claim as a non-zero
            # process result. Polling after that failure would incorrectly
            # report the winner's ``running`` task as our own claim.
            if "cannot claim" in str(exc):
                raise KanbanAdapterError("lost") from exc
            raise

        # Hermes 0.19.0 can write ``cannot claim ...`` to stderr while still
        # exiting zero. Treat that semantic CLI failure exactly like the
        # non-zero form; otherwise the subsequent poll observes the winner.
        if "cannot claim" in (completed.stdout + completed.stderr):
            raise KanbanAdapterError("lost")
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
        self._run("kanban", "block", task_id, "--kind", "transient", reason)
        return {"operation": "handle_failure", "task_id": task_id, "reason": reason}
