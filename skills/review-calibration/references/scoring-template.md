# Calibration scoring template

Use as a template for future scoring passes — copy the table shapes, not the numbers.

## Directory layout (expected)

```
calibration/run-<date>/
  oracle/cases.private.yaml     # answer key — reviewers never see this
  frozen_inputs/                # contracts + metric envelope, hash-pinned
  packets/C-0XX/                # one dir per case: packet.md + artifact files
    packet.md                   # review contract + acceptance criteria (public)
    src/...                     # artifact under review
  submissions/C-0XX/review.md   # reviewer output (one per case)
  run-manifest.yaml             # sealed_at, corpus_revision, per-packet sha256
  scoring.md                    # this file — oracle-aligned scoring
```

## Reviewer output format (enforce in dispatch)

```markdown
# Blind Review: <case_id>
reviewer_lane: <profile>
timestamp: <ISO 8601>

## Disposition
<approve | find_defect | uncertain>

## Findings
### Finding N
- severity: <critical|major|minor>
- location: <file:line>
- evidence: <description>
- confidence: <high|medium|low>

## Summary
2-3 sentences.
```

Fixed format makes the scoring pass script-parseable.

## Scoring tables

### 1. Defect-finding recall (known-defect cases)

Match each oracle defect to a reviewer finding by location overlap + mechanism match.

| Case | Oracle defect | Oracle sev | Reviewer hit | Sev match | Verdict |
|---|---|---|---|---|---|

Compute four numbers:
- **Disposition recall** — fraction of known-defect cases that returned `find_defect`. (Target: 100%.)
- **Location-precise recall** — fraction where the reviewer cited the exact planted line/region. (Acceptable: ≥75%.)
- **Pattern-found, location-miss** — reviewer found the right defect pattern but cited the wrong line. Counts as found for disposition, not for surgical fix-handoff.
- **Severity-calibration match** — fraction where reviewer severity == oracle severity. (Threshold for lane trust: ≥50%.)

### 2. Clean-control false-positive rate

| Case | Oracle | Reviewer | Verdict |
|---|---|---|---|

Split the verdict column:
- **calibrated** — reviewer approved a genuinely clean case.
- **invented FP** — reviewer asserted a defect the code does not contain. Counts against the reviewer.
- **corpus-artifact FP** — reviewer found a real bug the synthetic author introduced. Counts against the corpus, not the reviewer. Patch the artifact or reclassify the case.

Report reviewer-attributable FP rate separately from corpus-artifact FP rate.

### 3. Ambiguous-case calibration

| Case | Oracle | Reviewer | Verdict |
|---|---|---|---|

Verdict: **calibrated** if disposition is `approve` or `uncertain`; **over-flag** if `find_defect` with multiple high-confidence findings on genuinely debatable code.

## Threshold proposal shape

After scoring, propose per-lane thresholds for the held-out confirmation run:

- Minimum acceptable disposition recall (e.g. 100%)
- Minimum acceptable location-precise recall (e.g. 75%)
- Maximum acceptable severity mismatch (e.g. 50%)
- Maximum acceptable reviewer FP rate (e.g. 33%)
- Maximum acceptable ambiguous over-flag rate (e.g. 33%)

State explicitly whether the lane is: **PASS** (trusted for this risk class), **CONDITIONAL** (trusted for triage, not for prioritization), or **FAIL** (do not use without recalibration).

## Oracle–packet reconciliation (held-out integrity recovery)

When the oracle entries reference artifact files that do not exist in the packets (metadata drift), you must reconcile before scoring. The two paths:

### Option A — rebuild the oracle to match the packets (PREFERRED when packets contain real defects)

Use when the actual packet contents contain genuine, classifiable defects (not junk). This preserves the blinded reviews already collected and avoids re-running the crash-prone synthetic authoring step.

Steps:
1. For each affected case, inspect the actual packet contents (`find packets/<case>/ -type f` + read the files, or read the inline `## Artifact Contents` block in `packet.md`).
2. Cross-reference against the reviewer's findings — the reviewer already found the real defects in the actual artifacts. Use the reviewer's findings as a draft, but independently verify each finding is a real defect (not an invented FP) before promoting it to an oracle entry.
3. Rewrite the oracle entry: update `domain`, `location`, `mechanism`, `severity`, `expected_finding_keywords`, and `source_refs` to match reality. Add a comment noting the rebuild date and reason.
4. Re-seal the manifest (the oracle hash changed).
5. Score normally.

**Epistemic caveat:** this is weaker than "planted defect, blind retrieval." The oracle was partly derived from the reviews being scored against it. The recall signal is still valid (reviewers were blinded to each other and to the original oracle), but the circularity must be recorded in the scoring doc. Flag which cases retain the original planted-defect structure (fully prospective) vs which were rebuilt.

### Option B — regenerate the packets to match the oracle (use only when packets are junk)

Use when the actual packet contents are unusable (placeholder, corrupted, or contain no real defects). This throws away the blinded reviews and requires re-running the reviewer dispatch. Avoid unless necessary — synthetic defect authoring is the step that historically crashes.