"""Tests for Fieldbook v3 durable portable storage backend (Slice 3)."""

import json
import os
from pathlib import Path
from datetime import datetime

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    Evidence,
    LifecycleState,
    TaskContract,
)
from agentic_fieldbook.storage import (
    CorruptedRecordError,
    InvalidTaskIDError,
    PortableTaskStore,
    SchemaVersionError,
    UnknownSchemaVersionError,
)


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for storage tests."""
    return tmp_path / "fieldbook_store"


@pytest.fixture
def sample_contract() -> TaskContract:
    """Create a sample task contract for testing."""
    return TaskContract(
        contract_id="FB-001",
        objective="Fix the parser bug",
        scope=("parser", "parser tests"),
        exclusions=("deployment",),
        risk_class="low",
        capabilities=("repo-write", "local-test"),
        acceptance_criteria=("parser-test-passes",),
        required_evidence=("tests", "diff"),
        domain="coding.v1",
    )


@pytest.fixture
def sample_record(sample_contract: TaskContract) -> CanonicalTaskRecord:
    """Create a sample task record with some history."""
    record = CanonicalTaskRecord.create(sample_contract, task_id="task-1")
    record.transition(LifecycleState.PLANNED, actor="planner")
    record.transition(LifecycleState.APPROVED, actor="planner")
    record.transition(
        LifecycleState.EXECUTING,
        actor="executor",
        executor_capabilities=("repo-write", "local-test"),
    )
    record.transition(
        LifecycleState.REPORTED_COMPLETE,
        actor="executor",
        evidence=[Evidence("tests", "pytest passed", "pytest", "0")],
    )
    return record


class TestPortableTaskStoreBasics:
    """Test basic PortableTaskStore creation and configuration."""

    def test_store_creates_tasks_directory(self, temp_dir: Path) -> None:
        """Store should create the tasks directory on initialization."""
        store = PortableTaskStore(base_dir=temp_dir)
        tasks_dir = temp_dir / "tasks"
        assert tasks_dir.exists()
        assert tasks_dir.is_dir()

    def test_store_accepts_custom_base_dir(self, temp_dir: Path) -> None:
        """Store should accept a custom base directory."""
        custom_dir = temp_dir / "custom_store"
        store = PortableTaskStore(base_dir=custom_dir)
        assert (custom_dir / "tasks").exists()


class TestAtomicWrites:
    """Test atomic write guarantees."""

    def test_save_creates_atomically_via_temp_file(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Save should write to a temp file first, then rename atomically."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Save the record
        store.save(sample_record)

        # Check file exists at expected location
        task_file = temp_dir / "tasks" / "task-1.json"
        assert task_file.exists()

        # Verify content is valid JSON
        with open(task_file) as f:
            data = json.load(f)
        assert data["task_id"] == "task-1"
        assert data["schema"] == "fieldbook.task-record.v1"

    def test_save_overwrites_existing_atomically(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Save should atomically replace existing records."""
        import time

        store = PortableTaskStore(base_dir=temp_dir)

        # Save initial version
        store.save(sample_record)
        first_mtime = (temp_dir / "tasks" / "task-1.json").stat().st_mtime

        # Small sleep to ensure mtime changes
        time.sleep(0.01)

        # Advance record and save again
        sample_record.transition(LifecycleState.REVIEW, actor="reviewer")
        sample_record.transition(LifecycleState.VERIFICATION, actor="verifier")
        sample_record.transition(
            LifecycleState.VERIFIED,
            actor="verifier",
            evidence=[
                Evidence("diff", "diff is in scope", "git diff", "clean"),
                Evidence("parser-test-passes", "All parser tests pass", "pytest", "0"),
            ],
        )
        store.save(sample_record)

        # File was updated
        second_mtime = (temp_dir / "tasks" / "task-1.json").stat().st_mtime
        assert second_mtime >= first_mtime

        # Verify updated content
        loaded = store.load("task-1")
        assert loaded.state == LifecycleState.VERIFIED


class TestSaveLoadRoundTrip:
    """Test save/load round-trip preserves record state."""

    def test_save_load_preserves_all_fields(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Save and load should preserve all record fields."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        assert loaded.task_id == sample_record.task_id
        assert loaded.state == sample_record.state
        assert len(loaded.history) == len(sample_record.history)
        assert len(loaded.evidence) == len(sample_record.evidence)
        assert loaded.contract.contract_id == sample_record.contract.contract_id

    def test_save_load_preserves_history(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """History should be preserved across save/load."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        assert len(loaded.history) == 4
        assert loaded.history[0]["from"] == "proposed"
        assert loaded.history[0]["to"] == "planned"
        assert loaded.history[3]["to"] == "reported_complete"

    def test_save_load_preserves_evidence(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Evidence should be preserved across save/load."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        assert len(loaded.evidence) == 1
        assert loaded.evidence[0]["requirement"] == "tests"
        assert loaded.evidence[0]["claim"] == "pytest passed"

    def test_save_load_preserves_governance_state(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Governance state should be preserved across save/load."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        # Check governance state was restored
        assert loaded._governance is not None
        assert loaded._governance.rollback_declared == (sample_record.contract.risk_class == "high")


class TestListRecords:
    """Test listing records from storage."""

    def test_list_returns_all_records(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """List should return all stored records."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Create and save multiple records
        for i in range(3):
            record = CanonicalTaskRecord.create(sample_contract, task_id=f"task-{i}")
            record.transition(LifecycleState.PLANNED, actor="planner")
            record.transition(LifecycleState.APPROVED, actor="planner")
            store.save(record)

        records = store.list()
        assert len(records) == 3
        task_ids = {r.task_id for r in records}
        assert task_ids == {"task-0", "task-1", "task-2"}

    def test_list_filters_by_state(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """List should filter records by lifecycle state."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Create records in different states
        record1 = CanonicalTaskRecord.create(sample_contract, task_id="task-1")
        record1.transition(LifecycleState.PLANNED, actor="planner")
        store.save(record1)

        record2 = CanonicalTaskRecord.create(sample_contract, task_id="task-2")
        record2.transition(LifecycleState.PLANNED, actor="planner")
        record2.transition(LifecycleState.APPROVED, actor="planner")
        store.save(record2)

        record3 = CanonicalTaskRecord.create(sample_contract, task_id="task-3")
        record3.transition(LifecycleState.PLANNED, actor="planner")
        record3.transition(LifecycleState.APPROVED, actor="planner")
        store.save(record3)

        # Filter by state
        planned = store.list(state=LifecycleState.PLANNED)
        assert len(planned) == 1
        assert planned[0].task_id == "task-1"

        approved = store.list(state=LifecycleState.APPROVED)
        assert len(approved) == 2
        approved_ids = {r.task_id for r in approved}
        assert approved_ids == {"task-2", "task-3"}

    def test_list_returns_empty_for_no_records(self, temp_dir: Path) -> None:
        """List should return empty list when no records exist."""
        store = PortableTaskStore(base_dir=temp_dir)
        records = store.list()
        assert records == []


class TestCrossSessionRecovery:
    """Test cross-session recovery scenarios."""

    def test_save_in_one_session_load_in_another(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Record saved in one session should be loadable in a fresh session."""
        # Session 1: Save
        store1 = PortableTaskStore(base_dir=temp_dir)
        store1.save(sample_record)

        # Session 2: Load (fresh store instance)
        store2 = PortableTaskStore(base_dir=temp_dir)
        loaded = store2.load("task-1")

        assert loaded.task_id == "task-1"
        assert loaded.state == sample_record.state

    def test_list_across_sessions(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """Records saved in one session should be listable in another."""
        # Session 1: Save multiple records
        store1 = PortableTaskStore(base_dir=temp_dir)
        for i in range(3):
            record = CanonicalTaskRecord.create(sample_contract, task_id=f"task-{i}")
            record.transition(LifecycleState.PLANNED, actor="planner")
            store1.save(record)

        # Session 2: List
        store2 = PortableTaskStore(base_dir=temp_dir)
        records = store2.list()
        assert len(records) == 3


class TestSchemaVersioning:
    """Test schema version validation."""

    def test_accepts_valid_schema_version(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Store should accept records with valid schema version."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        # Should load successfully
        loaded = store.load("task-1")
        assert loaded.task_id == "task-1"

    def test_rejects_unknown_schema_version(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """Store should reject records with unknown schema versions."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Manually create a file with wrong schema version
        task_file = temp_dir / "tasks" / "task-1.json"
        bad_data = {
            "schema": "fieldbook.task-record.v999",
            "task_id": "task-1",
            "contract": sample_contract.to_dict(),
            "state": "planned",
            "history": [],
            "evidence": [],
            "governance": {},
        }
        with open(task_file, "w") as f:
            json.dump(bad_data, f)

        # Should raise UnknownSchemaVersionError
        with pytest.raises(UnknownSchemaVersionError, match="v999"):
            store.load("task-1")

    def test_rejects_missing_schema_field(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """Store should reject records without schema field."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Manually create a file without schema
        task_file = temp_dir / "tasks" / "task-1.json"
        bad_data = {
            "task_id": "task-1",
            "contract": sample_contract.to_dict(),
            "state": "planned",
            "history": [],
            "evidence": [],
            "governance": {},
        }
        with open(task_file, "w") as f:
            json.dump(bad_data, f)

        # Should raise SchemaVersionError
        with pytest.raises(SchemaVersionError):
            store.load("task-1")


class TestCorruptionDetection:
    """Test corruption detection and handling."""

    @pytest.mark.parametrize(
        ("task_id", "payload", "root_type"),
        [
            ("task-array", [], "list"),
            ("task-null", None, "NoneType"),
            ("task-scalar", 1, "int"),
        ],
    )
    def test_load_rejects_valid_json_with_non_mapping_root(
        self, temp_dir: Path, task_id: str, payload, root_type: str
    ) -> None:
        """A JSON document must have an object root to be a task record."""
        store = PortableTaskStore(base_dir=temp_dir)
        (temp_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(payload))

        with pytest.raises(CorruptedRecordError, match=rf"{task_id}.*{root_type}"):
            store.load(task_id)

    def test_list_skips_and_reports_all_non_mapping_json_roots(self, temp_dir: Path) -> None:
        """List should report every valid-JSON file with an invalid root type."""
        store = PortableTaskStore(base_dir=temp_dir)
        payloads = {"task-array": [], "task-null": None, "task-scalar": 1}
        for task_id, payload in payloads.items():
            (temp_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(payload))

        seen = []
        assert store.list(on_error=lambda path, error: seen.append((path, error))) == []
        assert {path.stem for path, _ in seen} == set(payloads)
        assert all(isinstance(error, CorruptedRecordError) for _, error in seen)
        assert {path.stem for path, _ in store.diagnostics} == set(payloads)

    def test_load_normalizes_invalid_record_structure(self, temp_dir: Path) -> None:
        """A mapping with a valid schema but missing fields is still corruption."""
        store = PortableTaskStore(base_dir=temp_dir)
        task_id = "task-missing-fields"
        (temp_dir / "tasks" / f"{task_id}.json").write_text(
            json.dumps({"schema": "fieldbook.task-record.v1"})
        )

        with pytest.raises(CorruptedRecordError, match=task_id):
            store.load(task_id)

    def test_load_normalizes_invalid_lifecycle_state(self, temp_dir: Path, sample_contract: TaskContract) -> None:
        """A schema-valid record with an invalid lifecycle state is corruption."""
        store = PortableTaskStore(base_dir=temp_dir)
        task_id = "task-invalid-state"
        (temp_dir / "tasks" / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "schema": "fieldbook.task-record.v1",
                    "task_id": task_id,
                    "contract": sample_contract.to_dict(),
                    "state": "bogus",
                    "history": [],
                    "evidence": [],
                    "governance": {},
                }
            )
        )

        with pytest.raises(CorruptedRecordError, match=task_id) as exc_info:
            store.load(task_id)
        assert isinstance(exc_info.value.__cause__, ValueError)

        seen = []
        assert store.list(on_error=lambda path, error: seen.append((path, error))) == []
        assert len(seen) == 1
        assert seen[0][0] == temp_dir / "tasks" / f"{task_id}.json"
        assert isinstance(seen[0][1], CorruptedRecordError)

    def test_reports_corrupted_json_files(self, temp_dir: Path) -> None:
        """Store should report corrupted JSON files without crashing."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Create a corrupted JSON file
        task_file = temp_dir / "tasks" / "task-1.json"
        with open(task_file, "w") as f:
            f.write("{ invalid json content")

        # Should raise CorruptedRecordError
        with pytest.raises(CorruptedRecordError, match="task-1"):
            store.load("task-1")

    def test_list_skips_corrupted_files(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """List should skip corrupted files and continue."""
        store = PortableTaskStore(base_dir=temp_dir)

        # Save a valid record
        store.save(sample_record)

        # Create a corrupted file
        corrupted_file = temp_dir / "tasks" / "task-2.json"
        with open(corrupted_file, "w") as f:
            f.write("{ invalid json")

        # List should only return the valid record
        records = store.list()
        assert len(records) == 1
        assert records[0].task_id == "task-1"

    def test_save_truncated_file_is_safe(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """If write is interrupted before atomic rename, no partial file should exist."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        # Manually create a temp file that simulates interrupted write
        temp_pattern = "task-1.json.*"
        temp_files = list((temp_dir / "tasks").glob(temp_pattern))
        # In normal operation, no temp files should exist after successful save
        assert len(temp_files) == 0


    def test_rejects_path_traversal_ids_before_filesystem_access(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        store = PortableTaskStore(base_dir=temp_dir)
        sample_record.task_id = "../escape"
        with pytest.raises(InvalidTaskIDError):
            store.save(sample_record)
        with pytest.raises(InvalidTaskIDError):
            store.load("../escape")
        assert not (temp_dir / "escape.json").exists()

    def test_list_reports_corruption_without_crashing(self, temp_dir: Path) -> None:
        store = PortableTaskStore(base_dir=temp_dir)
        bad = temp_dir / "tasks" / "bad.json"
        bad.write_text("not json")
        seen = []
        assert store.list(on_error=lambda path, error: seen.append((path, error))) == []
        assert seen and seen[0][0] == bad
        assert isinstance(store.diagnostics[0][1], CorruptedRecordError)

    def test_failed_replace_cleans_temp_file(self, temp_dir: Path, sample_record: CanonicalTaskRecord, monkeypatch) -> None:
        store = PortableTaskStore(base_dir=temp_dir)
        def fail_replace(source, target):
            raise OSError("injected replace failure")
        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="injected"):
            store.save(sample_record)
        assert not list((temp_dir / "tasks").glob("*.tmp"))


class TestErrorHandling:
    """Test error handling edge cases."""

    def test_load_nonexistent_record_raises_key_error(self, temp_dir: Path) -> None:
        """Loading a nonexistent record should raise KeyError."""
        store = PortableTaskStore(base_dir=temp_dir)

        with pytest.raises(KeyError, match="task-nonexistent"):
            store.load("task-nonexistent")

    def test_save_with_existing_directory(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Save should work even if tasks directory already exists."""
        # Pre-create the tasks directory (with parents to avoid error)
        tasks_dir = temp_dir / "tasks"
        tasks_dir.mkdir(parents=True)

        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        # Should have saved successfully
        assert (tasks_dir / "task-1.json").exists()


class TestRecordValidation:
    """Test that loaded records are properly validated."""

    def test_loaded_record_enforces_lifecycle_rules(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Loaded records should enforce lifecycle transition rules."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        # Should still enforce lifecycle rules
        from agentic_fieldbook.lifecycle import InvalidTransitionError

        with pytest.raises(InvalidTransitionError):
            loaded.transition(LifecycleState.VERIFIED, actor="verifier")

    def test_loaded_record_preserves_contract_validation(self, temp_dir: Path, sample_record: CanonicalTaskRecord) -> None:
        """Loaded records should preserve contract validation."""
        store = PortableTaskStore(base_dir=temp_dir)
        store.save(sample_record)

        loaded = store.load("task-1")

        # Contract should still be validated
        assert loaded.contract.risk_class == "low"
        assert loaded.contract.contract_id == "FB-001"