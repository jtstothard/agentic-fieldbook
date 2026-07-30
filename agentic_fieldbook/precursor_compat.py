"""Precursor compatibility adapter for Fieldbook v1.

This module provides lossless import of old AOS (Agentic Operating System)
artifacts from the precursor repository into Fieldbook CanonicalTaskRecord format.

The adapter:
- Parses precursor markdown files (decisions, tickets, calibration records, metric envelopes)
- Maps precursor fields to Fieldbook TaskContract fields
- Preserves unknown/extra fields in provenance metadata
- Infers missing fields (risk class, lifecycle state) from context
- Reports non-lossless mappings and any warnings
- Creates stable task IDs derived from source file names

Slice 4 scope: read/import only. Write/export is a future slice.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .lifecycle import CanonicalTaskRecord, LifecycleState, TaskContract

from .lifecycle import (
    CanonicalTaskRecord,
    LifecycleState,
    TaskContract,
)


class PrecursorArtifactType(str, Enum):
    """Types of precursor artifacts that can be imported."""

    DECISION = "decision"
    TICKET = "ticket"
    CALIBRATION = "calibration"
    SPEC = "spec"
    UNKNOWN = "unknown"


@dataclass
class CompatibilityReport:
    """Report on the compatibility and mapping quality of an import.

    Attributes:
        source_file: Name/path of the source file
        source_type: Type of precursor artifact
        mapped_cleanly: Fields that were mapped 1:1 to Fieldbook schema
        inferred: Fields that were inferred from context with rationale
        warnings: Any warnings about non-ideal mappings
        lost_fields: Fields that could not be preserved (should be empty for lossless import)
        provenance: All unknown/extra fields preserved in metadata
    """

    source_file: str
    source_type: str
    mapped_cleanly: dict[str, str] = field(default_factory=dict)
    inferred: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    lost_fields: list[str] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)

    def is_lossless(self) -> bool:
        """Return True if the import was completely lossless."""
        return len(self.warnings) == 0 and len(self.lost_fields) == 0

    def with_provenance(self, provenance: dict[str, object]) -> "CompatibilityReport":
        """Return a new report with updated provenance."""
        return dataclasses.replace(self, provenance=provenance)


class PrecursorImportError(Exception):
    """Base error for precursor import failures."""

    pass


class UnsupportedFileTypeError(PrecursorImportError):
    """Raised when an unsupported file type is encountered."""

    pass


def infer_risk_class_from_scope(
    scope: tuple[str, ...],
    context: dict[str, object] | None = None,
) -> tuple[str, str]:
    """Infer risk class from scope text and context.

    Args:
        scope: Tuple of scope text strings
        context: Additional context (optional)

    Returns:
        (risk_class, rationale) where risk_class is "low", "medium", or "high"
    """
    scope_text = " ".join(scope)
    context_text = " ".join(str(value) for value in (context or {}).values())
    combined_text = f"{scope_text} {context_text}".lower()

    # High-risk checks deliberately run before low-risk checks.
    high_keywords = [
        "production", "prod", "deploy", "delete", "drop", "truncate", "destroy",
        "secret", "billing", "access", "permission", "downtime", "release",
        "migration", "database", "data loss",
    ]

    # Medium-risk indicators
    medium_keywords = [
        "bounded",
        "rollback",
        "mutation",
        "change",
        "modify",
        "refactor",
        "feature",
        "fix",
    ]

    # Low-risk indicators
    low_keywords = [
        "local",
        "documentation",
        "doc",
        "read",
        "research",
        "analysis",
        "reversible",
        "test",
        "testing",
    ]

    # Check for high risk
    for keyword in high_keywords:
        if keyword in combined_text:
            return (
                "high",
                f"Inferred as high risk due to '{keyword}' keyword in scope or context",
            )

    # Check for low risk
    low_count = sum(1 for kw in low_keywords if kw in combined_text)
    if low_count >= 2 or (low_count == 1 and "local" in combined_text):
        return (
            "low",
            "Inferred as low risk due to local/reversible/documentation nature",
        )

    # Default to medium risk
    return (
        "medium",
        "Default inference: medium risk for unclear scope",
    )


class PrecursorImportAdapter:
    """Adapter for importing precursor AOS artifacts into Fieldbook.

    The adapter handles:
    - Parsing markdown files from the precursor repository
    - Mapping precursor fields to Fieldbook TaskContract
    - Inferring missing fields from context
    - Preserving all original data in provenance
    - Generating compatibility reports
    """

    def __init__(self, precursor_repo_path: Path | str | None = None):
        """Initialize the adapter.

        Args:
            precursor_repo_path: Optional path to the precursor repository
        """
        self.precursor_repo_path = (
            Path(precursor_repo_path) if precursor_repo_path else None
        )

        # Lifecycle state mapping from precursor terminology to Fieldbook
        self.state_mapping: dict[str, LifecycleState] = {
            "proposed": LifecycleState.PROPOSED,
            "planned": LifecycleState.PLANNED,
            "approved": LifecycleState.APPROVED,
            "ready-for-agent": LifecycleState.PLANNED,  # Tickets ready for work
            "ready": LifecycleState.PLANNED,
            "executing": LifecycleState.EXECUTING,
            "in-progress": LifecycleState.EXECUTING,
            "complete": LifecycleState.REPORTED_COMPLETE,
            "completed": LifecycleState.VERIFIED,  # Historical assumption
            "verified": LifecycleState.VERIFIED,
            "blocked": LifecycleState.BLOCKED,
            "failed": LifecycleState.FAILED,
            "cancelled": LifecycleState.CANCELLED,
            "superseded": LifecycleState.SUPERSEDED,
            "decision recorded": LifecycleState.VERIFIED,
            "resolved": LifecycleState.VERIFIED,
        }

    def _detect_artifact_type(self, file_path: Path) -> PrecursorArtifactType:
        """Detect the type of precursor artifact from filename and content.

        Args:
            file_path: Path to the artifact file

        Returns:
            PrecursorArtifactType enum value
        """
        filename = file_path.name.lower()

        # Check by filename patterns
        if filename.startswith("decision-") or filename.startswith("decision_"):
            return PrecursorArtifactType.DECISION
        elif filename.startswith("ticket-") or filename.startswith("ticket_"):
            return PrecursorArtifactType.TICKET
        elif "calibration" in filename or "audit" in filename or "baseline" in filename:
            return PrecursorArtifactType.CALIBRATION
        elif filename.startswith("spec-") or filename.startswith("spec_"):
            return PrecursorArtifactType.SPEC

        # Try to detect from content
        try:
            content = file_path.read_text()

            if "**Status:** Decision recorded" in content:
                return PrecursorArtifactType.DECISION
            elif "**What to build:**" in content:
                return PrecursorArtifactType.TICKET
            elif "**Auditor:**" in content or "**Baseline Metrics**" in content:
                return PrecursorArtifactType.CALIBRATION
            elif "## Problem Statement" in content and "## Solution" in content:
                return PrecursorArtifactType.SPEC
        except (OSError, UnicodeDecodeError):
            pass

        return PrecursorArtifactType.UNKNOWN

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, str], str]:
        """Parse YAML frontmatter from markdown content.

        Args:
            content: Full markdown content

        Returns:
            (frontmatter_dict, remaining_content)
        """
        frontmatter = {}
        remaining = content

        if content.startswith("---"):
            # Find the end of frontmatter
            end_marker = content.find("\n---\n", 4)
            if end_marker != -1:
                frontmatter_text = content[4:end_marker]
                remaining = content[end_marker + 5 :]

                # Parse simple key-value pairs
                for line in frontmatter_text.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, value = line.split(":", 1)
                        frontmatter[key.strip()] = value.strip()

        return frontmatter, remaining

    def _extract_sections(self, content: str) -> dict[str, str]:
        """Extract markdown sections as a dictionary.

        Args:
            content: Markdown content without frontmatter

        Returns:
            Dict mapping section titles to content
        """
        sections = {}
        current_section = "introduction"
        current_content = []

        lines = content.split("\n")
        for line in lines:
            if line.startswith("#"):
                # Save previous section
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()

                # Start new section
                current_section = line.lstrip("#").strip().lower()
                current_content = []
            else:
                current_content.append(line)

        # Save last section
        if current_content:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _parse_markdown_file(self, file_path: Path) -> dict[str, object]:
        """Parse a markdown file, reporting (rather than raising) bad frontmatter."""
        content = file_path.read_text()
        frontmatter, remaining_content = self._parse_frontmatter(content)
        sections = self._extract_sections(remaining_content)
        warnings: list[str] = []
        if content.startswith("---"):
            end_marker = content.find("\n---\n", 4)
            if end_marker == -1:
                warnings.append("Malformed frontmatter: missing closing --- marker")
            else:
                frontmatter_text = content[4:end_marker]
                malformed = [
                    line.strip() for line in frontmatter_text.splitlines()
                    if line.strip() and ":" not in line
                ]
                if malformed:
                    warnings.append(
                        "Malformed frontmatter: lines without key/value separator: "
                        + ", ".join(malformed)
                    )

        return {
            "source_file": str(file_path),
            "source_type": self._detect_artifact_type(file_path).value,
            "frontmatter": frontmatter,
            "sections": sections,
            "raw_content": content,
            "filename": file_path.name,
            "_compatibility_warnings": warnings,
        }

    def parse_decision_file(self, file_path: Path) -> dict[str, object]:
        """Parse a decision markdown file.

        Args:
            file_path: Path to the decision file

        Returns:
            Parsed decision data
        """
        parsed = self._parse_markdown_file(file_path)

        # Extract decision-specific fields
        sections = parsed.get("sections", {})

        parsed["status"] = sections.get("status", "unknown")
        parsed["decision"] = sections.get("decision", "")
        parsed["rationale"] = sections.get("rationale", "")

        return parsed

    def parse_ticket_file(self, file_path: Path) -> dict[str, object]:
        """Parse a ticket markdown file.

        Args:
            file_path: Path to the ticket file

        Returns:
            Parsed ticket data
        """
        parsed = self._parse_markdown_file(file_path)
        sections = parsed.get("sections", {})
        frontmatter = parsed.get("frontmatter", {})

        # Ensure sections and frontmatter are dicts
        if not isinstance(sections, dict):
            sections = {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}

        # Extract ticket-specific fields
        parsed["status"] = str(
            frontmatter.get("status", sections.get("status", "unknown"))
        )

        # Parse "What to build" section
        what_to_build = sections.get("what to build", "")
        parsed["objective"] = str(what_to_build) if what_to_build else ""

        # Parse "Blocked by"
        blocked_by = sections.get("blocked by", "")
        parsed["blocked_by"] = str(blocked_by) if blocked_by else ""

        # Extract acceptance criteria
        acceptance_section = sections.get("acceptance criteria", "")
        acceptance_criteria = []
        for line in str(acceptance_section).split("\n"):
            line = line.strip()
            if line.startswith("-"):
                acceptance_criteria.append(line[1:].strip())
        parsed["acceptance_criteria"] = tuple(acceptance_criteria)

        return parsed

    def parse_calibration_file(self, file_path: Path) -> dict[str, object]:
        """Parse a calibration/metric envelope file.

        Args:
            file_path: Path to the calibration file

        Returns:
            Parsed calibration data
        """
        parsed = self._parse_markdown_file(file_path)
        sections = parsed.get("sections", {})

        # Ensure sections is a dict
        if not isinstance(sections, dict):
            sections = {}

        parsed["status"] = str(sections.get("status", "unknown"))
        parsed["executive_summary"] = str(sections.get("executive summary", ""))
        parsed["audit_criteria"] = str(sections.get("audit criteria", ""))
        parsed["results"] = str(sections.get("results", ""))

        return parsed

    def parse_markdown_file(self, file_path: Path) -> dict[str, object]:
        """Parse any markdown file using auto-detection.

        Args:
            file_path: Path to the markdown file

        Returns:
            Parsed data
        """
        artifact_type = self._detect_artifact_type(file_path)

        if artifact_type == PrecursorArtifactType.DECISION:
            return self.parse_decision_file(file_path)
        elif artifact_type == PrecursorArtifactType.TICKET:
            return self.parse_ticket_file(file_path)
        elif artifact_type == PrecursorArtifactType.CALIBRATION:
            return self.parse_calibration_file(file_path)
        else:
            # Generic markdown parsing
            return self._parse_markdown_file(file_path)

    def map_to_task_contract(
        self, parsed_data: dict[str, object]
    ) -> tuple[TaskContract, CompatibilityReport]:
        """Map parsed precursor data to a Fieldbook TaskContract.

        Args:
            parsed_data: Parsed precursor artifact data

        Returns:
            (TaskContract, CompatibilityReport) tuple
        """
        source_type = parsed_data.get("source_type", "unknown")
        source_file = parsed_data.get("filename", "unknown")

        raw_warnings = parsed_data.get("_compatibility_warnings", [])
        warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
        report = CompatibilityReport(
            source_file=source_file,
            source_type=source_type,
            warnings=warnings,
        )

        # Track provenance - start with all parsed fields
        provenance: dict[str, object] = {}
        known_fields = {
            "objective",
            "scope",
            "exclusions",
            "risk_class",
            "capabilities",
            "acceptance_criteria",
            "required_evidence",
            "domain",
        }

        # Extract objective
        objective = ""
        if "objective" in parsed_data:
            objective = str(parsed_data["objective"])
            report.mapped_cleanly["objective"] = "direct"
        elif "decision" in parsed_data:
            objective = str(parsed_data["decision"])
            report.mapped_cleanly["objective"] = "from decision section"
        elif "executive_summary" in parsed_data:
            objective = str(parsed_data["executive_summary"])
            report.mapped_cleanly["objective"] = "from executive summary"
        else:
            objective = f"Imported {source_type} from {source_file}"
            report.inferred["objective"] = "generated from source info"

        objective = objective.strip()
        if not objective:
            objective = "Imported precursor artifact"
            report.warnings.append("Empty objective, using default")

        # Extract scope from sections or content
        scope_items = []
        sections = parsed_data.get("sections", {})

        # Ensure sections is a dict
        if not isinstance(sections, dict):
            sections = {}

        # Look for scope-like sections
        for section_name in ["scope", "what to build", "acceptance criteria"]:
            if section_name in sections:
                section_content = str(sections[section_name])
                for line in section_content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        scope_items.append(line)

        # Add filename to scope for provenance
        scope_items.append(f"Source: {source_file}")

        scope = tuple(scope_items) if scope_items else ("precursor artifact",)
        report.mapped_cleanly["scope"] = "extracted from sections"

        # Exclusions - usually empty in precursor artifacts
        exclusions: tuple[str, ...] = ()
        report.mapped_cleanly["exclusions"] = "default empty"

        # Risk class - infer if not present
        risk_class = "medium"  # Default
        if "risk_class" in parsed_data:
            risk_class = str(parsed_data["risk_class"])
            report.mapped_cleanly["risk_class"] = "direct"
        else:
            risk_class, rationale = infer_risk_class_from_scope(scope)
            report.inferred["risk_class"] = rationale

        # Capabilities - extract from scope or sections
        capabilities: tuple[str, ...] = ()
        scope_text = " ".join(scope).lower()

        # Look for capability keywords
        capability_keywords = {
            "read": "read",
            "write": "write",
            "execute": "execute",
            "deploy": "deployment",
            "delete": "delete",
            "secret": "secret-read",
            "billing": "billing-change",
            "access": "access-grant",
        }

        found_capabilities = []
        for keyword, capability in capability_keywords.items():
            if keyword in scope_text:
                found_capabilities.append(capability)

        if found_capabilities:
            capabilities = tuple(found_capabilities)
            report.mapped_cleanly["capabilities"] = "inferred from scope keywords"
        else:
            report.inferred["capabilities"] = "no capabilities detected, using empty"

        # Acceptance criteria
        acceptance_criteria: tuple[str, ...] = ()
        if "acceptance_criteria" in parsed_data and parsed_data["acceptance_criteria"]:
            ac = parsed_data["acceptance_criteria"]
            if isinstance(ac, tuple):
                acceptance_criteria = ac
            elif isinstance(ac, list):
                acceptance_criteria = tuple(str(item) for item in ac)
            report.mapped_cleanly["acceptance_criteria"] = "direct"
        else:
            acceptance_criteria = ("Artifact imported from precursor",)
            report.inferred["acceptance_criteria"] = "default for imported artifact"

        # Required evidence - infer based on risk class
        if risk_class == "high":
            required_evidence = (
                "Verification of completion",
                "Rollback/recovery plan",
                "Test results",
            )
        elif risk_class == "medium":
            required_evidence = ("Verification of completion", "Test results")
        else:
            required_evidence = ("Verification of completion",)

        report.inferred["required_evidence"] = f"based on risk class: {risk_class}"

        # Domain - include precursor provenance
        domain_parts = [f"precursor:{source_type}", f"source:{source_file}"]
        if "frontmatter" in parsed_data:
            domain_parts.append("has_frontmatter")
        domain = " ".join(domain_parts)
        report.mapped_cleanly["domain"] = "includes provenance"

        # Collect unknown fields for provenance
        for key, value in parsed_data.items():
            if key not in known_fields and key not in {
                "source_file",
                "source_type",
                "frontmatter",
                "sections",
                "raw_content",
                "filename",
                "status",
                "decision",
                "rationale",
                "objective",
                "blocked_by",
                "executive_summary",
                "audit_criteria",
                "results",
                "_compatibility_warnings",
            }:
                provenance[key] = value

        # Add frontmatter to provenance
        if "frontmatter" in parsed_data and parsed_data["frontmatter"]:
            provenance["frontmatter"] = parsed_data["frontmatter"]

        report.provenance = provenance

        # Create contract ID from source
        contract_id = f"precursor-{source_type}-{source_file.replace('.md', '')}"

        try:
            contract = TaskContract(
                contract_id=contract_id,
                objective=objective,
                scope=scope,
                exclusions=exclusions,
                risk_class=risk_class,
                capabilities=capabilities,
                acceptance_criteria=acceptance_criteria,
                required_evidence=required_evidence,
                domain=domain,
                revision=1,
            )
        except ValueError as e:
            # If high-risk contract lacks rollback evidence, add it
            if "rollback" in str(e).lower() and risk_class == "high":
                required_evidence = (
                    "Verification of completion",
                    "Rollback/recovery plan",
                    "Test results",
                )
                contract = TaskContract(
                    contract_id=contract_id,
                    objective=objective,
                    scope=scope,
                    exclusions=exclusions,
                    risk_class=risk_class,
                    capabilities=capabilities,
                    acceptance_criteria=acceptance_criteria,
                    required_evidence=required_evidence,
                    domain=domain,
                    revision=1,
                )
                report.inferred["rollback_evidence"] = "added to satisfy high-risk contract validation"
            else:
                raise

        return contract, report

    def _generate_task_id(self, source_file: Path) -> str:
        """Generate a stable task ID from the source file.

        Args:
            source_file: Path to the source file

        Returns:
            Stable task ID string
        """
        filename = source_file.name
        # Use SHA256 hash of filename for stability
        hash_obj = hashlib.sha256(filename.encode())
        short_hash = hash_obj.hexdigest()[:12]
        return f"precursor-{filename.replace('.md', '')}-{short_hash}"

    def infer_lifecycle_state(
        self, parsed_data: dict[str, object]
    ) -> tuple[LifecycleState, str]:
        """Infer lifecycle state from precursor artifact.

        Args:
            parsed_data: Parsed precursor data

        Returns:
            (LifecycleState, rationale) tuple
        """
        status_value = parsed_data.get("status", "unknown")
        status = str(status_value).strip().lower()

        # Match complete normalized status tokens/phrases, not substrings:
        # ``ready`` must not match ``not-ready`` or ``readiness-check``.
        for precursor_state, fieldbook_state in sorted(
            self.state_mapping.items(), key=lambda item: len(item[0]), reverse=True
        ):
            pattern = r"(?<![a-z0-9-])" + re.escape(precursor_state) + r"(?![a-z0-9-])"
            if re.search(pattern, status):
                return fieldbook_state, f"Mapped from status: {status}"

        # Default based on artifact type
        source_type = parsed_data.get("source_type", "unknown")
        if source_type == "decision":
            return LifecycleState.VERIFIED, "Decisions are considered verified"
        elif source_type == "ticket":
            return LifecycleState.PLANNED, "Tickets default to planned state"
        elif source_type == "calibration":
            return LifecycleState.VERIFIED, "Calibration records are verified"

        return LifecycleState.PROPOSED, "Default to proposed for unknown artifacts"

    def import_from_precursor(
        self, file_path: Path, task_id: str | None = None
    ) -> CanonicalTaskRecord:
        """Import a precursor artifact into a CanonicalTaskRecord.

        Args:
            file_path: Path to the precursor artifact file
            task_id: Optional custom task ID (auto-generated if None)

        Returns:
            CanonicalTaskRecord instance

        Raises:
            UnsupportedFileTypeError: If file type is not supported
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_path.suffix != ".md":
            raise UnsupportedFileTypeError(f"Unsupported file type: {file_path.suffix}")

        # Parse the file
        parsed_data = self.parse_markdown_file(file_path)

        # Map to contract
        contract, compatibility_report = self.map_to_task_contract(parsed_data)

        # Generate task ID
        if task_id is None:
            task_id = self._generate_task_id(file_path)

        # Imported status is historical context, not proof of newly completed work.
        # Terminal states are retained only when the source carries explicit history
        # and evidence; otherwise import at PLANNED so normal lifecycle gates apply.
        initial_state, state_rationale = self.infer_lifecycle_state(parsed_data)
        has_historical_support = bool(parsed_data.get("history")) and bool(parsed_data.get("evidence"))
        if initial_state in {
            LifecycleState.VERIFIED,
            LifecycleState.FAILED,
            LifecycleState.CANCELLED,
            LifecycleState.SUPERSEDED,
        } and not has_historical_support:
            initial_state = LifecycleState.PLANNED
            compatibility_report.warnings.append(
                f"Historical terminal state downgraded to planned on import: {state_rationale}"
            )

        record = CanonicalTaskRecord.create(contract, task_id=task_id)
        if initial_state is LifecycleState.PLANNED:
            record.transition(LifecycleState.PLANNED, actor="precursor-import", reason=state_rationale)
        elif initial_state is not LifecycleState.PROPOSED:
            # Unsupported historical execution states are intentionally safe.
            compatibility_report.warnings.append(
                f"Historical state {initial_state.value} imported as proposed"
            )

        record._provenance = {
            "compatibility_report": {
                "source_file": compatibility_report.source_file,
                "source_type": compatibility_report.source_type,
                "mapped_cleanly": compatibility_report.mapped_cleanly,
                "inferred": compatibility_report.inferred,
                "warnings": compatibility_report.warnings,
                "lost_fields": compatibility_report.lost_fields,
            },
            "precursor_extras": compatibility_report.provenance,
        }

        return record

    def analyze_compatibility(self, file_path: Path) -> CompatibilityReport:
        """Analyze a precursor file without importing it.

        Args:
            file_path: Path to the precursor artifact file

        Returns:
            CompatibilityReport instance
        """
        parsed_data = self.parse_markdown_file(file_path)
        contract, report = self.map_to_task_contract(parsed_data)
        return report

    def batch_import_from_directory(
        self, directory: Path | str
    ) -> list[CanonicalTaskRecord]:
        """Import all supported precursor artifacts from a directory.

        Args:
            directory: Path to the directory containing precursor artifacts

        Returns:
            List of CanonicalTaskRecord instances
        """
        directory = Path(directory)

        if not directory.is_dir():
            raise ValueError(f"Not a directory: {directory}")

        records = []

        for file_path in directory.glob("*.md"):
            try:
                record = self.import_from_precursor(file_path)
                records.append(record)
            except (UnsupportedFileTypeError, ValueError) as e:
                # Skip files that can't be imported
                continue

        return records


__all__ = [
    "CompatibilityReport",
    "PrecursorArtifactType",
    "PrecursorImportAdapter",
    "PrecursorImportError",
    "UnsupportedFileTypeError",
    "infer_risk_class_from_scope",
]