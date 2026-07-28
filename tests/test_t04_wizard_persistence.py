"""T04 wizard persistence and ownership tests."""

import os
from pathlib import Path

import pytest
import yaml

from agentic_fieldbook.config import (
    LaneBindingConfig,
    WizardOwnershipError,
    regenerate_config,
)


def test_save_is_atomic_temp_then_rename(tmp_path, monkeypatch):
    target = tmp_path / "aos-lanes.yaml"
    target.write_text("", encoding="utf-8")  # Start empty (wizard-owned)
    renames = []
    real_replace = os.replace

    def record_replace(source, destination):
        renames.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr("agentic_fieldbook.config.os.replace", record_replace)
    regenerate_config(LaneBindingConfig(planner="planner-v2"), target)

    assert target.read_text(encoding="utf-8").startswith("# AOS Lane Bindings")
    assert renames and renames[0][1] == target
    assert not renames[0][0].exists()


def test_hand_edited_owned_file_warns_and_refuses_overwrite(tmp_path):
    target = tmp_path / "aos-lanes.yaml"
    regenerate_config(LaneBindingConfig(planner="original"), target)
    # Simulate hand-edit by removing wizard marker and changing content
    content = target.read_text(encoding="utf-8")
    hand_edited = "\n".join(line for line in content.split("\n") if not line.strip().startswith("# aos-wizard-state-sha256:"))
    hand_edited = hand_edited.replace("planner: original", "planner: hand-edited")
    target.write_text(hand_edited, encoding="utf-8")

    with pytest.raises(WizardOwnershipError, match="hand-edited"):
        regenerate_config(LaneBindingConfig(planner="replacement"), target)
    assert "hand-edited" in target.read_text(encoding="utf-8")


def test_save_regenerates_entire_file_from_state(tmp_path):
    target = tmp_path / "aos-lanes.yaml"
    regenerate_config(LaneBindingConfig(planner="old", executor="stale"), target)
    regenerate_config(LaneBindingConfig(planner="new"), target)

    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == {"planner": "new", "executor": None, "reviewer": None, "verifier": None}
    assert "stale" not in target.read_text(encoding="utf-8")


def test_generated_yaml_is_readable_and_commented(tmp_path):
    target = tmp_path / "aos-lanes.yaml"
    regenerate_config(LaneBindingConfig(planner="planner"), target)
    content = target.read_text(encoding="utf-8")

    assert "# AOS Lane Bindings" in content
    assert "# Role bindings:" in content
    assert "# aos-wizard-state-sha256:" in content
    assert content.index("planner:") < content.index("executor:")
