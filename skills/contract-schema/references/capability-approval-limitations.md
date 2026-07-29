# Capability-Approval Domain: Pilot Limitations

This document records the boundaries of the evidence behind the capability-approval guidance. The protocol patterns below are pilot-validated and suitable for extraction into reusable guidance; they are not, by themselves, a production-readiness claim.

## Approval boundary

**Pilot evidence:** Approval was mediated manually through a human-facing channel, with a routing component submitting the resulting lease request.

**Limitation:** The pilot did not validate an automated approval gate that enforces the complete approval binding at request time. A deployment must provide an authenticated human gate and verify that approval is bound to the contract digest, target, capability, and parameters before issuing a lease.

## Wrapper and service operation

**Pilot evidence:** The execution wrapper and broker-facing services were intentionally minimal and exercised in a controlled test environment.

**Limitations:** The pilot did not establish production operational properties such as hardened process management, high availability, replicated storage, capacity limits, observability, upgrade procedures, or disaster recovery. Those properties require deployment-specific design and validation.

## Automated cleanup

**Pilot evidence:** Lease and evidence cleanup was not the focus of the validation.

**Limitation:** A deployment must define and test retention, expiry cleanup, artifact cleanup, and recovery of interrupted cleanup. Expired or revoked leases must not remain usable even if associated records are retained for audit.

## Scope of validation

The pilot evidence supports these extracted patterns:

- Contract-digest binding prevents execution under a materially changed contract.
- Independent verification catches false success claims.
- Broker-backed lease state and budget enforcement can fail closed.
- Replay protection rejects reuse of an operation identifier or exhausted budget.
- Degraded broker conditions do not issue or extend leases.

The pilot evidence does not establish that any particular deployment is production-ready. Production suitability requires separate validation of its approval gate, service hardening, availability, security controls, monitoring, backup/recovery, retention, and operational procedures.

## Provenance

This guidance was extracted from the capability-approval pilot acceptance evidence and its associated validation records. The evidence is retained separately from this reusable reference; this document intentionally omits pilot identities, private endpoints, and exact artifact identifiers.

## Decision rule

Use this reference as a pilot-validated checklist and extraction boundary. Do not represent the protocol or any implementation as production-ready without deployment-specific evidence and review against the limitations above.
