from datetime import datetime, timedelta, timezone
import threading
from typing import Any, cast

from agentic_fieldbook.broker import (
    AuditEvent, Lease, LeaseAuthority, LeaseState, OperationOutcome,
)


NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_lease(**changes):
    values = dict(
        lease_id="lease-1",
        receipt_id="receipt-1",
        action_digest="sha256:" + "a" * 64,
        target={"cluster": "example", "id": "guest-1"},
        capability="snapshot_guest",
        parameters={"snapshot": "approved"},
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        operation_limit=1,
    )
    values.update(changes)
    typed = cast(dict[str, Any], values)
    return Lease(
        lease_id=cast(str, typed["lease_id"]), receipt_id=cast(str, typed["receipt_id"]),
        action_digest=cast(str, typed["action_digest"]), target=cast(dict[str, Any], typed["target"]),
        capability=cast(str, typed["capability"]), parameters=cast(dict[str, Any], typed["parameters"]),
        issued_at=cast(datetime, typed["issued_at"]), expires_at=cast(datetime, typed["expires_at"]),
        operation_limit=cast(int, typed["operation_limit"]),
    )


def test_lease_is_traceable_to_one_receipt_and_digest():
    authority = LeaseAuthority()
    lease = authority.issue(make_lease())
    assert lease.receipt_id == "receipt-1"
    assert lease.action_digest.startswith("sha256:")
    assert [event.event_type for event in authority.recover()] == ["lease_issued"]


def test_revocation_is_idempotent_and_never_recovers_to_usable():
    authority = LeaseAuthority()
    authority.issue(make_lease())
    revoked = authority.revoke("lease-1", NOW, "operator cancellation")
    authority.revoke("lease-1", NOW, "retry")
    assert revoked.state is LeaseState.REVOKED
    assert not authority.usable("lease-1", NOW)
    assert [event.event_type for event in authority.recover()] == ["lease_issued", "lease_revoked"]


def test_expiry_is_append_only_and_blocks_execution():
    authority = LeaseAuthority()
    authority.issue(make_lease(expires_at=NOW + timedelta(seconds=1)))
    assert not authority.usable("lease-1", NOW + timedelta(seconds=2))
    assert authority.leases["lease-1"].state is LeaseState.EXPIRED
    assert [event.event_type for event in authority.recover()] == ["lease_issued", "lease_expired"]


def test_repeated_issue_does_not_duplicate_authorization_or_audit():
    authority = LeaseAuthority()
    first = authority.issue(make_lease())
    second = authority.issue(make_lease())
    assert first == second
    assert len(authority.recover()) == 1


def test_operation_budget_is_atomic_idempotent_and_lifecycle_bound():
    authority = LeaseAuthority()
    authority.issue(make_lease(operation_limit=2))
    assert authority.reserve_operation("lease-1", "op-1", NOW) is OperationOutcome.RESERVED
    assert authority.leases["lease-1"].state is LeaseState.EXECUTING
    assert authority.reserve_operation("lease-1", "op-1", NOW) is OperationOutcome.REPLAY
    assert authority.consume_operation("lease-1", "op-1", NOW) is OperationOutcome.CONSUMED
    assert authority.leases["lease-1"].state is LeaseState.ISSUED
    assert authority.reserve_operation("lease-1", "op-2", NOW) is OperationOutcome.RESERVED
    assert authority.consume_operation("lease-1", "op-2", NOW) is OperationOutcome.CONSUMED
    assert authority.leases["lease-1"].state is LeaseState.CONSUMED
    assert authority.reserve_operation("lease-1", "op-3", NOW) is OperationOutcome.UNAVAILABLE


def test_operation_reservation_rejects_expired_lease():
    authority = LeaseAuthority()
    authority.issue(make_lease(expires_at=NOW + timedelta(seconds=1)))
    assert authority.reserve_operation("lease-1", "op-1", NOW + timedelta(seconds=2)) is OperationOutcome.UNAVAILABLE
    assert authority.leases["lease-1"].state is LeaseState.EXPIRED


def test_concurrent_operation_reservations_cannot_exceed_budget():
    authority = LeaseAuthority()
    authority.issue(make_lease(operation_limit=1))
    outcomes = []
    barrier = threading.Barrier(8)

    def reserve(index):
        barrier.wait()
        outcomes.append(authority.reserve_operation("lease-1", f"op-{index}", NOW))

    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(OperationOutcome.RESERVED) == 1
    assert authority.leases["lease-1"].operations_used == 1
