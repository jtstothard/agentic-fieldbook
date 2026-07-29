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
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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


class InvalidTaskIDError(StorageError, ValueError):
    """Raised when a task ID could escape the store's tasks directory."""


SUPPORTED_SCHEMA_VERSION = "fieldbook.task-record.v1"
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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
        # A store is safe for concurrent callers within one process. Files remain
        # the cross-process coordination boundary; os.replace provides atomicity.
        self._lock = threading.RLock()
        self._last_errors: list[tuple[Path, Exception]] = []

    @property
    def diagnostics(self) -> tuple[tuple[Path, Exception], ...]:
        """Errors skipped by the most recent ``list`` call."""
        with self._lock:
            return tuple(self._last_errors)

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if not isinstance(task_id, str) or not task_id or not _SAFE_TASK_ID.fullmatch(task_id):
            raise InvalidTaskIDError(
                "task_id must contain only ASCII letters, digits, '_' or '-'"
            )

    def save(self, record: CanonicalTaskRecord) -> None:
        """Save a record to disk with atomic write guarantees.

        The record is serialized to JSON and written to a temporary file,
        then atomically renamed to the final location using os.replace().

        Args:
            record: The CanonicalTaskRecord to save.
        """
        task_id = record.task_id
        self._validate_task_id(task_id)
        with self._lock:
            data = record.to_dict()
            provenance = getattr(record, "_provenance", None)
            if provenance is not None:
                data["provenance"] = provenance
            temp_file = self.tasks_dir / f"{task_id}.json.tmp"
            target_file = self.tasks_dir / f"{task_id}.json"
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_file, target_file)
            finally:
                # Covers serialization/write/replace failures and stale temp files.
                try:
                    temp_file.unlink(missing_ok=True)
                except OSError:
                    pass

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

        self._validate_task_id(task_id)
        with self._lock:
            target_file = self.tasks_dir / f"{task_id}.json"

            if not target_file.exists():
                raise KeyError(f"Task not found: {task_id}")

            try:
                with open(target_file, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                raise CorruptedRecordError(f"Corrupted record file for task {task_id}: {exc}") from exc

            if not isinstance(data, dict):
                raise CorruptedRecordError(
                    f"Corrupted record file {target_file}: "
                    f"expected JSON object root, got {type(data).__name__}"
                )

            schema = data.get("schema")
            if schema is None:
                raise SchemaVersionError(f"Record {task_id} missing schema version")
            if schema != SUPPORTED_SCHEMA_VERSION:
                raise UnknownSchemaVersionError(
                    f"Record {task_id} has unsupported schema version: {schema}. "
                    f"Supported: {SUPPORTED_SCHEMA_VERSION}"
                )

            try:
                record = CanonicalTaskRecord.from_dict(data)
            except (AttributeError, TypeError, KeyError) as exc:
                raise CorruptedRecordError(
                    f"Corrupted record file {target_file}: invalid record structure: {exc}"
                ) from exc
            if "provenance" in data:
                setattr(record, "_provenance", data["provenance"])
            return record

    def list(
        self,
        state: LifecycleState | str | None = None,
        *,
        on_error: Callable[[Path, Exception], None] | None = None,
    ) -> list[CanonicalTaskRecord]:
        """List all records, optionally filtered by lifecycle state.

        Args:
            state: Optional lifecycle state to filter by. If None, returns all records.

        Returns:
            List of CanonicalTaskRecord instances matching the filter.
        """
        from .lifecycle import CanonicalTaskRecord, LifecycleState

        with self._lock:
            records = []
            self._last_errors = []
            target_state = LifecycleState(state) if isinstance(state, str) else state

            for json_file in self.tasks_dir.glob("*.json"):
                task_id = json_file.stem
                try:
                    self._validate_task_id(task_id)
                    record = self.load(task_id)
                    if target_state is not None and record.state != target_state:
                        continue
                    records.append(record)
                except (CorruptedRecordError, SchemaVersionError, KeyError, ValueError) as exc:
                    self._last_errors.append((json_file, exc))
                    if on_error is not None:
                        on_error(json_file, exc)

            return records


__all__ = [
    "CorruptedRecordError",
    "InvalidTaskIDError",
    "PortableTaskStore",
    "SchemaVersionError",
    "StorageError",
    "UnknownSchemaVersionError",
]