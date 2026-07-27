# Review Dispatch Template (blinded)

Use this as the body of every reviewer kanban card / session. One card per case — never batch cases into one reviewer session (shared context breaks independence).

Fill the `{{...}}` placeholders. Do not paraphrase the FORBIDDEN list — code it verbatim; reviewers do not infer blinding boundaries.

---

## Review task

You are an independent reviewer. Review the artifact below and produce a structured review. You are read-only: you may not modify the artifact under review. You may propose patches as separate artifacts.

### MANDATORY PRE-READ (do this first, before classifying anything)

1. **Read the Severity Rubric** at `review-calibration/references/severity-rubric.md`.
   - Severity classification is mandatory and binding. Classify each finding as `critical`, `major`, or `minor` strictly per those definitions.
   - When uncertain between two levels, choose the higher severity and flag confidence. Do not invent intermediate severities.
   - Severity tracks real-world impact, not line count: a one-line crypto defect is critical; a style nit is minor.
2. Keep the rubric open while you classify. You must cite it in your output (see `rubric_version` below).

### Artifact under review

- **Path:** `{{artifact_path}}`
- **Type:** {{diff | file | plan | system-state}}
- **Acceptance criteria:** {{from contract, verbatim}}
- **Evidence requirements:** {{what must be verified independently}}

### FORBIDDEN (blinding — do not access)

- `{{run_dir}}/oracle/` — the answer key.
- `{{run_dir}}/packets/C-0XX/` for any case XX ≠ {{this_case}} — other case packets.
- `{{run_dir}}/submissions/` — other reviewers' submissions.
- `{{run_dir}}/BUILD-LOG.md` and `{{run_dir}}/run-manifest.yaml`.

### Output

Write your review to `{{run_dir}}/submissions/{{case_id}}/review.md` in exactly this format:

```
case_id: {{case_id}}
reviewer_lane: {{lane_id}}
rubric_version: aos-severity-rubric-v1   # confirms rubric was loaded
disposition: {{find_defect | uncertain | approve}}
summary: {{one-paragraph honest assessment}}

findings:
  - severity: {{critical | major | minor}}      # per rubric definitions
    location: {{file:line or element}}
    description: {{what is wrong}}
    evidence: {{how you verified this is real — not an assertion}}
    confidence: {{high | medium | low}}
```

### Adversarial lens

Your job is to find what could be wrong, not to confirm the implementer. Assume the code is deployed as written and ask: what breaks, what can an attacker do, what edge case is unhandled? An approval must be justified by the absence of defects, not by the absence of effort to find them.

---

### Dispatcher notes (not shown to reviewer)

- **Lane:** use the same reviewer profile per domain across all cases in the set (e.g. `coder` for coding, `worker` for ops). Mixing lanes within a set calibrates the mix, not the lane.
- **Rubric binding check:** before accepting a submission, confirm `rubric_version:` is present and non-empty. If missing, the dispatch is invalid — reject and re-dispatch.
- **Independence:** the reviewer must have fresh context, frozen input, explicit scope, no pre-coordination, and (for medium/high-risk) a different model/provider family than the implementer.