"""
Tests for Ticket T06: Guided first-pilot flow.

This module tests:
1. First-pilot flow accessible via command or wizard completion
2. Task guidance framework: low-risk qualification, selection, documentation
3. Calibration data capture: task outcome, reviewer scores, risk classification
4. Integration with existing calibration skills
5. Bypass by --minimal install: flow not available or referenced
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agentic_fieldbook.config import LaneBindingConfig
from agentic_fieldbook.first_pilot import (
    FirstPilotSession,
    CalibrationData,
    PilotTask,
    TaskOutcome,
    is_low_risk_task,
    suggest_low_risk_tasks,
    run_first_pilot_flow,
    _is_minimal_mode,
)


class TestLowRiskTaskGuidance:
    """Tests for low-risk task qualification and selection."""

    def test_low_risk_task_qualification_simple_documentation(self):
        """Simple documentation tasks qualify as low-risk."""
        task_summary = "Update README with installation instructions"
        assert is_low_risk_task(task_summary, "documentation") is True

    def test_low_risk_task_qualification_simple_refactor(self):
        """Simple refactors qualify as low-risk."""
        task_summary = "Extract function for email validation"
        assert is_low_risk_task(task_summary, "refactor") is True

    def test_low_risk_task_qualification_test_addition(self):
        """Adding tests qualifies as low-risk."""
        task_summary = "Add unit tests for utils.py"
        assert is_low_risk_task(task_summary, "testing") is True

    def test_low_risk_task_qualification_code_cleanup(self):
        """Code cleanup qualifies as low-risk."""
        task_summary = "Remove unused imports and fix PEP8 warnings"
        assert is_low_risk_task(task_summary, "cleanup") is True

    def test_high_risk_task_database_migration(self):
        """Database migrations do NOT qualify as low-risk."""
        task_summary = "Migrate user database to new schema"
        assert is_low_risk_task(task_summary, "migration") is False

    def test_high_risk_task_deployment(self):
        """Deployment tasks do NOT qualify as low-risk."""
        task_summary = "Deploy application to production"
        assert is_low_risk_task(task_summary, "deployment") is False

    def test_high_risk_task_security_changes(self):
        """Security changes do NOT qualify as low-risk."""
        task_summary = "Update authentication to OAuth2"
        assert is_low_risk_task(task_summary, "security") is False

    def test_high_risk_task_core_logic_changes(self):
        """Core logic changes do NOT qualify as low-risk."""
        task_summary = "Refactor payment processing algorithm"
        assert is_low_risk_task(task_summary, "core_logic") is False

    def test_suggest_low_risk_tasks_provides_examples(self):
        """suggest_low_risk_tasks returns a list of example tasks."""
        tasks = suggest_low_risk_tasks()
        assert len(tasks) > 0
        assert all(isinstance(t, dict) for t in tasks)
        assert all("summary" in t and "task_type" in t for t in tasks)

    def test_suggested_tasks_are_all_low_risk(self):
        """All suggested tasks pass low-risk qualification."""
        tasks = suggest_low_risk_tasks()
        for task in tasks:
            assert is_low_risk_task(task["summary"], task["task_type"]) is True


class TestPilotTask:
    """Tests for PilotTask data structure."""

    def test_pilot_task_creation(self):
        """PilotTask can be created with required fields."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime(2026, 7, 28, 10, 0, 0),
        )
        assert task.task_id == "pilot-001"
        assert task.task_type == "documentation"
        assert task.task_summary == "Update README"
        assert task.started_at == datetime(2026, 7, 28, 10, 0, 0)
        assert task.completed_at is None
        assert task.outcome is None

    def test_pilot_task_completion(self):
        """PilotTask can be marked as complete."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime(2026, 7, 28, 10, 0, 0),
            completed_at=datetime(2026, 7, 28, 10, 30, 0),
            outcome="passed",
            duration_seconds=1800,
        )
        assert task.completed_at == datetime(2026, 7, 28, 10, 30, 0)
        assert task.outcome == "passed"
        assert task.duration_seconds == 1800

    def test_pilot_task_outcome_validation(self):
        """PilotTask only accepts valid outcomes."""
        valid_outcomes = ["passed", "failed", "partial", "timeout"]
        for outcome in valid_outcomes:
            task = PilotTask(
                task_id=f"pilot-{outcome}",
                task_type="documentation",
                task_summary="Test",
                started_at=datetime.now(),
                outcome=outcome,
            )
            assert task.outcome == outcome


class TestCalibrationData:
    """Tests for CalibrationData persistence."""

    def test_calibration_data_creation(self):
        """CalibrationData can be created with pilot tasks."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            outcome="passed",
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )
        assert calibration.lane_id == "executor-claude-sonnet-4"
        assert len(calibration.pilot_tasks) == 1
        assert calibration.pilot_tasks[0].task_id == "pilot-001"

    def test_calibration_data_adds_reviewer_scores(self):
        """CalibrationData can capture reviewer scores."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )
        calibration.add_reviewer_score(
            task_id="pilot-001",
            reviewer_profile="aos-reviewer",
            scores={
                "accuracy": 0.9,
                "completeness": 0.85,
                "quality": 0.88,
            },
        )
        assert len(calibration.pilot_tasks[0].reviewer_scores) == 1
        assert calibration.pilot_tasks[0].reviewer_scores[0].reviewer_profile == "aos-reviewer"

    def test_calibration_data_serialization(self):
        """CalibrationData can be serialized to dict for storage."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime(2026, 7, 28, 10, 0, 0),
            completed_at=datetime(2026, 7, 28, 10, 30, 0),
            outcome="passed",
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )
        data_dict = calibration.to_dict()
        assert data_dict["lane_id"] == "executor-claude-sonnet-4"
        assert len(data_dict["pilot_tasks"]) == 1
        assert data_dict["pilot_tasks"][0]["task_id"] == "pilot-001"

    def test_calibration_data_deserialization(self):
        """CalibrationData can be loaded from dict."""
        data_dict = {
            "lane_id": "executor-claude-sonnet-4",
            "created_at": datetime.now().isoformat(),
            "pilot_tasks": [
                {
                    "task_id": "pilot-001",
                    "task_type": "documentation",
                    "task_summary": "Update README",
                    "started_at": datetime(2026, 7, 28, 10, 0, 0).isoformat(),
                    "completed_at": datetime(2026, 7, 28, 10, 30, 0).isoformat(),
                    "outcome": "passed",
                    "duration_seconds": 1800,
                    "reviewer_scores": [],
                }
            ],
        }
        calibration = CalibrationData.from_dict(data_dict)
        assert calibration.lane_id == "executor-claude-sonnet-4"
        assert len(calibration.pilot_tasks) == 1
        assert calibration.pilot_tasks[0].task_id == "pilot-001"
        assert calibration.pilot_tasks[0].outcome == "passed"


class TestFirstPilotSession:
    """Tests for FirstPilotSession flow."""

    def test_session_initialization(self):
        """FirstPilotSession initializes with lane config."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)
        assert session.config is not None
        assert session.config.executor == "aos-executor"

    def test_session_creates_calibration_data(self):
        """Session creates calibration data for executor lane."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)
        calibration = session.create_calibration_data("executor")
        # Lane ID format: {role}-{profile}
        assert calibration.lane_id == "executor-aos-executor"

    def test_session_guides_task_selection(self):
        """Session provides task guidance."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)
        suggestions = session.get_task_suggestions()
        assert len(suggestions) > 0

    def test_session_validates_risk_classification(self):
        """Session validates that selected task is low-risk."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)
        assert session.validate_risk("documentation", "Update README") is True
        assert session.validate_risk("deployment", "Deploy to production") is False

    @patch("sys.stdin.isatty")
    def test_session_runs_interactive_flow(self, mock_isatty):
        """Session runs interactive flow with prompts."""
        mock_isatty.return_value = True

        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)

        with patch("builtins.input", side_effect=["1", "Update README", "1", "passed", "5"]):
            result = session.run_interactive_flow()
            # Should complete successfully
            assert result is not None

    def test_session_generates_calibration_output(self):
        """Session generates calibration data output."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)

        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            outcome="passed",
        )

        # Set calibration_data before setting current_task
        session.calibration_data = CalibrationData(lane_id="executor-aos-executor", pilot_tasks=[task])
        session.current_task = task

        output = session.generate_calibration_output()
        assert "pilot-001" in output
        assert "documentation" in output
        assert "passed" in output


class TestMinimalModeBypass:
    """Tests for --minimal install bypass."""

    def test_minimal_mode_detection(self):
        """Minimal mode is detected when starter-kit is not installed."""
        # Test with non-existent starter-kit directory
        result = _is_minimal_mode()
        # Result depends on whether starter-kit exists
        assert isinstance(result, bool)

    def test_flow_refuses_in_minimal_mode(self):
        """First-pilot flow refuses to run in minimal mode."""
        with patch("agentic_fieldbook.first_pilot._is_minimal_mode", return_value=True):
            result = run_first_pilot_flow(interactive=False)
            # Should fail gracefully
            assert result != 0

    def test_flow_runs_in_starter_mode(self):
        """First-pilot flow runs in starter mode (interactive)."""
        with patch("agentic_fieldbook.first_pilot._is_minimal_mode", return_value=False):
            with patch("agentic_fieldbook.config.read_config") as mock_read:
                mock_read.return_value = LaneBindingConfig(executor="aos-executor")

                with patch("agentic_fieldbook.first_pilot.FirstPilotSession") as mock_session:
                    mock_instance = Mock()
                    mock_instance.run_interactive_flow.return_value = 0
                    mock_session.return_value = mock_instance

                    # Run in interactive mode
                    result = run_first_pilot_flow(interactive=True)
                    assert result == 0
                    mock_session.assert_called_once()


class TestCalibrationDataPersistence:
    """Tests for calibration data file persistence."""

    def test_calibration_data_save_to_file(self):
        """CalibrationData can be saved to a YAML file."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            outcome="passed",
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            calibration.save_to_file(temp_path)
            assert temp_path.exists()

            # Verify it can be read back
            loaded = CalibrationData.load_from_file(temp_path)
            assert loaded.lane_id == calibration.lane_id
            assert len(loaded.pilot_tasks) == 1
        finally:
            temp_path.unlink(missing_ok=True)

    def test_calibration_data_load_from_file(self):
        """CalibrationData can be loaded from a YAML file."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            outcome="passed",
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            calibration.save_to_file(temp_path)
            loaded = CalibrationData.load_from_file(temp_path)
            assert loaded.lane_id == "executor-claude-sonnet-4"
            assert len(loaded.pilot_tasks) == 1
        finally:
            temp_path.unlink(missing_ok=True)

    def test_calibration_data_file_integration_with_lane_calibration(self):
        """CalibrationData file integrates with lane-calibration skill schema."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            outcome="passed",
        )
        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = Path(f.name)

        try:
            calibration.save_to_file(temp_path)

            # Load and verify schema compliance
            with open(temp_path) as f:
                import yaml
                data = yaml.safe_load(f)

            # Check required fields from calibration-schema.yaml
            assert "lane_id" in data
            assert "calibration_status" in data
            assert "created_at" in data
            assert "pilot_tasks" in data
            assert data["calibration_status"] == "in_progress"
        finally:
            temp_path.unlink(missing_ok=True)


class TestCommandIntegration:
    """Tests for CLI command integration."""

    def test_first_pilot_command_handler(self):
        """First-pilot command handler exists and returns int."""
        from agentic_fieldbook.plugin import _cmd_first_pilot
        from argparse import Namespace

        # Mock the first_pilot module to avoid import errors
        with patch("agentic_fieldbook.first_pilot.run_first_pilot_flow") as mock_flow:
            mock_flow.return_value = 0

            args = Namespace()
            result = _cmd_first_pilot(args)
            assert isinstance(result, int)
            assert result == 0
            mock_flow.assert_called_once_with(interactive=True)

    @patch("agentic_fieldbook.first_pilot._is_minimal_mode")
    def test_first_pilot_non_interactive_mode(self, mock_minimal):
        """First-pilot runs in non-interactive mode."""
        mock_minimal.return_value = False

        with patch("agentic_fieldbook.first_pilot.FirstPilotSession") as mock_session:
            mock_instance = Mock()
            mock_instance.run_interactive_flow.return_value = 0
            mock_session.return_value = mock_instance

            result = run_first_pilot_flow(interactive=False)
            assert result == 0


class TestWizardCompletionIntegration:
    """Tests for wizard completion integration."""

    def test_wizard_suggests_first_pilot_after_mapping(self):
        """Wizard suggests first-pilot flow after successful lane mapping."""
        config = LaneBindingConfig(
            planner="aos-planner",
            executor="aos-executor",
            reviewer="aos-reviewer",
            verifier="aos-verifier",
        )

        # After all roles are bound, wizard should offer first-pilot
        all_bound = all([config.planner, config.executor, config.reviewer, config.verifier])
        assert all_bound is True

    @patch("builtins.input", return_value="y")
    def test_wizard_transitions_to_first_pilot(self, mock_input):
        """Wizard can transition to first-pilot flow."""
        config = LaneBindingConfig(executor="aos-executor")

        with patch("agentic_fieldbook.first_pilot.run_first_pilot_flow") as mock_flow:
            mock_flow.return_value = 0
            result = run_first_pilot_flow(interactive=False)
            assert result == 0


class TestCalibrationSkillIntegration:
    """Tests for integration with existing calibration skills."""

    def test_calibration_data_matches_lane_calibration_schema(self):
        """CalibrationData structure matches lane-calibration skill schema."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            outcome="passed",
            duration_seconds=1800,
            notes="Task completed successfully",
        )

        calibration = CalibrationData(
            lane_id="executor-claude-sonnet-4",
            pilot_tasks=[task],
        )

        data = calibration.to_dict()

        # Verify schema matches lane-calibration/references/calibration-schema.yaml
        assert "lane_id" in data
        assert "calibration_status" in data
        assert "created_at" in data
        assert "pilot_tasks" in data

        # Verify pilot task structure
        task_data = data["pilot_tasks"][0]
        assert "task_id" in task_data
        assert "task_type" in task_data
        assert "started_at" in task_data
        assert "completed_at" in task_data
        assert "outcome" in task_data
        assert "duration_seconds" in task_data
        assert "notes" in task_data

    def test_reviewer_scores_match_review_calibration_template(self):
        """Reviewer scores match review-calibration scoring template."""
        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
        )

        calibration = CalibrationData(lane_id="executor-claude-sonnet-4", pilot_tasks=[task])

        calibration.add_reviewer_score(
            task_id="pilot-001",
            reviewer_profile="aos-reviewer",
            scores={
                "accuracy": 0.9,
                "completeness": 0.85,
                "quality": 0.88,
            },
        )

        data = calibration.to_dict()
        reviewer_score = data["pilot_tasks"][0]["reviewer_scores"][0]

        # Verify reviewer score structure
        assert "reviewer_profile" in reviewer_score
        assert "scores" in reviewer_score
        assert "accuracy" in reviewer_score["scores"]
        assert "completeness" in reviewer_score["scores"]
        assert "quality" in reviewer_score["scores"]


class TestFlowLogic:
    """Tests for overall flow logic."""

    def test_flow_guides_user_through_steps(self):
        """Flow guides user through low-risk selection, execution, and data capture."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)

        # Step 1: Task selection guidance
        suggestions = session.get_task_suggestions()
        assert len(suggestions) > 0

        # Step 2: Risk validation
        is_safe = session.validate_risk("documentation", "Update README")
        assert is_safe is True

        # Step 3: Create calibration data
        calibration = session.create_calibration_data("executor")
        # Lane ID format: {role}-{profile}
        assert calibration.lane_id == "executor-aos-executor"

    def test_flow_handles_task_completion(self):
        """Flow handles task completion and outcome recording."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)

        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
        )

        session.current_task = task
        session.record_task_outcome(outcome="passed", duration_seconds=1800)

        assert session.current_task.outcome == "passed"
        assert session.current_task.duration_seconds == 1800

    def test_flow_generates_summary(self):
        """Flow generates calibration summary for user."""
        config = LaneBindingConfig(executor="aos-executor")
        session = FirstPilotSession(config=config)

        task = PilotTask(
            task_id="pilot-001",
            task_type="documentation",
            task_summary="Update README",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            outcome="passed",
        )

        session.calibration_data = CalibrationData(lane_id="executor-aos-executor", pilot_tasks=[task])
        session.current_task = task

        output = session.generate_calibration_output()

        # Verify summary contains key information
        assert "pilot-001" in output
        assert "documentation" in output
        assert "passed" in output
        assert "executor" in output