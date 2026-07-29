"""Durable portable storage backend for Fieldbook v1.

This module provides a simple JSON-based storage backend for CanonicalTaskRecord
instances. It uses atomic writes, schema versioning, and corruption detection.

Features:
- Atomic writes using temp file + os.replace()
- Flat directory of JSON files (tasks/<task_id>.json)
- Schema version validation (fieldbook.task-record.v1)
- Corruption detection (reports bad files without crashing)
- Cross-session recovery (save in one session, load in another)
- List all records with optional state filtering
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .lifecycle import CanonicalTaskRecord, LifecycleState


class StorageError(Exception):
    """Base error for storage operations."""


class SchemaVersionError(StorageError):
    """Raised when a record has an invalid or missing schema version."""


class UnknownSchemaVersionError(SchemaVersionError):
    """Raised when a record has an unknown schema version."""


class CorruptedRecordError(StorageError):
    """Raised when a record file is corrupted (invalid JSON, etc.)."""


SUPPORTED_SCHEMA_VERSION = "fieldbook.task-record.v1"


class PortableTaskStore:
    """Portable JSON storage backend for CanonicalTaskRecord instances.

    Records are stored as JSON files in a flat directory structure:
        <base_dir>/tasks/<task_id>.json

    The store guarantees atomic writes using temp file + os.replace(),
    validates schema versions, and detects corrupted files without crashing.
    """

    def __init__(self, base_dir: Path | str) -> None:
        """Initialize the storage backend.

        Args:
            base_dir: Base directory for storage. A 'tasks' subdirectory will be created.
        """
        self.base_dir = Path(base_dir)
        self.tasks_dir = self.base_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: CanonicalTaskRecord) -> None:
        """Save a record to disk with atomic write guarantees.

        The record is serialized to JSON and written to a temporary file,
        then atomically renamed to the final location using os.replace().

        Args:
            record: The CanonicalTaskRecord to save.
        """
        data = record.to_dict()
        task_id = record.task_id

        # Write to temp file first
        temp_file = self.tasks_dir / f"{task_id}.json.tmp"
        target_file = self.tasks_dir / f"{task_id}.json"

        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)

        # Atomic rename
        os.replace(temp_file, target_file)

    def load(self, task_id: str) -> CanonicalTaskRecord:
        """Load a record from disk by task_id.

        Args:
            task_id: The task ID to load.

        Returns:
            The loaded CanonicalTaskRecord.

        Raises:
            KeyError: If the task_id is not found.
            CorruptedRecordError: If the file is corrupted (invalid JSON).
            SchemaVersionError: If the schema version is missing or invalid.
            UnknownSchemaVersionError: If the schema version is not supported.
        """
        from .lifecycle import CanonicalTaskRecord

        target_file = self.tasks_dir / f"{task_id}.json"

        if not target_file.exists():
            raise KeyError(f"Task not found: {task_id}")

        try:
            with open(target_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise CorruptedRecordError(f"Corrupted record file for task {task_id}: {exc}") from exc

        # Validate schema version
        schema = data.get("schema")
        if schema is None:
            raise SchemaVersionError(f"Record {task_id} missing schema version")
        if schema != SUPPORTED_SCHEMA_VERSION:
            raise UnknownSchemaVersionError(
                f"Record {task_id} has unsupported schema version: {schema}. "
                f"Supported: {SUPPORTED_SCHEMA_VERSION}"
            )

        # Reconstruct record
        return CanonicalTaskRecord.from_dict(data)

    def list(self, state: LifecycleState | str | None = None) -> list[CanonicalTaskRecord]:
        """List all records, optionally filtered by lifecycle state.

        Args:
            state: Optional lifecycle state to filter by. If None, returns all records.

        Returns:
            List of CanonicalTaskRecord instances matching the filter.
        """
        from .lifecycle import CanonicalTaskRecord, LifecycleState

        records = []

        # Get all JSON files in tasks directory
        json_files = list(self.tasks_dir.glob("*.json"))

        for json_file in json_files:
            # Skip temp files
            if json_file.name.endswith(".tmp"):
                continue

            task_id = json_file.stem

            try:
                record = self.load(task_id)

                # Filter by state if specified
                if state is not None:
                    if isinstance(state, str):
                        target_state = LifecycleState(state)
                    else:
                        target_state = state

                    if record.state != target_state:
                        continue

                records.append(record)
            except (CorruptedRecordError, SchemaVersionError, KeyError):
                # Skip corrupted or invalid files
                continue

        return records


__all__ = [
    "CorruptedRecordError",
    "PortableTaskStore",
    "SchemaVersionError",
    "StorageError",
    "UnknownSchemaVersionError",
]