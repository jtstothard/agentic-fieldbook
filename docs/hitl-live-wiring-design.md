# HITL live-wiring design

Status: design for #86 and #87
Owner: Fieldbook ↔ Hermes integration

This document defines the first live integration between the Fieldbook gate engine and the default Hermes profile. It is deliberately a boundary design: the router remains usable when Fieldbook is not installed, and a gate outage never prevents the router from sending the existing ad-hoc Telegram confirmation.

## Decisions at a glance

| Area | Decision |
| --- | --- |
| Decision/audit persistence | SQLite-backed `LearningStore` in the Fieldbook integration state directory; keep the existing in-memory implementation as an explicit test/ephemeral option. |
| Router boundary | A lazily loaded, structural bridge protocol. The Hermes router imports no `agentic_fieldbook` module at import time. |
| Failure policy | Fail open to the current Telegram ping, with a structured degradation log. Never convert bridge, evaluator, persistence, or Matrix failure into an action block. |
| Approval translation | `AUTONOMOUS` and `REPORT_ONLY` proceed; `GATE_LIGHT` and `GATE_HEAVY` create a gate. A recorded `APPROVED` proceeds; `REJECTED`, `EXPIRED`, and `REVOKED` abort. Unknown or malformed outcomes use the legacy Telegram path rather than blocking. |
| First always-ask rollout | `destructive`, because it has a small, high-confidence capability vocabulary, clear scope, and an easy-to-test abort/rollback story. |
| Live transport | The running Hermes Matrix gateway adapter is the transport. `FakeTransport` is test-only. The bridge receives the live adapter from the gateway's adapter registry; it does not construct a second Matrix client. |

## 1. Persistence decision

### Recommendation: SQLite-backed `LearningStore`

Use a small SQLite implementation behind the existing `GateLearningStore` protocol, located under the profile's Fieldbook integration state directory. SQLite is the v1 system of record for gate decisions and the input to standing-approval/known-preference checks.

The current evaluator intentionally depends on a narrow protocol:

```text
check_standing_approval(action_class) -> bool
check_known_preference(fork_signature, threshold=3) -> bool
```

The live store should extend that protocol with append-only recording, while preserving the evaluator's read methods:

```text
record_resolution(
    action_class,
    fork_signature,
    outcome,
    chosen_option,
    actor,
    task_id,
    contract_digest,
    timestamp,
) -> None
```

The store should use a schema version and migrations from its first release. The minimum durable data is:

- immutable resolution event: task/gate ID, action class, fork signature, outcome, selected option, actor, timestamp;
- contract digest and relevant risk/capability projection, so a later scope change cannot reuse an old decision accidentally;
- derived standing-approval and preference facts, or deterministic queries over the event table;
- a degradation/error record for failed writes, without storing secrets or message bodies.

Write the decision before resuming execution. If persistence fails, log `learning_store_unavailable` and use the legacy Telegram fallback; do not treat a missing learning record as a reason to block an action.

### Why not the alternatives?

- **In-memory:** useful for unit tests and explicitly disposable sessions, but it loses the audit trail and all learned preferences on restart. It is not acceptable as the live default.
- **Hindsight-backed:** useful later for cross-session semantic retrieval and pattern discovery, but probabilistic retrieval is the wrong authority for a safety/audit decision. It also introduces a service/auth/network dependency into the critical path. Hindsight may receive a sanitized, asynchronous projection after SQLite commits; it must not decide whether an action proceeds.

SQLite is local, deterministic, inspectable, transactional, and already matches the single-profile gateway deployment model. A future Hindsight projection is additive, not a replacement or a prerequisite.

### Concurrency, retention, and privacy

- Enable WAL mode, busy timeout, foreign keys, and one transaction per resolution.
- Use a single writer boundary; readers may query while the gateway is running.
- Do not store raw Telegram/Matrix message text, access tokens, secrets, or credentials. Store stable actor IDs only where required by the audit policy, preferably hashed/profile-local identifiers.
- Retain resolution events according to the profile audit policy. Never silently rewrite an event; corrections are compensating events.
- If the database is locked/corrupt/unavailable, emit a warning with task/gate ID and fall back to Telegram.

## 2. Router ↔ gate bridge contract

### Ownership and import boundary

The router belongs to the default Hermes profile; gate types and implementations belong to `agentic_fieldbook`. The router must not contain a top-level import of `agentic_fieldbook`, `LightGateRequest`, or any Fieldbook implementation. This keeps ordinary Hermes startup and operation working when the package is absent or incompatible.

Define a small protocol in the Hermes-side integration module (or an equivalent plugin hook):

```text
class GateBridge(Protocol):
    def evaluate_and_maybe_gate(task: RouterTask) -> BridgeResult: ...
    def process_reply(message: IncomingMessage) -> BridgeResult | None: ...
```

`RouterTask` is a JSON-shaped projection, not a live `CanonicalTaskRecord` object:

```text
RouterTask(
    task_id, objective, scope, exclusions, risk_class,
    capabilities, action_class, fork_description,
    recommended_option, options, trade_off, revert_path,
    idempotency_key, contract_digest,
)
```

The lazy loader resolves the bridge only when a task is about to be dispatched or a gate command is received. It catches import, construction, and protocol-version errors. The bridge may lazily import Fieldbook internally. The reverse dependency is forbidden: Fieldbook must not import Hermes gateway internals.

### Result contract

`BridgeResult` is transport-neutral and serializable:

```text
BridgeResult(
    status = proceed | abort | pending | fallback,
    task_id,
    gate_id = optional,
    reason,
    disposition = optional,
    outcome = optional,
    degradation_code = optional,
)
```

The bridge maps the existing evaluator and gate lifecycle as follows:

| Fieldbook result | Router action |
| --- | --- |
| `AUTONOMOUS` | proceed immediately; no human prompt |
| `REPORT_ONLY` | proceed and emit the existing report/notification |
| `GATE_LIGHT` | create/present a Matrix light gate; return `pending` |
| `GATE_HEAVY` (G1/always-ask) | create/present the heavy approval gate; return `pending` |
| `APPROVED` | record the resolution and resume the exact task/contract epoch; `proceed` |
| `REJECTED` | record the resolution; `abort` without executing |
| `EXPIRED` or `REVOKED` | record the terminal resolution; `abort` and report why |
| malformed/unknown/infrastructure error | `fallback`, then send the legacy Telegram ping |

`pending` is only an orchestration state while a live gate is waiting. It is not permission to execute. A `proceed` result must include the task ID and contract digest/approval binding so a scope change cannot resume an old approval. A rejected or expired decision must never be retried as approval.

### Fail-open behavior

The existing Telegram ping is the compatibility and availability path. At every bridge boundary:

1. Log the failure as a structured event (`gate_bridge_unavailable`, `matrix_unavailable`, `learning_store_unavailable`, `gate_malformed`, or `gate_timeout`) with task/gate ID, component, exception class, and retry/fallback action.
2. Do not raise the failure into the router's action executor.
3. Send the same ad-hoc Telegram confirmation currently used by the router, preserving its existing recipient, wording, and response handling.
4. Continue using the legacy Telegram result semantics. If Telegram itself fails, surface the existing delivery failure; do not invent a new fail-closed gate.

This is deliberately fail-open for infrastructure outages, not an approval bypass. When the integration is healthy, the Fieldbook result controls the action. When it is not healthy, the current Telegram HITL path remains the source of the user's decision.

The fallback must be idempotent: use the same task ID/idempotency key and do not create duplicate execution attempts when a bridge call times out after sending a prompt.

### Suggested lazy-loader shape

```text
bridge = None
try:
    from integration.fieldbook_bridge import load_bridge  # inside the call
    bridge = load_bridge(gateway_context)
except Exception:
    logger.warning("gate bridge unavailable", exc_info=True)

if bridge is None:
    return legacy_telegram_confirmation(task)

try:
    result = bridge.evaluate_and_maybe_gate(task)
except Exception:
    logger.warning("gate bridge degraded", exc_info=True)
    return legacy_telegram_confirmation(task)

if result.status == "fallback":
    return legacy_telegram_confirmation(task)
return translate_result(result)
```

The actual implementation should use the host router's established logging and Telegram delivery helpers rather than copying them into Fieldbook.

## 3. Always-ask → `CanonicalTaskRecord` mapping

Always-ask is an absolute overlay: it must remain `GATE_HEAVY` regardless of reversibility, standing approvals, known preferences, or a Matrix/Telegram transport choice. Each record is created with a complete `TaskContract`; the category is represented by one or more capabilities, not by an untyped prompt string.

All mappings require:

- `risk_class`: `high` for the first rollout; this guarantees rollback/recovery evidence is declared by `TaskContract`.
- `scope`: exact resources, identities, services, environments, and operation boundaries. No wildcard scope in an approval record.
- `exclusions`: explicit non-targets (production vs preview, unrelated resources, credential values, unrelated accounts).
- `capabilities`: the category capability plus only capabilities actually needed.
- `acceptance_criteria`: observable post-action checks.
- `required_evidence`: preflight, approval, execution result, and rollback/recovery evidence.
- `objective` and `contract_id`/revision: stable, human-readable and digestible for idempotency.

| Always-ask class | Trigger capabilities | Contract mapping | Minimum exclusions/evidence |
| --- | --- | --- | --- |
| destructive | `delete`, `drop`, `truncate`, `destroy` | `risk_class=high`; capability exactly names the destructive operation and resource type; scope lists the resource IDs | Exclude backups, unrelated resources, and production unless explicitly scoped. Require target inventory, confirmation of backup/recovery, deletion result, and rollback/recovery evidence. |
| secret | `secret-read/write/rotate`, `credential-read/write/rotate` | `risk_class=high`; separate read, write, and rotate capabilities; scope names secret namespace/key references but never values | Exclude secret values from logs/prompts. Require authorization/preflight, rotation or access result, and recovery evidence. |
| billing | `billing-change`, `billing-adjust` | `risk_class=high`; scope names account, vendor, currency, amount/limit, and effective window | Exclude unrelated accounts and open-ended spend. Require before/after limits, cost impact, and reversal/refund path. |
| access | `access-grant`, `permission-grant`, `role-grant` | `risk_class=high`; scope names principal, resource, role, duration, and tenant | Exclude permanent/global/admin access unless explicitly requested. Require authorization evidence, effective-permission check, and revocation path. |
| downtime | `service-restart`, `service-stop`, `service-reload`, `deployment` | `risk_class=high`; scope names service, environment, window, and expected impact | Exclude unrelated services and unapproved environments. Require health checks, user-impact window, and rollback/backout evidence. |

The existing capability vocabulary also contains `release`/`deploy`/`promote`; those remain always-ask and should be mapped to the downtime/release policy in a follow-up rather than silently treated as routine deployment.

### First rollout: destructive

Start with destructive actions. It is the smallest category with unambiguous existing capability names and no need to interpret financial amounts, credential values, or access graphs. It exercises the full path safely in a disposable/preview scope: exact target inventory → heavy Matrix gate → approve/reject → execution or abort → audit resolution → recovery evidence. Roll out with an allowlist of explicitly recognized operations and require a non-empty scope; unknown destructive verbs fall back to the legacy Telegram path.

Do not roll out all five categories behind one flag. Add category-specific metrics and kill switches; expand to secret, billing, access, and downtime only after destructive-path audit and fallback tests pass.

## 4. Live Matrix transport

### Matrix gateway is the transport

The Fieldbook `MatrixTransport` protocol is an adapter seam for tests and deployment neutrality. It must not be implemented by a fake in production. The live object is the already-running Hermes Matrix platform adapter, which owns the authenticated mautrix client, room delivery, retries, encryption, access policy, and gateway lifecycle.

The Hermes adapter's actual operation is asynchronous (`send(chat_id, content, ...) -> SendResult`) and returns the Matrix event ID in `SendResult.message_id`. The Fieldbook bridge must therefore provide a small async-to-sync or async-native wrapper around that object rather than assuming a synchronous `send()`/`receive()` API. The bridge should use the gateway's event/callback path for incoming replies; it should not start a second polling loop or create another Matrix client.

### Obtaining the live adapter

When the bridge is constructed inside the gateway process, inject a `GatewayContext` containing:

```text
GatewayContext(
    adapters,        # live gateway adapter map
    platform_config, # resolved Matrix config/home room
    logger,
)
```

Resolve the adapter by the existing registry key (`Platform.MATRIX`, or the equivalent `"matrix"` key in the adapter map):

```text
matrix = gateway_context.adapters.get(Platform.MATRIX)
if matrix is None:
    raise MatrixUnavailable("live Matrix adapter is not running")
transport = HermesMatrixTransport(matrix, room_id=matrix_gate_room)
```

The adapter map is the source of truth. Do not import and instantiate `plugins.platforms.matrix.adapter.MatrixAdapter` from the bridge, do not read the access token to build a parallel client, and do not use the standalone HTTP sender for the in-process gate path. The standalone sender is only the existing out-of-process `deliver=matrix` fallback and is not a live `MatrixTransport`.

The wrapper's outbound operation is conceptually:

```text
result = await live_matrix.send(room_id, rendered_message)
if not result.success:
    raise MatrixUnavailable(result.error)
return result.message_id or ""
```

Inbound `/gate` messages should be delivered by the gateway's existing Matrix message event handler to `bridge.process_reply(text, sender, event_id, room_id)`. The bridge filters to the configured gate room and accepted sender policy, then delegates parsing to `MatrixGateAdapter.process_reply`. There is no `receive()` call in the live wrapper; a test transport may expose one for deterministic tests.

### Room and sender safety

- Use an explicit gate/control-room ID, preferably `MATRIX_HOME_ROOM` or a dedicated configured room, never an arbitrary room from a task message.
- Preserve the gateway's Matrix allowed-room/user policy and any approval sender restriction.
- Bind the actor, room, event ID, gate ID, task ID, and contract digest into the resolution audit record.
- Ignore free text and commands from unauthorized rooms/users.
- Keep gate prompts free of secret values; use references and redacted summaries.

## 5. Wiring sequence and operational controls

1. Router builds a JSON-shaped `RouterTask` and calls the lazy bridge.
2. Bridge evaluates the task and constructs a `CanonicalTaskRecord`/`TaskContract` when an always-ask class is present.
3. For a gate disposition, bridge creates the Fieldbook request with a stable idempotency key and presents it through the injected live Matrix adapter.
4. Gateway routes the incoming Matrix event to the bridge; the bridge validates sender/room, parses `/gate approve|reject|pick`, records the resolution in SQLite, and returns the translated result.
5. Router resumes only the same task and approval epoch for `proceed`; otherwise it aborts/reports.
6. Any unavailable component invokes the Telegram compatibility path and records structured degradation telemetry.

Required metrics/log fields: `task_id`, `gate_id`, `contract_digest`, `action_class`, disposition, outcome, component, fallback, latency, and error class. Never log token values, secret values, or full message bodies.

Required tests before enabling the live flag:

- importing the router with Fieldbook absent does not fail;
- bridge import/construction failure invokes Telegram fallback;
- Matrix send failure invokes Telegram fallback;
- `AUTONOMOUS`/`REPORT_ONLY` proceed and `GATE_*` wait;
- approve/reject/expire/revoke map to proceed/abort exactly;
- scope/contract digest changes cannot reuse an approval;
- each always-ask mapping creates the expected contract and exclusions;
- live adapter injection uses the gateway's existing Matrix instance, while tests use `FakeTransport` only;
- SQLite restart preserves resolutions and preference counts.

The live feature should be disabled by default until these checks pass, then enabled for the destructive allowlist in one profile/room with a reversible configuration change.
