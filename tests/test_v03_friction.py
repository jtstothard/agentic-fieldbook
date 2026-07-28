import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agentic_fieldbook.first_pilot import CalibrationData, FirstPilotSession, PilotTask
from agentic_fieldbook.config import LaneBindingConfig
from agentic_fieldbook.wizard import discover_profiles


def test_discover_profiles_from_profile_scoped_hermes_home(tmp_path):
    root = tmp_path / "profiles"
    (root / "coder").mkdir(parents=True)
    (root / "ops").mkdir()
    with patch.dict(os.environ, {"HERMES_HOME": str(root / "coder")}):
        assert discover_profiles() == ["coder", "ops"]


def test_discover_profiles_rejects_missing_home(tmp_path):
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / "missing")}):
        with pytest.raises(RuntimeError, match="does not exist"):
            discover_profiles()


def test_calibration_save_default_path_creates_home(tmp_path):
    task = PilotTask("pilot-1", "testing", "Run tests", __import__("datetime").datetime.now(), outcome="passed")
    data = CalibrationData("executor-coder", pilot_tasks=[task])
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / "hermes")}):
        saved = data.save_to_default_file()
    assert saved == tmp_path / "hermes" / "calibration" / "lane-calibration.yaml"
    assert saved.exists()


def test_noninteractive_flow_requires_explicit_inputs(capsys):
    session = FirstPilotSession(LaneBindingConfig(executor="coder"))
    assert session.run_interactive_flow() == 1
    assert "non-interactive" in capsys.readouterr().out.lower()


def test_explicit_noninteractive_flow_records_all_fields(tmp_path):
    session = FirstPilotSession(LaneBindingConfig(executor="coder"))
    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / "hermes")}):
        assert session.run_noninteractive_flow(
            role="executor", task_type="testing", task_summary="Run tests",
            outcome="passed", duration_seconds=12, notes="green"
        ) == 0
    task = session.calibration_data.pilot_tasks[0]
    assert (task.task_type, task.task_summary, task.outcome, task.duration_seconds, task.notes) == (
        "testing", "Run tests", "passed", 12, "green"
    )


def test_noninteractive_missing_arguments_is_rejected(capsys):
    with patch.dict(os.environ, {"HERMES_HOME": "/tmp/hermes-friction-test"}), patch(
        "agentic_fieldbook.first_pilot._is_minimal_mode", return_value=False
    ):
        from agentic_fieldbook.first_pilot import run_first_pilot_flow
        assert run_first_pilot_flow(interactive=False, noninteractive_requested=True) == 2
    assert "requires" in capsys.readouterr().out
