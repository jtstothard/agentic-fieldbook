"""
First-pilot flow for guided calibration data collection.

This module provides:
1. First-pilot flow accessible via command or wizard completion
2. Task guidance framework: low-risk qualification, selection, documentation
3. Calibration data capture: task outcome, reviewer scores, risk classification
4. Integration with existing calibration skills (contract-schema, lane-calibration, review-calibration)
5. Bypass by --minimal install: flow not available or referenced
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import yaml


# Constants
LOW_RISK_TASK_TYPES = {
    "documentation",
    "testing",
    "cleanup",
    "simple_refactor",
    "refactor",
}

HIGH_RISK_TASK_TYPES = {
    "deployment",
    "migration",
    "security",
    "core_logic",
    "database",
}


class TaskOutcome(str, Enum):
    """Valid task outcomes for pilot tasks."""
    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


def is_low_risk_task(task_summary: str, task_type: str) -> bool:
    """
    Determine if a task qualifies as low-risk for first pilot.

    Args:
        task_summary: Brief description of the task.
        task_type: Task category (e.g., 'documentation', 'refactor', 'deployment').

    Returns:
        bool: True if the task qualifies as low-risk.
    """
    # Task type-based qualification
    if task_type in HIGH_RISK_TASK_TYPES:
        return False

    if task_type in LOW_RISK_TASK_TYPES:
        return True

    # Heuristic-based qualification for other types
    dangerous_keywords = [
        "deploy", "production", "migrate", "delete", "drop", "truncate",
        "security", "auth", "payment", "billing", "credit", "bank",
        "database", "schema", "migration", "cascade", "force",
    ]

    task_lower = task_summary.lower()
    for keyword in dangerous_keywords:
        if keyword in task_lower:
            return False

    # Default to conservative: assume not low-risk
    return False


def suggest_low_risk_tasks() -> List[Dict[str, str]]:
    """
    Suggest example low-risk tasks suitable for first pilot.

    Returns:
        List of dicts with 'summary' and 'task_type' keys.
    """
    return [
        {
            "summary": "Update README with installation instructions",
            "task_type": "documentation",
        },
        {
            "summary": "Add unit tests for utils.py",
            "task_type": "testing",
        },
        {
            "summary": "Remove unused imports and fix PEP8 warnings",
            "task_type": "cleanup",
        },
        {
            "summary": "Extract function for email validation",
            "task_type": "simple_refactor",
        },
        {
            "summary": "Add docstrings to public API functions",
            "task_type": "documentation",
        },
        {
            "summary": "Fix typo in error message",
            "task_type": "simple_refactor",
        },
    ]


@dataclass
class ReviewerScore:
    """Reviewer score for a pilot task."""
    reviewer_profile: str
    scores: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "reviewer_profile": self.reviewer_profile,
            "scores": self.scores,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewerScore":
        """Create from dict."""
        return cls(
            reviewer_profile=data["reviewer_profile"],
            scores=data["scores"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


@dataclass
class PilotTask:
    """A single pilot task in the calibration process."""
    task_id: str
    task_type: str
    task_summary: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    outcome: Optional[TaskOutcome] = None
    duration_seconds: Optional[int] = None
    notes: Optional[str] = None
    reviewer_scores: List[ReviewerScore] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        data = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_summary": self.task_summary,
            "started_at": self.started_at.isoformat(),
            "reviewer_scores": [s.to_dict() for s in self.reviewer_scores],
        }

        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()

        if self.outcome:
            # Handle both Enum and string values
            if isinstance(self.outcome, TaskOutcome):
                data["outcome"] = self.outcome.value
            else:
                data["outcome"] = str(self.outcome)

        if self.duration_seconds is not None:
            data["duration_seconds"] = self.duration_seconds

        if self.notes:
            data["notes"] = self.notes

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PilotTask":
        """Create from dict."""
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_summary=data["task_summary"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            outcome=TaskOutcome(data["outcome"]) if data.get("outcome") else None,
            duration_seconds=data.get("duration_seconds"),
            notes=data.get("notes"),
            reviewer_scores=[ReviewerScore.from_dict(s) for s in data.get("reviewer_scores", [])],
        )


@dataclass
class CalibrationData:
    """
    Calibration data for a lane.

    Structure matches lane-calibration/references/calibration-schema.yaml.
    """
    lane_id: str
    calibration_status: str = "in_progress"
    created_at: datetime = field(default_factory=datetime.utcnow)
    pilot_tasks: List[PilotTask] = field(default_factory=list)

    def add_reviewer_score(
        self,
        task_id: str,
        reviewer_profile: str,
        scores: Dict[str, float],
    ) -> None:
        """Add a reviewer score to a specific task."""
        for task in self.pilot_tasks:
            if task.task_id == task_id:
                task.reviewer_scores.append(
                    ReviewerScore(
                        reviewer_profile=reviewer_profile,
                        scores=scores,
                    )
                )
                return

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization (matches lane-calibration schema)."""
        return {
            "lane_id": self.lane_id,
            "calibration_status": self.calibration_status,
            "created_at": self.created_at.isoformat(),
            "pilot_tasks": [t.to_dict() for t in self.pilot_tasks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationData":
        """Create from dict."""
        return cls(
            lane_id=data["lane_id"],
            calibration_status=data.get("calibration_status", "in_progress"),
            created_at=datetime.fromisoformat(data["created_at"]),
            pilot_tasks=[PilotTask.from_dict(t) for t in data.get("pilot_tasks", [])],
        )

    def save_to_file(self, path: Path) -> None:
        """Save calibration data to a YAML file."""
        data = self.to_dict()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load_from_file(cls, path: Path) -> "CalibrationData":
        """Load calibration data from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)


class FirstPilotSession:
    """
    Interactive session for guided first-pilot flow.

    Guides users through:
    1. Low-risk task selection
    2. Task execution (user runs it themselves)
    3. Outcome recording
    4. Calibration data capture
    """

    def __init__(self, config: Any):
        """Initialize session with lane-binding config."""
        self.config = config
        self.current_task: Optional[PilotTask] = None
        self.calibration_data: Optional[CalibrationData] = None

    def create_calibration_data(self, role: str) -> CalibrationData:
        """Create calibration data for the specified role."""
        profile = getattr(self.config, role)
        if not profile:
            raise ValueError(f"Role {role} is not bound")

        # Construct lane_id from profile and role
        # e.g., "aos-executor" -> "executor-aos-executor"
        lane_id = f"{role}-{profile}"

        self.calibration_data = CalibrationData(lane_id=lane_id)
        return self.calibration_data

    def get_task_suggestions(self) -> List[Dict[str, str]]:
        """Get suggested low-risk tasks."""
        return suggest_low_risk_tasks()

    def validate_risk(self, task_type: str, task_summary: str) -> bool:
        """Validate that a task is low-risk."""
        return is_low_risk_task(task_summary, task_type)

    def record_task_outcome(
        self,
        outcome: str,
        duration_seconds: int,
        notes: Optional[str] = None,
    ) -> None:
        """Record the outcome of the current task."""
        if not self.current_task:
            raise ValueError("No current task to record outcome for")

        self.current_task.outcome = TaskOutcome(outcome)
        self.current_task.duration_seconds = duration_seconds
        self.current_task.completed_at = datetime.utcnow()
        self.current_task.notes = notes

    def _format_outcome(self, outcome: Optional[TaskOutcome]) -> str:
        """Format task outcome for display."""
        if outcome is None:
            return "N/A"
        if isinstance(outcome, TaskOutcome):
            return outcome.value
        return str(outcome)

    def generate_calibration_output(self) -> str:
        """Generate calibration data output for user review."""
        if not self.current_task or not self.calibration_data:
            raise ValueError("No task or calibration data to output")

        lines = [
            "=" * 60,
            "First Pilot Calibration Data",
            "=" * 60,
            "",
            f"Lane: {self.calibration_data.lane_id}",
            f"Status: {self.calibration_data.calibration_status}",
            "",
            "Task:",
            f"  ID: {self.current_task.task_id}",
            f"  Type: {self.current_task.task_type}",
            f"  Summary: {self.current_task.task_summary}",
            f"  Outcome: {self._format_outcome(self.current_task.outcome)}",
            f"  Duration: {self.current_task.duration_seconds}s" if self.current_task.duration_seconds else "",
            "",
        ]

        if self.current_task.notes:
            lines.append(f"Notes: {self.current_task.notes}")

        if self.current_task.reviewer_scores:
            lines.append("")
            lines.append("Reviewer Scores:")
            for score in self.current_task.reviewer_scores:
                lines.append(f"  Reviewer: {score.reviewer_profile}")
                lines.append(f"  Scores: {score.scores}")

        lines.append("")
        lines.append("This data can be used to track calibration progress.")
        lines.append("Store in: ~/.hermes/calibration/lane-calibration.yaml")
        lines.append("")

        return "\n".join(lines)

    def run_interactive_flow(self) -> int:
        """Run the interactive first-pilot flow."""
        print("=" * 60)
        print("First Pilot Flow")
        print("=" * 60)
        print()
        print("This flow guides you through your first calibration pilot.")
        print("You'll select a low-risk task, execute it, and record the outcome.")
        print()

        # Check for bound roles
        bound_roles = []
        for role in ["planner", "executor", "reviewer", "verifier"]:
            profile = getattr(self.config, role)
            if profile:
                bound_roles.append((role, profile))

        if not bound_roles:
            print("ERROR: No roles are bound. Run 'hermes aos map-lanes' first.")
            return 1

        print("Available roles:")
        for i, (role, profile) in enumerate(bound_roles, 1):
            print(f"  {i}) {role} -> {profile}")

        # Select role
        if sys.stdin.isatty():
            role_choice = input(f"\nSelect role for pilot [1-{len(bound_roles)}]: ").strip()
            try:
                role_idx = int(role_choice) - 1
                if 0 <= role_idx < len(bound_roles):
                    role, profile = bound_roles[role_idx]
                else:
                    print("Invalid choice.")
                    return 1
            except ValueError:
                print("Invalid input.")
                return 1
        else:
            # Non-interactive: use first bound role
            role, profile = bound_roles[0]
            print(f"Auto-selected role: {role}")

        # Create calibration data
        try:
            self.create_calibration_data(role)
        except ValueError as e:
            print(f"ERROR: {e}")
            return 1

        print()
        print("-" * 60)
        print("Step 1: Task Selection")
        print("-" * 60)

        suggestions = self.get_task_suggestions()
        print("\nSuggested low-risk tasks:")
        for i, task in enumerate(suggestions, 1):
            print(f"  {i}) {task['summary']} [{task['task_type']}]")
        print(f"  0) Enter custom task")

        # Select task
        if sys.stdin.isatty():
            task_choice = input(f"\nSelect task [0-{len(suggestions)}]: ").strip()
            try:
                task_idx = int(task_choice)
                if 0 <= task_idx < len(suggestions):
                    selected_task = suggestions[task_idx]
                    task_type = selected_task["task_type"]
                    task_summary = selected_task["summary"]
                elif task_idx == 0:
                    task_type = input("Task type: ").strip()
                    task_summary = input("Task summary: ").strip()
                else:
                    print("Invalid choice.")
                    return 1
            except ValueError:
                print("Invalid input.")
                return 1
        else:
            # Non-interactive: use first suggestion
            selected_task = suggestions[0]
            task_type = selected_task["task_type"]
            task_summary = selected_task["summary"]
            print(f"Auto-selected task: {task_summary}")

        # Validate risk
        if not self.validate_risk(task_type, task_summary):
            print(f"\nERROR: Task does not qualify as low-risk.")
            print(f"  Type: {task_type}")
            print(f"  Summary: {task_summary}")
            print("\nPlease select a different task.")
            return 1

        print(f"\n✓ Task qualifies as low-risk.")
        print(f"  Type: {task_type}")
        print(f"  Summary: {task_summary}")

        # Create task
        task_id = f"pilot-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        self.current_task = PilotTask(
            task_id=task_id,
            task_type=task_type,
            task_summary=task_summary,
            started_at=datetime.utcnow(),
        )

        print()
        print("-" * 60)
        print("Step 2: Task Execution")
        print("-" * 60)
        print()
        print("Execute the task now in your target workspace.")
        print(f"Task: {task_summary}")
        print()

        # Record outcome
        if sys.stdin.isatty():
            print("-" * 60)
            print("Step 3: Record Outcome")
            print("-" * 60)
            print()
            print("Task outcomes:")
            print("  1) passed")
            print("  2) failed")
            print("  3) partial")
            print("  4) timeout")

            outcome_choice = input("Select outcome [1-4]: ").strip()
            outcome_map = {"1": "passed", "2": "failed", "3": "partial", "4": "timeout"}
            outcome = outcome_map.get(outcome_choice, "failed")

            duration = input("Duration (seconds): ").strip()
            try:
                duration_seconds = int(duration)
            except ValueError:
                duration_seconds = 0

            notes = input("Notes (optional): ").strip() or None
        else:
            # Non-interactive: assume passed
            outcome = "passed"
            duration_seconds = 0
            notes = None

        self.record_task_outcome(outcome, duration_seconds, notes)

        # Add to calibration data
        self.calibration_data.pilot_tasks.append(self.current_task)

        print()
        print("=" * 60)
        print("Pilot Complete")
        print("=" * 60)
        print()
        print(self.generate_calibration_output())

        return 0


def _is_minimal_mode() -> bool:
    """
    Check if the plugin is installed in minimal mode.

    Minimal mode: starter-kit directory does not exist or is empty.
    Starter mode: starter-kit directory exists with templates.

    Returns:
        bool: True if in minimal mode.
    """
    try:
        # Get the plugin root directory
        plugin_root = Path(__file__).resolve().parent.parent

        # Check for starter-kit
        starter_kit = plugin_root / "starter-kit"

        if not starter_kit.exists():
            # No starter-kit directory -> minimal mode
            return True

        # Check if templates directory exists and is non-empty
        templates_dir = starter_kit / "profile-templates"
        if not templates_dir.exists():
            return True

        # Check if templates directory has content
        if not any(templates_dir.iterdir()):
            return True

        # Starter-kit is present -> not minimal mode
        return False

    except Exception:
        # On any error, assume minimal mode for safety
        return True


def run_first_pilot_flow(interactive: bool = True) -> int:
    """
    Run the first-pilot flow.

    Args:
        interactive: If True, run interactive flow. If False, check minimal mode only.

    Returns:
        int: Exit code (0 for success, non-zero for errors).
    """
    # Check for minimal mode
    if _is_minimal_mode():
        print("ERROR: First-pilot flow is not available in minimal mode.")
        print("Reinstall with --starter flag:")
        print("  hermes plugin install agentic-fieldbook --starter")
        return 1

    if not interactive:
        # Non-interactive mode: just check minimal mode and report ready
        print("First-pilot flow is available.")
        print("Run: hermes aos first-pilot")
        return 0

    # Import wizard to get config
    try:
        from .config import read_config as _read_config
        config = _read_config()
    except Exception as e:
        print(f"ERROR: Failed to read config: {e}")
        return 1

    # Run interactive flow
    session = FirstPilotSession(config=config)
    return session.run_interactive_flow()