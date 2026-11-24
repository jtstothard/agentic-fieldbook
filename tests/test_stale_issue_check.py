"""
Tests for the stale-issue candidate-selection checklist (#47).

Tests cover:
- The #44 false pick: an issue already fixed by an unrelated commit is blocked
- Item 1 (defect still present) via git grep and via recorded reading
- Item 2 (no recent closing commit): closing keywords, plain mentions,
  acknowledgement, the lookback window, and issue-number boundaries
- Skipped checks block dispatch
"""

import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from agentic_fieldbook.stale_issue_check import (
    DEFECT_PRESENT,
    NO_RECENT_CLOSING_COMMIT,
    CheckStatus,
    CommitRecord,
    check_defect_present_by_grep,
    check_defect_present_by_reading,
    check_no_recent_closing_commit,
    evaluate_candidate,
    find_referencing_commits,
    git_recent_commits,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def commit(sha, subject, days_ago=1, body=""):
    return CommitRecord(sha=sha, committed_at=NOW - timedelta(days=days_ago), subject=subject, body=body)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def commit_file(repo, name, content, message):
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


class TestWorkedExampleIssue44:
    """The v0.2.2 dogfood false pick: #44 had already been fixed by a
    privacy-hardening commit that never mentioned the issue."""

    def test_already_fixed_issue_is_blocked(self, repo):
        commit_file(repo, "export.py", "log.info('user email %s', user.email)\n", "add export logging")
        commit_file(repo, "export.py", "log.info('user exported')\n", "privacy hardening: stop logging PII")

        defect = check_defect_present_by_grep(repo, "user.email", ["export.py"])
        verdict = evaluate_candidate(44, defect, git_recent_commits(repo))

        # The commit never mentions #44, so item 2 alone would pass. Item 1 catches it.
        assert verdict.items[1].status == CheckStatus.PASSED
        assert verdict.items[0].status == CheckStatus.FAILED
        assert not verdict.dispatchable
        assert "already be fixed" in verdict.items[0].evidence

    def test_live_issue_is_dispatchable(self, repo):
        commit_file(repo, "export.py", "log.info('user email %s', user.email)\n", "add export logging")

        defect = check_defect_present_by_grep(repo, "user.email", ["export.py"])
        verdict = evaluate_candidate(44, defect, git_recent_commits(repo))

        assert verdict.dispatchable
        assert "export.py:1:" in verdict.items[0].evidence


class TestDefectPresentByGrep:
    def test_regex_mode(self, repo):
        commit_file(repo, "a.py", "now = datetime.utcnow()\n", "init")
        item = check_defect_present_by_grep(repo, r"utcnow\(\)", fixed_string=False)
        assert item.key == DEFECT_PRESENT
        assert item.status == CheckStatus.PASSED

    def test_grep_on_ref(self, repo):
        commit_file(repo, "a.py", "bad()\n", "init")
        git(repo, "branch", "old")
        commit_file(repo, "a.py", "good()\n", "fix")
        assert check_defect_present_by_grep(repo, "bad()", ref="old").status == CheckStatus.PASSED
        assert check_defect_present_by_grep(repo, "bad()", ref="main").status == CheckStatus.FAILED

    def test_evidence_is_truncated(self, repo):
        commit_file(repo, "a.py", "bad()\n" * 9, "init")
        item = check_defect_present_by_grep(repo, "bad()")
        assert "matched 9 line(s)" in item.evidence
        assert "(+4 more)" in item.evidence

    def test_git_error_is_not_run(self, tmp_path):
        item = check_defect_present_by_grep(tmp_path / "missing", "x")
        assert item.status == CheckStatus.NOT_RUN

    def test_empty_pattern_is_not_run(self, repo):
        assert check_defect_present_by_grep(repo, "").status == CheckStatus.NOT_RUN


class TestDefectPresentByReading:
    def test_recorded_reading_passes(self):
        item = check_defect_present_by_reading("router.py:88 still retries without a cap", still_present=True)
        assert item.status == CheckStatus.PASSED

    def test_reading_shows_fixed(self):
        item = check_defect_present_by_reading("router.py:88 now caps retries at 3", still_present=False)
        assert item.status == CheckStatus.FAILED

    def test_assertion_without_evidence_is_not_run(self):
        item = check_defect_present_by_reading("   ", still_present=True)
        assert item.status == CheckStatus.NOT_RUN


class TestNoRecentClosingCommit:
    @pytest.mark.parametrize("message", [
        "fix: redact emails (fixes #44)",
        "Closes #44",
        "resolved #44 by dropping the field",
        "chore: tidy\n\nFix: #44",
    ])
    def test_closing_keyword_fails(self, message):
        subject, _, body = message.partition("\n")
        item = check_no_recent_closing_commit(44, [commit("a" * 40, subject, body=body)], NOW)
        assert item.key == NO_RECENT_CLOSING_COMMIT
        assert item.status == CheckStatus.FAILED
        assert "closing commit" in item.evidence

    def test_closing_commit_cannot_be_acknowledged_away(self):
        sha = "a" * 40
        item = check_no_recent_closing_commit(44, [commit(sha, "fixes #44")], NOW, acknowledged_shas=[sha])
        assert item.status == CheckStatus.FAILED

    def test_plain_mention_fails_until_acknowledged(self):
        sha = "b" * 40
        commits = [commit(sha, "refactor exporter, groundwork for #44")]
        assert check_no_recent_closing_commit(44, commits, NOW).status == CheckStatus.FAILED
        item = check_no_recent_closing_commit(44, commits, NOW, acknowledged_shas=[sha[:7]])
        assert item.status == CheckStatus.PASSED
        assert "acknowledged" in item.evidence

    def test_short_acknowledgement_prefix_is_ignored(self):
        sha = "b" * 40
        item = check_no_recent_closing_commit(44, [commit(sha, "groundwork for #44")], NOW, acknowledged_shas=["bbb"])
        assert item.status == CheckStatus.FAILED

    def test_commit_outside_window_is_ignored(self):
        item = check_no_recent_closing_commit(44, [commit("c" * 40, "fixes #44", days_ago=8)], NOW)
        assert item.status == CheckStatus.PASSED

    def test_custom_lookback(self):
        commits = [commit("c" * 40, "fixes #44", days_ago=8)]
        item = check_no_recent_closing_commit(44, commits, NOW, lookback_days=14)
        assert item.status == CheckStatus.FAILED
        assert "14 days" in item.question

    @pytest.mark.parametrize("message", ["fixes #440", "fixes #4", "fixes other/repo#44", "fixes abc#44"])
    def test_other_issue_numbers_do_not_match(self, message):
        assert find_referencing_commits(44, [commit("d" * 40, message)], NOW) == []

    def test_no_commits_passes(self):
        assert check_no_recent_closing_commit(44, [], NOW).status == CheckStatus.PASSED


class TestEvaluateCandidate:
    def test_skipped_defect_check_blocks_dispatch(self):
        verdict = evaluate_candidate(44, None, [], NOW)
        assert verdict.items[0].status == CheckStatus.NOT_RUN
        assert not verdict.dispatchable
        assert [i.key for i in verdict.blocking_items] == [DEFECT_PRESENT]

    def test_closing_commit_blocks_dispatch(self):
        defect = check_defect_present_by_reading("a.py:3 still broken", still_present=True)
        verdict = evaluate_candidate(44, defect, [commit("e" * 40, "fixes #44")], NOW)
        assert not verdict.dispatchable
        assert [i.key for i in verdict.blocking_items] == [NO_RECENT_CLOSING_COMMIT]

    def test_markdown_checklist(self):
        defect = check_defect_present_by_reading("a.py:3 still broken", still_present=True)
        md = evaluate_candidate(44, defect, [commit("e" * 40, "fixes #44")], NOW).to_markdown()
        assert "Stale-issue checklist for #44" in md
        assert "- [x] Target code still contains the described defect (passed)" in md
        assert "- [ ] No commit merged in the last 7 days already closes the issue (failed)" in md
        assert md.endswith("Dispatch: blocked")


class TestGitRecentCommits:
    def test_reads_subject_body_and_date(self, repo):
        (repo / "a.txt").write_text("x\n")
        git(repo, "add", "a.txt")
        git(repo, "commit", "-q", "-m", "subject line", "-m", "body mentions #44")
        commits = git_recent_commits(repo)
        assert len(commits) == 1
        assert commits[0].subject == "subject line"
        assert commits[0].body == "body mentions #44"
        assert commits[0].committed_at.tzinfo is not None
        assert len(commits[0].sha) == 40
