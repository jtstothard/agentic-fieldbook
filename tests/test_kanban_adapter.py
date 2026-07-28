"""Evidence-driven tests for the experimental Hermes Kanban adapter."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from agentic_fieldbook.kanban_adapter import KanbanAdapter, KanbanAdapterError


@pytest.fixture
def adapter(tmp_path):
    home = tmp_path / "hermes"
    return KanbanAdapter(home=home, board="shadow")


def test_full_lifecycle_create_claim_poll_read(adapter):
    task = adapter.create("shadow lifecycle", assignee="worker", workspace="scratch")
    claimed = adapter.claim(task["id"], ttl=30)
    assert claimed["status"] == "running"

    adapter._run("kanban", "complete", task["id"], "--result", "shadow-result")
    result = adapter.poll(task["id"])
    assert result["status"] == "done"
    assert adapter.read_result(task["id"]) == "shadow-result"


def test_concurrent_claim_has_one_winner(adapter):
    task = adapter.create("claim race", assignee="worker")
    results = []

    def claim():
        try:
            results.append(adapter.claim(task["id"], ttl=30)["status"])
        except KanbanAdapterError:
            results.append("lost")

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("running") == 1
    assert results.count("lost") == 1


def test_stale_claim_is_recovered_by_dispatch(adapter):
    task = adapter.create("stale claim", assignee="worker")
    adapter.claim(task["id"], ttl=1)
    time.sleep(2)
    report = adapter.dispatch(dry_run=True)
    assert report["reclaimed"] >= 1


def test_failure_is_named_and_requeues_task(adapter):
    task = adapter.create("failure path", assignee="worker")
    adapter.claim(task["id"], ttl=30)
    report = adapter.handle_failure(task["id"], "synthetic dispatcher failure")
    assert report["operation"] == "handle_failure"
    assert report["reason"] == "synthetic dispatcher failure"
    assert adapter.poll(task["id"])["status"] == "blocked"


def test_worktree_requirement_is_reported(adapter):
    with pytest.raises(KanbanAdapterError, match="worktree"):
        adapter.create("invalid worktree", assignee="worker", workspace="worktree", branch="bad branch")


def test_dispatch_anomaly_is_explicit(adapter):
    task = adapter.create("unassigned", assignee=None)
    report = adapter.dispatch(dry_run=True)
    assert task["id"] in report["skipped_unassigned"]
    assert report["anomalies"]


def test_adapter_never_uses_default_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "ambient"))
    adapter = KanbanAdapter(home=tmp_path / "shadow-home", board="shadow")
    task = adapter.create("isolated", assignee="worker")
    assert task["id"]
    assert not (tmp_path / "ambient" / "kanban.db").exists()
