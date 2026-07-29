"""Test suite for Fieldbook v1 precursor compatibility adapter.

Tests follow TDD approach: write failing tests first, then implement to make them pass.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from agentic_fieldbook.lifecycle import (
    CanonicalTaskRecord,
    LifecycleState,
    TaskContract,
)
from agentic_fieldbook.precursor_compat import (
    CompatibilityReport,
    PrecursorImportAdapter,
    infer_risk_class_from_scope,
)


class TestCompatibilityReport:
    """Test the CompatibilityReport dataclass."""

    def test_report_creation(self):
        """Report should initialize with empty tracking."""
        report = CompatibilityReport(
            source_file="test.md",
            source_type="decision",
            mapped_cleanly={},
            inferred={},
            warnings=[],
            lost_fields=[],
        )

        assert report.source_file == "test.md"
        assert report.source_type == "decision"
        assert report.mapped_cleanly == {}
        assert report.inferred == {}
        assert report.warnings == []
        assert report.lost_fields == []

    def test_report_is_lossless(self):
        """Report should indicate losslessness when no warnings or lost fields."""
        report = CompatibilityReport(
            source_file="test.md",
            source_type="decision",
            mapped_cleanly={"objective": "test objective"},
            inferred={"risk_class": "low"},
            warnings=[],
            lost_fields=[],
        )

        assert report.is_lossless() is True

    def test_report_not_lossless_with_warnings(self):
        """Report should not be lossless if warnings exist."""
        report = CompatibilityReport(
            source_file="test.md",
            source_type="decision",
            mapped_cleanly={},
            inferred={},
            warnings=["Could not map acceptance_criteria"],
            lost_fields=[],
        )

        assert report.is_lossless() is False

    def test_report_not_lossless_with_lost_fields(self):
        """Report should not be lossless if fields were lost."""
        report = CompatibilityReport(
            source_file="test.md",
            source_type="decision",
            mapped_cleanly={},
            inferred={},
            warnings=[],
            lost_fields=["custom_metadata"],
        )

        assert report.is_lossless() is False


class TestRiskClassInference:
    """Test risk class inference from scope and context."""

    def test_low_risk_local_reversible(self):
        """Local, reversible work should be low risk."""
        scope = ("local file modification", "documentation update")
        risk_class, rationale = infer_risk_class_from_scope(scope)

        assert risk_class == "low"
        assert "local" in rationale.lower()

    def test_medium_risk_bounded_mutation(self):
        """Bounded mutation with clear rollback should be medium risk."""
        scope = ("bounded code change", "with rollback plan")
        risk_class, rationale = infer_risk_class_from_scope(scope)

        assert risk_class == "medium"
        assert "default" in rationale.lower()

    def test_high_risk_production_mutation(self):
        """Production scope should be high risk."""
        scope = ("production deployment", "live database migration")
        risk_class, rationale = infer_risk_class_from_scope(scope)

        assert risk_class == "high"
        assert "production" in rationale.lower()

    def test_high_risk_destructive_keywords(self):
        """Destructive keywords should trigger high risk."""
        scope = ("delete production data", "drop database tables")
        risk_class, rationale = infer_risk_class_from_scope(scope)

        assert risk_class == "high"
        assert "production" in rationale.lower()

    def test_medium_risk_default(self):
        """Unclear scope should default to medium risk."""
        scope = ("general task", "some work")
        risk_class, rationale = infer_risk_class_from_scope(scope)

        assert risk_class == "medium"
        assert "default" in rationale.lower()


class TestPrecursorImportAdapter:
    """Test the PrecursorImportAdapter class."""

    def test_adapter_initialization(self):
        """Adapter should initialize with default mappings."""
        adapter = PrecursorImportAdapter()

        assert adapter.precursor_repo_path is None
        assert adapter.state_mapping is not None
        assert LifecycleState.PROPOSED in adapter.state_mapping.values()

    def test_adapter_with_repo_path(self):
        """Adapter should accept a repo path."""
        adapter = PrecursorImportAdapter(
            precursor_repo_path="/tmp/test-repo"
        )

        assert adapter.precursor_repo_path == Path("/tmp/test-repo")

    def test_parse_decision_file_simple(self, sample_decision_path):
        """Should parse a simple decision markdown file."""
        adapter = PrecursorImportAdapter()

        result = adapter.parse_decision_file(sample_decision_path)

        assert result is not None
        assert "source_type" in result
        assert result["source_type"] == "decision"
        assert "raw_content" in result

    def test_parse_decision_file_extracts_sections(self, sample_decision_path):
        """Should extract markdown sections from decision files."""
        adapter = PrecursorImportAdapter()

        result = adapter.parse_decision_file(sample_decision_path)

        assert "sections" in result
        assert isinstance(result["sections"], dict)

    def test_parse_ticket_file_simple(self, sample_ticket_path):
        """Should parse a simple ticket markdown file."""
        adapter = PrecursorImportAdapter()

        result = adapter.parse_ticket_file(sample_ticket_path)

        assert result is not None
        assert "source_type" in result
        assert result["source_type"] == "ticket"
        assert "raw_content" in result

    def test_parse_ticket_file_extracts_status(self, sample_ticket_path):
        """Should extract status from ticket files."""
        adapter = PrecursorImportAdapter()

        result = adapter.parse_ticket_file(sample_ticket_path)

        assert "status" in result
        assert "blocked_by" in result

    def test_parse_calibration_file(self, sample_calibration_path):
        """Should parse calibration/metric files."""
        adapter = PrecursorImportAdapter()

        result = adapter.parse_calibration_file(sample_calibration_path)

        assert result is not None
        assert "source_type" in result
        assert result["source_type"] == "calibration"

    def test_map_decision_to_contract(self, sample_decision_path):
        """Should map decision fields to TaskContract."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_decision_file(sample_decision_path)
        contract, report = adapter.map_to_task_contract(parsed)

        assert contract is not None
        assert isinstance(contract, TaskContract)
        assert isinstance(report, CompatibilityReport)
        assert report.source_type == "decision"
        assert contract.objective != ""

    def test_map_ticket_to_contract(self, sample_ticket_path):
        """Should map ticket fields to TaskContract."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_ticket_file(sample_ticket_path)
        contract, report = adapter.map_to_task_contract(parsed)

        assert contract is not None
        assert isinstance(contract, TaskContract)
        assert isinstance(report, CompatibilityReport)
        assert report.source_type == "ticket"
        # Ticket files should have more structure
        assert len(contract.scope) > 0

    def test_map_calibration_to_contract(self, sample_calibration_path):
        """Should map calibration fields to TaskContract."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_calibration_file(sample_calibration_path)
        contract, report = adapter.map_to_task_contract(parsed)

        assert contract is not None
        assert isinstance(contract, TaskContract)
        assert isinstance(report, CompatibilityReport)
        assert report.source_type == "calibration"

    def test_preserve_unknown_fields_in_provenance(self, sample_ticket_path):
        """Should preserve unknown fields in provenance."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_ticket_file(sample_ticket_path)
        # Add a custom field
        parsed["custom_field"] = "custom_value"
        parsed["another_unknown"] = {"nested": "data"}

        contract, report = adapter.map_to_task_contract(parsed)

        # Unknown fields should be preserved in provenance
        assert "custom_field" in report.provenance
        assert "another_unknown" in report.provenance
        # May have warnings due to missing objective, but fields should be preserved
        assert len(report.lost_fields) == 0

    def test_infer_risk_class_when_missing(self, sample_decision_path):
        """Should infer risk class when not explicitly present."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_decision_file(sample_decision_path)
        # Remove risk class if present
        parsed.pop("risk_class", None)

        contract, report = adapter.map_to_task_contract(parsed)

        assert contract.risk_class in {"low", "medium", "high"}
        assert "risk_class" in report.inferred
        assert "default" in report.inferred["risk_class"].lower()

    def test_report_unmappable_fields_as_warnings(self, sample_ticket_path):
        """Should report fields that couldn't be mapped."""
        adapter = PrecursorImportAdapter()

        parsed = adapter.parse_ticket_file(sample_ticket_path)
        # Add a field that clearly won't map
        parsed["some_arbitrary_structure"] = {
            "nested": {
                "deep": {
                    "value": "that doesn't fit Fieldbook schema"
                }
            }
        }

        contract, report = adapter.map_to_task_contract(parsed)

        # The field should be preserved, not lost
        assert "some_arbitrary_structure" in report.provenance
        # No fields should be lost, but there may be warnings
        assert len(report.lost_fields) == 0

    def test_import_decision_to_canonical_record(self, sample_decision_path):
        """Should import decision to CanonicalTaskRecord."""
        adapter = PrecursorImportAdapter()

        record = adapter.import_from_precursor(sample_decision_path)

        assert record is not None
        assert isinstance(record, CanonicalTaskRecord)
        assert record.task_id != ""
        # Historical terminal statuses are imported safely, not treated as new proof.
        assert record.state == LifecycleState.PLANNED
        assert any("downgraded" in warning for warning in getattr(record, "_provenance")["compatibility_report"]["warnings"])

    def test_import_ticket_to_canonical_record(self, sample_ticket_path):
        """Should import ticket to CanonicalTaskRecord."""
        adapter = PrecursorImportAdapter()

        record = adapter.import_from_precursor(sample_ticket_path)

        assert record is not None
        assert isinstance(record, CanonicalTaskRecord)
        assert record.task_id != ""

    def test_import_creates_stable_task_id(self, sample_decision_path):
        """Task ID should be stable and derived from source."""
        adapter = PrecursorImportAdapter()

        record1 = adapter.import_from_precursor(sample_decision_path)
        record2 = adapter.import_from_precursor(sample_decision_path)

        assert record1.task_id == record2.task_id
        # Task ID should include the source filename
        assert "decision" in record1.task_id.lower() or "ticket" in record1.task_id.lower()

    def test_import_includes_provenance_in_record(self, sample_decision_path):
        """Imported record should include provenance info."""
        adapter = PrecursorImportAdapter()

        record = adapter.import_from_precursor(sample_decision_path)

        # Provenance is stored as a private attribute on the record
        assert hasattr(record, "_provenance")
        assert "compatibility_report" in record._provenance
        assert "precursor_extras" in record._provenance
        assert "source_file" in record._provenance["compatibility_report"]

    def test_import_handles_markdown_with_frontmatter(self):
        """Should handle markdown files with YAML frontmatter."""
        adapter = PrecursorImportAdapter()

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test-frontmatter.md"
            test_file.write_text("""---
title: Test Document
date: 2026-07-24
status: ready
---

# Test Content

This is a test document with frontmatter.
""")
            parsed = adapter.parse_markdown_file(test_file)

            assert parsed is not None
            assert "frontmatter" in parsed
            assert parsed["frontmatter"]["title"] == "Test Document"

    def test_analyze_compatibility_for_file(self, sample_decision_path):
        """Should analyze compatibility without importing."""
        adapter = PrecursorImportAdapter()

        report = adapter.analyze_compatibility(sample_decision_path)

        assert report is not None
        assert isinstance(report, CompatibilityReport)
        assert report.source_file == sample_decision_path.name

    def test_batch_import_from_directory(self, sample_precursor_repo):
        """Should batch import all supported files from a directory."""
        adapter = PrecursorImportAdapter(
            precursor_repo_path=sample_precursor_repo
        )

        records = adapter.batch_import_from_directory(sample_precursor_repo)

        assert len(records) > 0
        assert all(isinstance(r, CanonicalTaskRecord) for r in records)

    def test_unknown_file_type_raises_error(self, sample_precursor_repo):
        """Should raise error for unknown file types."""
        adapter = PrecursorImportAdapter()

        with TemporaryDirectory() as tmpdir:
            unknown_file = Path(tmpdir) / "test.unknown"
            unknown_file.write_text("some content")

            from agentic_fieldbook.precursor_compat import UnsupportedFileTypeError
            with pytest.raises(UnsupportedFileTypeError, match="Unsupported file type"):
                adapter.import_from_precursor(unknown_file)


# Fixtures for test data

@pytest.fixture
def sample_decision_path(tmp_path):
    """Create a sample decision markdown file."""
    decision_file = tmp_path / "decision-01-destination.md"
    decision_file.write_text("""# Destination: setup-oriented agentic operating system

**Status:** Decision recorded during wayfinder charting

## Decision

The effort covers all agentic work across Hermes and coding agents, with the output being an operating specification and rollout plan rather than upstream feature implementation.

## Rationale

This approach allows for systematic development without premature implementation.
""")
    return decision_file


@pytest.fixture
def sample_ticket_path(tmp_path):
    """Create a sample ticket markdown file."""
    ticket_file = tmp_path / "ticket-01-contract-schema.md"
    ticket_file.write_text("""# 01 — Universal contract schema and templates

**What to build:** A versioned YAML/JSON contract schema plus Markdown templates that any agent can use to start a non-trivial task.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

## Acceptance Criteria

- Universal core contract schema defined in YAML
- Lifecycle state machine documented
- Standard stage output envelope template
- At least one domain extension stub
- Markdown presentation template

## Deliverable

A skill or template set that gives agents the contract structure and lifecycle rules.
""")
    return ticket_file


@pytest.fixture
def sample_calibration_path(tmp_path):
    """Create a sample calibration markdown file."""
    calibration_file = tmp_path / "calibration-audit-2026-07-24.md"
    calibration_file.write_text("""# Calibration Audit Report

**Date:** 2026-07-24
**Auditor:** Independent audit task

## Executive Summary

**Decision: APPROVE - Foundation artifacts ready for pilot deployment**

## Audit Criteria

- Blind-input integrity
- Attack lens coverage
- Independence proof mechanisms
- Fail-closed validation

## Results

All audit criteria passed successfully.
""")
    return calibration_file


@pytest.fixture
def sample_precursor_repo(tmp_path):
    """Create a sample precursor repository structure."""
    repo_dir = tmp_path / "precursor-repo"
    repo_dir.mkdir()

    # Create decision files
    (repo_dir / "decision-01-test.md").write_text("# Test Decision\n\n## Decision\nTest content")
    (repo_dir / "decision-02-another.md").write_text("# Another Decision\n\n## Decision\nAnother content")

    # Create ticket files
    (repo_dir / "ticket-01-work.md").write_text("# Ticket 01\n\n**What to build:** Something\n\n**Status:** ready")

    # Create calibration files
    (repo_dir / "calibration-audit.md").write_text("# Calibration\n\n## Summary\nAudit passed")

    return repo_dir