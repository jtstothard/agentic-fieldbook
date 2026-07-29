# Capability-Approval Lease Lifecycle

This is the canonical inner lifecycle for a capability lease. It nests inside the universal contract lifecycle: `lease-issued` begins authorized execution, and verification outcomes feed the enclosing review/verification stages. A lease is bound to an immutable contract digest, target, capability, parameters, expiry, and operation budget.

## States

| State | Meaning | Allowed next states |
|---|---|---|
| `lease-issued` | Broker issued a lease after validating approval, contract binding, target, TTL, and remaining budget. No capability call has started. | `executing`, `lease-consumed`, `expired`, `revoked` |
| `executing` | Worker is performing the approved capability under the lease. The broker must enforce lease validity and operation identity. | `awaiting-verification`, `lease-consumed`, `expired`, `revoked` |
| `awaiting-verification` | Worker reported completion and post-state; an independent verifier must query the target directly. The worker claim is not success. | `verified-true`, `verified-false`, `expired`, `revoked` |
| `verified-true` | Independent verifier confirmed the expected result against the authoritative target. | `lease-consumed` |
| `verified-false` | Independent verifier found the result absent, mismatched, or unverifiable. This is a failure outcome, not acceptance. | `lease-consumed` |
| `lease-consumed` | The lease can no longer authorize execution. Consumption occurs after the permitted operation budget is used or after a terminal verification outcome. | none |

`expired` and `revoked` are terminal administrative outcomes. They may be recorded alongside the six operational states above; neither may transition back to an executable state.

## Normal flow

```text
lease-issued -> executing -> awaiting-verification -> verified-true -> lease-consumed
                                               \-> verified-false -> lease-consumed
```

A broker may transition `lease-issued` directly to `lease-consumed` when issuance discovers that the budget is unavailable or the lease is already unusable. It must record the reason. A failed execution still requires independent verification when a target-side mutation may have occurred; do not consume the lease merely because the worker returned an error.

## Revoke and expiry

- **Revoke:** An authorized operator or policy engine marks a lease revoked. The broker rejects new calls immediately and attempts to cancel in-flight work where the target supports cancellation. Cancellation is best effort; any possible mutation is still independently verified. Revoke is fail-closed and cannot be undone by the worker.
- **Expiry:** The broker compares requests against the lease expiry using a trusted clock. After expiry it rejects new calls and extensions. In-flight work must be stopped where possible, then verified; if it cannot be verified, the result is `verified-false` or an explicit unverifiable failure according to the contract's fail-closed policy. Expiry is terminal.
- Lease state, reason, actor, timestamps, and affected operation ID must be appended to the audit record for both events.

## Replay and budget exhaustion

Every execution request carries a unique `operation_id` bound to the lease and contract digest. The broker atomically records it before execution. A repeated ID is rejected as replay and cannot execute again. When the operation budget reaches zero, the broker transitions the lease to `lease-consumed`; further calls are rejected, including calls with a fresh operation ID. Race-safe accounting is required so concurrent requests cannot exceed the budget.

## Broker outage and recovery

- **During outage:** Fail closed. Do not issue, renew, or accept execution under a lease when the broker cannot validate current state. Do not treat a cached approval, receipt, or worker claim as authorization or success.
- **In-flight outage:** The worker must stop making capability calls when lease validation cannot be refreshed. Preserve the operation ID and local evidence; do not retry blindly.
- **Recovery:** On reconnection, the broker reconciles durable lease, operation, and audit records idempotently. It marks leases expired, revoked, or consumed according to authoritative timestamps and budget records, then accepts work only for leases still valid. Any operation whose outcome is uncertain is independently verified before a final verdict; uncertain or unavailable verification remains fail-closed.
- Recovery must not resurrect revoked/expired leases, reset consumed budgets, or permit a previously recorded operation ID to run again.

## Evidence and role boundaries

- **Broker:** Authorizes transitions, enforces digest binding, TTL, revoke state, replay protection, and operation budget; appends audit events.
- **Worker:** Executes only while the broker authorizes the operation and reports claims. It cannot self-verify.
- **Independent verifier:** Queries the target directly with read-only access and submits `verified-true` or `verified-false` to the broker.
- **Operator/human gate:** Approves the exact binding before issuance and may revoke according to policy.

Every transition records the lease ID, contract digest, operation ID when applicable, actor, reason, and timestamp. A terminal result is not accepted until required evidence and verification are present.

## Provenance

This lifecycle is a reusable abstraction extracted from pilot acceptance evidence and validation records. It intentionally contains no pilot-specific identities, endpoints, or artifact identifiers.
