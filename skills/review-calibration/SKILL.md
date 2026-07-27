---
name: review-calibration
description: "Reviewer calibration protocol and evaluation suite design for the agentic operating system. Defines how reviewer lanes are calibrated on a blinded suite, how independence is proven, and how disagreements are adjudicated. Load when setting up reviewer calibration, defining review depth, or adjudicating conflicting reviews."
---

# Agentic Operating System — Review Calibration Protocol

## When to load

- Setting up or running reviewer calibration.
- Determining review depth (how many reviewers, what independence level).
- Adjudicating conflicting reviews.
- Checking recalibration triggers for a review lane.

## Review depth by risk

| Risk | Reviewers |
|---|---|
| **Low** | Automated checks, or one independent reviewer. |
| **Medium** | One genuinely independent reviewer + automated verification; different context and preferably different model/provider family. |
| **High** | Two independent reviewers, including at least one strong reasoning lane, + automated verification + human approval. |
| **Critical blast radius** | Add a third reviewer only when impact justifies the cost. |

**Never use majority vote as proof.** One valid defect outweighs multiple approvals. If one reviewer finds a real defect and two approve, the defect stands.

## Independence definition

A review is genuinely independent when ALL of these hold:

- **Fresh context** — the reviewer has no access to the implementer's private reasoning or session history.
- **Frozen review input** — the reviewer sees the exact diff, artifact, plan, or system state, not a summary filtered by the implementer.
- **Explicit review scope** — the reviewer knows exactly what to check, with an adversarial attack lens (what could be wrong?).
- **No pre-coordination** — the reviewer has not discussed the work with the implementer before producing their initial finding.
- **Separate reviewer identity** — recorded as a distinct lane/profile.
- **Different model/provider family** — where risk warrants (high-risk requires this; medium-risk prefers it).
- **Independent evidence collection** — the reviewer verifies claims independently, not by trusting the implementer's evidence.

**Same-model delegation is labeled context-independent, not automatically model-independent.** A `worker` lane reviewing `coder` work on the same model is context-independent (fresh session) but not model-independent. This is acceptable for low-risk, noted but acceptable for medium, and insufficient for high-risk.

## Calibration suite design

### Task selection criteria

The blinded evaluation suite contains:

- **Known defects** — tasks with planted bugs, security holes, logic errors, or missing edge cases. The reviewer must find these.
- **Ambiguous cases** — tasks where reasonable reviewers might disagree (style choices, minor optimizations, debatable correctness). Tests how the reviewer handles uncertainty.
- **Clean controls** — tasks with no defects. Tests the false-positive rate (does the reviewer invent problems?).
- **Domain coverage** — representative tasks across coding, research, ops, and automation domains.

Each suite item has:
- A frozen input (diff, artifact, plan, or system state).
- Known defect annotations (hidden from the reviewer).
- Severity labels for each defect.
- Correct disposition (what a calibrated reviewer should find).

### Frozen input format

Inputs are frozen as artifacts — not live sessions. Each input includes:
- The exact artifact under review (commit SHA + diff, file contents, plan document).
- The acceptance criteria from the contract.
- The evidence requirements.
- Nothing else — no implementer reasoning, no session history.

### Blind output collection

- Reviewers produce their findings **before** seeing other reviews or the known answers.
- No coordination between reviewers on the same item.
- Each reviewer runs in a separate context/session.
- Outputs are collected centrally and only compared after all reviewers have submitted.

### Metrics collected

| Metric | What it measures |
|---|---|
| **Severity-weighted recall** | Of the known defects, how many did the reviewer find, weighted by severity? (Missing a critical defect weighs more than missing a minor one.) |
| **False-positive rate** | On clean controls, how often did the reviewer report a defect that doesn't exist? |
| **Evidence quality** | Did the reviewer back each finding with verifiable evidence, or assert without proof? |
| **Cost** | What did the review cost (tokens/compute)? |
| **Latency** | How long did the review take? |

Measure **separately** for:
- Defect-finding ability (recall on tasks with known defects).
- Clean-approval ability (false-positive rate on clean controls).

A reviewer good at finding bugs but who cries wolf on clean code is less useful than one with balanced performance.

## Disagreement adjudication

When reviewers conflict (one finds a defect, another approves):

1. **Preserve blind findings** — do not show reviewers each other's output until both have submitted.
2. **Classify the disagreement** — is it a factual error, a judgment call, or a scope interpretation?
3. **Run targeted evidence checks** — for factual disputes, verify against the artifact directly.
4. **Human adjudication** — for medium/high-risk or sensitive conflicts, a human makes the call.
5. **Record final disposition** — what was decided and why. This feeds back into calibration (was one reviewer systematically wrong?).

**Never resolve by majority vote.** If one reviewer found a real critical defect and three approved, the task is blocked on that defect.

## Recalibration triggers

Recalibrate a reviewer lane when:

- Model/provider/version changes.
- Tool, prompt, or permission changes.
- A serious defect was missed that the lane should have caught.
- Drift detected (behavior on known tasks has changed).
- Staleness (calibration record past its review window — default 90 days).

Until recalibration completes, **downgrade the lane's trust level** (see `lane-calibration` skill for the downgrade procedure).

## Severity rubric for reviewers

The metrics section measures severity-weighted recall, but **the protocol does not define what each severity level means**. Without a shared rubric, reviewers calibrate severity idiosyncratically. With a standalone binding rubric promoted into the skill and bound into the dispatch template, severity classification is consistent.

The canonical rubric is `references/severity-rubric.md` — a standalone, binding document, not inline text. Read it for the full critical/major/minor definitions, classification rules, and worked examples. Quick orientation:

- **critical** — Exploitable security defect, data loss, RCE, auth bypass, or anything that makes the system unsafe to ship as-is. A "ship it" with this unfixed is wrong.
- **major** — Functional break, security misconfiguration requiring exploitation conditions, or a correctness defect affecting primary behavior. Must fix before merge, but not "system is pwned."
- **minor** — Edge-case bug, cosmetic issue, style/maintainability concern, or robustness gap that rarely manifests. Fix-when-convenient.

Two rules:

1. **Severity is about impact-if-shipped, not which acceptance criterion the defect violates.** Acceptance criteria often read as "critical-sounding" even for minor defects.
2. **A lane is severity-calibrated when ≥50% of findings on known-defect cases match the oracle severity.** Below that, the lane is usable for disposition triage (found / not-found) but **not** for prioritizing fixes, and must not be trusted for high-risk review.

## Operational patterns for running a calibration

Learned patterns for calibration runs. These belong in the protocol, not in per-run memory.

### Blinding dispatch

Each case is reviewed in its **own kanban card / session** — never batched into one reviewer session, because shared context breaks the independence requirement even within the same lane. Dispatch one card per case with a body that enumerates the FORBIDDEN paths explicitly:

- No access to `oracle/` (the answer key)
- No access to other case packets where the ID ≠ this case
- No access to other submissions
- No access to `BUILD-LOG.md` or `run-manifest.yaml`

**Use the dispatch template** at `templates/review-dispatch.md` — it encodes the FORBIDDEN list, the fixed output format, and the mandatory rubric pre-read. Do not write a card body from scratch; copy the template and fill the placeholders. The template binds the severity rubric as a **mandatory pre-read** (the reviewer must read `references/severity-rubric.md` *before* classifying anything) and requires a `rubric_version:` citation field in the output so the scoring pass can confirm it was loaded.

Each reviewer writes to `submissions/<case_id>/review.md` in the fixed format the template specifies (Disposition / Findings with severity-location-evidence-confidence / Summary) so scoring is parseable. **Before accepting a submission, confirm `rubric_version:` is present and non-empty** — if missing, the dispatch is invalid: the lane collapses to poor severity match without the rubric, so a rubric-less review is not a calibrated review.

Use the same reviewer profile per domain across all cases in the set (e.g. `coder` for coding, `worker` for ops), so the lane is what is being calibrated — not a per-case mix.

### Corpus integrity: metadata-drift traps

A calibration corpus is sealed under a manifest with per-packet hashes. Drift traps include:

1. **The cleanup/fix worker touches more than the fix card claims.** A card scoped to a subset of cases also rewrote packet.md for other cases, leaving the manifest's hashes stale. **After any post-seal fix, recompute hashes for ALL packets**, not just the ones the card says it touched. Verify with a hash-match loop, not by trusting the worker's summary.

2. **Oracle summary counts drift from the case lists.** The oracle's summary fields were stale vs the actual case-id lists. **The case-id lists are authoritative; the summary counts are derived metadata.** Trust the lists when deciding which cases belong in which phase.

3. **Oracle entries reference artifact files that were never authored.** The most severe drift trap: oracle entries pointed at planted defects in files that did not exist in the packets. The packets instead contained *different* real artifacts with *different* genuine defects. The reviewers reviewed the artifacts they were actually given and found real defects — just not the planted ones the oracle claimed. **Symptom:** reviewers cite defect locations in files the oracle never mentions; cross-checking `find packets/<case>/ -type f` against the oracle's `location:` fields reveals the gap. **Recovery decision:** rebuild the oracle entries from the actual packet contents + reviewer findings (preserving the blinded reviews), rather than regenerating the packets to match a stale oracle. Rationale: the packets contain real classifiable defects; regenerating throws away valid blinded reviews and reintroduces the crash-prone synthetic-authoring step that caused the gap. See "Oracle–packet reconciliation" below.

### Clean-control false positives: corpus-artifact vs invented

When a reviewer flags a defect on a clean-control case, do not assume a reviewer false positive. **Distinguish:**

- **Invented FP** — the reviewer asserts a defect that the code does not actually contain. This is a reviewer calibration problem (over-flagging) and feeds the FP-rate metric.
- **Corpus-artifact FP** — the reviewer found a *real* bug that the synthetic-code author introduced unintentionally. This is a corpus quality problem, not a reviewer error. The reviewer was technically correct; the "clean" case wasn't actually clean.

The one clean-control FP found historically was a corpus artifact — a genuine boundary bug. Treating it as a reviewer FP would have wrongly penalized a correctly-behaving reviewer.

Resolution: patch the artifact so the clean control is genuinely clean, OR reclassify the case as ambiguous. Do not silently score it as a reviewer FP.

### Ambiguous-case over-flagging

On cases the oracle marks `uncertain_or_approve` (genuinely debatable code), a calibrated reviewer should sit on the fence — disposition `uncertain`. A lane that returns `find_defect` with multiple high-confidence findings on these cases is **over-flagging ambiguity**, not exercising rigor. Treat this as a distinct calibration signal from clean-control FP rate.

### Phase ordering

Never run the held-out confirmation set until the main-set calibration passes the thresholds you care about — otherwise you are confirming a known-bad calibration. The held-out set is a finite resource: each run consumes it, and re-running after a prompt change no longer tests generalization, it tests overfit.

## Remediation sequence when a lane fails severity calibration

The intervention that followed a failed calibration is a reusable sequence — do these steps in order, not ad hoc:

1. **Score first, then patch the corpus.** Before changing anything, produce the full `scoring.md` against the current corpus so the baseline is recorded. You need the numbers to know if the remediation worked.
2. **Fix corpus-artifact false positives before changing prompts.** If a clean-control case had a real unintended bug, patch the artifact so the clean control is genuinely clean — otherwise you cannot tell whether later FPs are reviewer over-flagging or corpus noise.
3. **Author a binding severity rubric as a frozen input.** The canonical rubric now lives at `references/severity-rubric.md` (promoted out of ephemeral run directories so it survives cleanup). It is not a sentence in the dispatch prompt — it is a standalone document with (a) explicit critical/major/minor definitions, (b) a "when in doubt, choose the higher level and flag confidence" rule, (c) **worked examples drawn from exact cases**. The worked examples are the load-bearing part: a reviewer that flattened critical→major learns fastest from seeing its own mislabel named as critical in the rubric. The dispatch template (`templates/review-dispatch.md`) binds it as a mandatory pre-read with a `rubric_version:` citation field.
4. **Re-seal the manifest** after any corpus patch or rubric addition: recompute per-packet hashes for ALL packets, add the rubric to `inputs:` with its sha256, bump `corpus_revision` and `sealed_at`.
5. **Re-run with the rubric bound into the dispatch prompt** — the card body must (a) tell the reviewer to read the rubric FIRST, before classifying, and (b) cite the rubric path in the output (`rubric_version:`) so the scoring pass can confirm it was loaded.
6. **Do NOT re-run the main set.** The main set is now a trained-on artifact once the rubric references its mislabels. Run the **held-out set** — if severity match improves there, the rubric generalizes; if not, prompt-level guidance is insufficient and you need a different intervention (in-prompt few-shot examples, or a different reviewer model family).

## Reviewer mutation rights

- Reviewers are **read-only by default**. They cannot replace the artifact they are evaluating.
- Reviewers may create **proposed patches as separate artifacts** (not applied to the working branch).
- Fixes are applied by a **separate fixer role**, not the reviewer.
- Low-risk work may combine review-and-fix **only if** the contract explicitly permits it AND automated checks cover the combined operation.

## Relationship to other skills

- **lane-calibration** — stores calibration results and trust levels.
- **contract-schema** — defines acceptance criteria and evidence requirements that reviewers check against.
- **stage-handoff** — provides the frozen input format for reviewer handoffs.

## Support files

- `templates/review-dispatch.md` — **the dispatch template.** Copy, don't rewrite. Encodes FORBIDDEN blinding list, fixed output format, mandatory rubric pre-read, and `rubric_version:` citation field.
- `references/severity-rubric.md` — **canonical severity rubric.** Binding on all review dispatches. Hard dependency for severity-calibrated review.
- `references/scoring-template.md` — scoring table templates (defect recall, clean-control FP with corpus-artifact split, ambiguous calibration) plus a worked example and the oracle–packet reconciliation procedure.