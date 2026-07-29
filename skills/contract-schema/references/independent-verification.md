# Independent Verification Pattern

## Overview

Independent verification is a security pattern where a separate verifier agent checks the actual state of the target system after a capability is executed, rather than trusting the worker's post-state claims. The verifier queries the target directly, confirms the exact named artifact exists, and submits a verdict to the broker for audit-chain completeness.

## Core Rules

The pilot evidence validated six non-negotiable rules for independent verification:

1. **Direct target query** — Verifier must query the target system's authoritative API directly, never via the worker, wrapper, or any intermediate system that could be compromised or mistaken.

2. **No trust of worker post_state** — Verifier must ignore worker-provided post_state claims entirely. The verifier's own direct read is the only source of truth for verification.

3. **Verdict submission to broker** — Verifier submits a verdict (either `verified-true` or `verified-false`) directly to the broker. The verdict is recorded in the lease record as part of the audit chain.

4. **Broker records verdict** — Broker records the verdict with a timestamp, verifier identity, and verification source in the lease record. This becomes durable audit-chain evidence.

5. **Read-only target access** — Verifier has read-only access to the target (no mutation capability on any path). This prevents the verifier from accidentally or maliciously altering the target during verification.

6. **Exact artifact name check** — Verifier must confirm the exact named artifact from the contract exists (for example, the exact snapshot name), not just that "some artifact exists." Pattern matching or "any artifact" checks are insufficient.

## Pattern Flow

```
1. Worker executes capability and claims post_state
2. Worker submits completion + post_state to broker
3. Broker marks lease as "awaiting-verification"
4. Independent verifier receives lease context:
   - contract_digest
   - target identifier
   - expected artifact name
   - capability executed
5. Verifier queries target directly (read-only API)
6. Verifier checks for exact named artifact
7. Verifier submits verdict to broker:
   - verified-true: artifact exists and matches contract
   - verified-false: artifact absent or mismatch
8. Broker records verdict in lease record
9. Lease transitions to verified-true or verified-false state
```

## Anti-Patterns

**Do not trust worker post_state claims.** The pilot Gate 4 negative test demonstrated the risk: a buggy wrapper claimed `snapshot_exists=true` while the verifier independently found the snapshot absent. Without independent verification, the false success would have persisted uncaught.

**Do not use pattern matching for artifact checks.** Verifiers must confirm the exact named artifact exists. Checking "any snapshot" or "snapshot name starts with" allows false positives and misses mismatches.

**Do not query via intermediaries.** Querying the worker, wrapper, or any proxy between the verifier and the target breaks independence. The verifier must reach the target's authoritative source of truth directly.

## Role Boundaries

- **Worker:** Executes the capability, submits post_state claims to broker. Cannot verify its own work.
- **Verifier:** Read-only agent, independent of worker, queries target directly, submits verdict to broker. Cannot mutate target.
- **Broker:** Records worker claims, coordinates verification, records verdict, enforces lease budget and replay protection.
- **Wrapper:** Orchestrates capability execution against the target. Not a source of truth for verification.

## Key Terms

- **Independent verifier:** A separate agent with read-only target access, no mutation capability, no trust of worker claims.
- **Direct target query:** Verifier reaches the target system's authoritative API directly (no intermediaries).
- **Exact artifact name:** The precise artifact identifier from the contract (e.g., snapshot name, VM ID), not a pattern or "any" check.
- **Verified-true:** Verifier confirmed the exact named artifact exists and matches contract expectations.
- **Verified-false:** Verifier found the exact named artifact absent or mismatched with contract expectations.
- **Broker:** External coordination service that records worker claims, manages lease state, and records verifier verdicts.

## Pilot Evidence

The AOS capability-approval pilot (P1–P8) proved the value of independent verification at Gate 4. A deliberate negative test produced a false worker/wrapper success: the wrapper claimed the named snapshot existed, while the independent verifier found it absent. The verifier submitted `verified-false`; the broker recorded the verdict; and the mismatch was caught before any downstream system trusted the false success.

This is documented in the pilot acceptance evidence and demonstrates that independent verification catches real bugs that would otherwise propagate.

## Applicability

Use this pattern when:

- Operations mutate production infrastructure (VMs, containers, databases, cloud resources).
- A separate broker or coordination service records claims and verdicts.
- An audit chain is required (pre-state, capability call, post-state, verdict).
- The target system exposes a read-only API for verification.

Do not use this pattern when:

- Operations are reversible without risk (development environments, temporary resources).
- No external broker or coordination service exists.
- The target system does not expose a read-only API for direct queries.
- The cost of verification outweighs the risk (low-impact operations).

## Security Properties

Independent verification provides these security properties:

- **Separation of concerns:** Worker and verifier have distinct roles; neither can perform the other's function.
- **Audit-chain completeness:** All four phases are recorded independently (pre-state, capability call, post-state, verdict).
- **Fail-closed behavior:** Verified-false is treated as a failure state, triggering escalation or rollback rather than silent acceptance.
- **Replay resistance:** Verifier checks the exact artifact, preventing replay attacks where a different artifact is substituted.
- **Credential minimization:** Verifier needs only read-only credentials, reducing attack surface compared to worker write credentials.

## Implementation Notes

- Verifier credentials must be read-only only, with no write permissions.
- Verifier identity must be distinct from worker identity in the broker's records.
- Verifier must time out independently; do not wait indefinitely for target responses.
- Verifier should log its query sources and results for troubleshooting, but never include credentials or secret values in logs.
- On target unavailability, the verifier should fail the verification (verified-false) rather than skip, preserving fail-closed semantics.