"""
Stale-issue checklist for candidate selection (#47).

Before the router dispatches an issue it must finish two checks, and an
issue becomes dispatchable only when both have run and passed:

1. ``defect_present``: the code the issue points at still contains the
   defect. Run ``git grep`` for it, or read the file and record what you saw.
2. ``no_recent_closing_commit``: no commit merged in the lookback window
   (7 days by default) closes or mentions the issue. If a commit mentions
   it, read that commit and acknowledge its SHA before the check can pass.

A check that was skipped counts as not passed, so skipping one blocks
dispatch. A plain warning in the skill text did not stop the v0.2.2 dogfood
router from picking an issue that was already fixed. This module makes the
check a gate.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

DEFAULT_LOOKBACK_DAYS = 7

DEFECT_PRESENT = "defect_present"
NO_RECENT_CLOSING_COMMIT = "no_recent_closing_commit"

_CLOSING_KEYWORDS = (
    "close", "closes", "closed",
    "fix", "fixes", "fixed",
    "resolve", "resolves", "resolved",
)

_MAX_EVIDENCE_LINES = 5


class CheckStatus(str, Enum):
    """Outcome of one checklist item."""
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class CommitRecord:
    """A commit on the branch the issue would be fixed on."""
    sha: str
    committed_at: datetime  # timezone-aware
    subject: str
    body: str = ""

    @property
    def message(self) -> str:
        return f"{self.subject}\n{self.body}"


@dataclass
class ChecklistItem:
    """One stale-issue checklist item and the evidence behind its status."""
    key: str
    question: str
    status: CheckStatus
    evidence: str


@dataclass
class StaleIssueVerdict:
    """Result of the stale-issue checklist for one candidate issue."""
    issue_number: int
    items: List[ChecklistItem] = field(default_factory=list)

    @property
    def dispatchable(self) -> bool:
        """True only when every item ran and passed."""
        return bool(self.items) and all(i.status == CheckStatus.PASSED for i in self.items)

    @property
    def blocking_items(self) -> List[ChecklistItem]:
        return [i for i in self.items if i.status != CheckStatus.PASSED]

    def to_markdown(self) -> str:
        """Render the checklist for a dispatch record or issue comment."""
        lines = [f"Stale-issue checklist for #{self.issue_number}:"]
        for item in self.items:
            box = "x" if item.status == CheckStatus.PASSED else " "
            lines.append(f"- [{box}] {item.question} ({item.status.value}): {item.evidence}")
        lines.append("Dispatch: " + ("allowed" if self.dispatchable else "blocked"))
        return "\n".join(lines)


def _reference_pattern(issue_number: int) -> re.Pattern:
    # "#44" but not "#440", "abc#44" or "org/repo#44" from another repo.
    return re.compile(rf"(?<![\w/])#{issue_number}(?!\d)")


def _closing_pattern(issue_number: int) -> re.Pattern:
    keywords = "|".join(_CLOSING_KEYWORDS)
    return re.compile(rf"\b(?:{keywords})\b:?\s+#{issue_number}(?!\d)", re.IGNORECASE)


def find_referencing_commits(
    issue_number: int,
    commits: Iterable[CommitRecord],
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> List[CommitRecord]:
    """Return commits inside the lookback window that mention the issue."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    ref = _reference_pattern(issue_number)
    return [c for c in commits if c.committed_at >= cutoff and ref.search(c.message)]


def check_no_recent_closing_commit(
    issue_number: int,
    commits: Iterable[CommitRecord],
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    acknowledged_shas: Sequence[str] = (),
) -> ChecklistItem:
    """Checklist item 2: no merged commit in the window closes the issue.

    A commit with a closing keyword ("fixes #N") always fails the check.
    A plain mention ("refs #N", "(#N)") fails until the router has read
    that commit and passes its SHA (or a unique prefix of it) in
    ``acknowledged_shas``, confirming it does not fix the issue.
    """
    question = f"No commit merged in the last {lookback_days} days already closes the issue"
    closing = _closing_pattern(issue_number)
    referencing = find_referencing_commits(issue_number, commits, now, lookback_days)

    def acknowledged(commit: CommitRecord) -> bool:
        return any(len(a) >= 7 and commit.sha.startswith(a) for a in acknowledged_shas)

    closers = [c for c in referencing if closing.search(c.message)]
    if closers:
        shown = ", ".join(f"{c.sha[:7]} {c.subject!r}" for c in closers)
        return ChecklistItem(NO_RECENT_CLOSING_COMMIT, question, CheckStatus.FAILED,
                             f"closing commit(s) already merged: {shown}")

    unreviewed = [c for c in referencing if not acknowledged(c)]
    if unreviewed:
        shown = ", ".join(f"{c.sha[:7]} {c.subject!r}" for c in unreviewed)
        return ChecklistItem(NO_RECENT_CLOSING_COMMIT, question, CheckStatus.FAILED,
                             f"commit(s) mention #{issue_number}; read them and acknowledge "
                             f"their SHAs if they do not fix it: {shown}")

    note = f"no commit in the last {lookback_days} days mentions #{issue_number}"
    if referencing:
        note = (f"{len(referencing)} mentioning commit(s) read and acknowledged as "
                f"not fixing #{issue_number}")
    return ChecklistItem(NO_RECENT_CLOSING_COMMIT, question, CheckStatus.PASSED, note)


def check_defect_present_by_grep(
    repo: Union[str, Path],
    pattern: str,
    paths: Sequence[str] = (),
    fixed_string: bool = True,
    ref: Optional[str] = None,
) -> ChecklistItem:
    """Checklist item 1, greppable defects: ``git grep`` for the defect.

    Passes when the pattern still matches, and fails when it does not
    (the defect has probably been fixed already). Any git error leaves
    the item NOT_RUN, which still blocks dispatch.
    """
    question = "Target code still contains the described defect"
    if not pattern:
        return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.NOT_RUN, "no grep pattern given")
    cmd = ["git", "-C", str(repo), "grep", "-n", "-I"]
    cmd.append("-F" if fixed_string else "-E")
    cmd += ["-e", pattern]
    if ref:
        cmd.append(ref)
    cmd.append("--")
    cmd += list(paths)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.NOT_RUN, f"git grep failed to run: {exc}")
    if proc.returncode == 0:
        hits = proc.stdout.splitlines()
        shown = "; ".join(hits[:_MAX_EVIDENCE_LINES])
        more = f" (+{len(hits) - _MAX_EVIDENCE_LINES} more)" if len(hits) > _MAX_EVIDENCE_LINES else ""
        return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.PASSED,
                             f"git grep {pattern!r} matched {len(hits)} line(s): {shown}{more}")
    if proc.returncode == 1:
        return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.FAILED,
                             f"git grep {pattern!r} found nothing; the defect may already be fixed")
    return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.NOT_RUN,
                         f"git grep exited {proc.returncode}: {proc.stderr.strip()}")


def check_defect_present_by_reading(evidence: str, still_present: bool) -> ChecklistItem:
    """Checklist item 1, for defects grep cannot find: record what you read.

    ``evidence`` names the file and lines read and what they showed. With
    no evidence the item stays NOT_RUN, so the router cannot just assert it.
    """
    question = "Target code still contains the described defect"
    if not evidence.strip():
        return ChecklistItem(DEFECT_PRESENT, question, CheckStatus.NOT_RUN,
                             "no evidence recorded from reading the target code")
    status = CheckStatus.PASSED if still_present else CheckStatus.FAILED
    return ChecklistItem(DEFECT_PRESENT, question, status, evidence.strip())


def git_recent_commits(
    repo: Union[str, Path],
    ref: str = "HEAD",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> List[CommitRecord]:
    """Read commits from the last ``lookback_days`` on ``ref`` (e.g. ``origin/main``)."""
    fmt = "%H%x1f%cI%x1f%s%x1f%b%x1e"
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", f"--since={lookback_days} days ago", f"--format={fmt}", ref],
        capture_output=True, text=True, check=True,
    )
    commits = []
    for record in proc.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, date, subject, body = record.split("\x1f", 3)
        commits.append(CommitRecord(sha, datetime.fromisoformat(date), subject, body.strip()))
    return commits


def evaluate_candidate(
    issue_number: int,
    defect_check: Optional[ChecklistItem],
    commits: Iterable[CommitRecord],
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    acknowledged_shas: Sequence[str] = (),
) -> StaleIssueVerdict:
    """Run the stale-issue checklist for one candidate issue.

    ``defect_check`` comes from ``check_defect_present_by_grep`` or
    ``check_defect_present_by_reading``. Passing None records item 1 as
    NOT_RUN, which blocks dispatch.
    """
    if defect_check is None:
        defect_check = ChecklistItem(DEFECT_PRESENT, "Target code still contains the described defect",
                                     CheckStatus.NOT_RUN, "defect check was not run")
    commit_check = check_no_recent_closing_commit(
        issue_number, commits, now, lookback_days, acknowledged_shas
    )
    return StaleIssueVerdict(issue_number, [defect_check, commit_check])
