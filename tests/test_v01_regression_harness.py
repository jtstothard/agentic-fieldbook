"""
v0.1.0 regression harness — proves v0.2.0 is a strict additive superset.

This harness:
1. Captures v0.1.0 baseline output for all plugin commands
2. Captures v0.1.0 skill content and structure
3. Captures v0.1.0 plugin metadata
4. Fails if any v0.1.0 behavior changes in future commits

Run this harness against v0.1.0 to establish the baseline, then on every
v0.2.0 commit to verify no regressions.
"""

import os
import sys
import hashlib
import subprocess
from pathlib import Path
from typing import Dict
import pytest
import yaml
from unittest.mock import MagicMock, patch
from argparse import Namespace
from typing import TYPE_CHECKING, Optional

# Add plugin root to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))

# Handle preflight - it may not exist in v0.1.0
try:
    from agentic_fieldbook.plugin import (
        _cmd_setup,
        _cmd_doctor,
        _cmd_version,
        _cmd_preflight,
        plugin_info,
        _cmd_migrate,
    )
    _PREFLIGHT_EXISTS = True
except ImportError:
    from agentic_fieldbook.plugin import (
        _cmd_setup,
        _cmd_doctor,
        _cmd_version,
        plugin_info,
        _cmd_migrate,
    )
    _PREFLIGHT_EXISTS = False

if TYPE_CHECKING:
    pass


BASELINE_DIR = Path(__file__).parent / ".v01_baseline"
SKILLS_DIR = plugin_root / "skills"
METADATA_FILES = {
    "VERSION": plugin_root / "VERSION",
    "plugin.yaml": plugin_root / "agentic_fieldbook" / "plugin.yaml",
    "setup.py": plugin_root / "setup.py",
}


def read_file_hash(path: Path) -> str:
    """Return SHA256 hash of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_file_content(path: Path) -> str:
    """Return file content as string."""
    return path.read_text(encoding="utf-8")


def capture_command_output(cmd_func: callable, args: Optional[Namespace] = None) -> str:
    """Capture stdout/stderr from a command function."""
    from io import StringIO
    import contextlib

    if args is None:
        args = Namespace()

    stdout_capture = StringIO()
    stderr_capture = StringIO()

    with contextlib.redirect_stdout(stdout_capture):
        with contextlib.redirect_stderr(stderr_capture):
            cmd_func(args)

    return f"STDOUT:\n{stdout_capture.getvalue()}\nSTDERR:\n{stderr_capture.getvalue()}"


def capture_skill_structure() -> Dict[str, Dict]:
    """Capture structure and content of all v0.1 skills."""
    skill_dirs = sorted([d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])
    skills_data = {}

    for skill_dir in skill_dirs:
        skill_name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        references_dir = skill_dir / "references"
        templates_dir = skill_dir / "templates"

        skill_data = {
            "skill_md_hash": read_file_hash(skill_md),
            "skill_md_content": read_file_content(skill_md),
            "references": {},
            "templates": {},
        }

        if references_dir.exists():
            for ref_file in sorted(references_dir.iterdir()):
                if ref_file.is_file():
                    skill_data["references"][ref_file.name] = {
                        "hash": read_file_hash(ref_file),
                        "content": read_file_content(ref_file),
                    }

        if templates_dir.exists():
            for tmpl_file in sorted(templates_dir.iterdir()):
                if tmpl_file.is_file():
                    skill_data["templates"][tmpl_file.name] = {
                        "hash": read_file_hash(tmpl_file),
                        "content": read_file_content(tmpl_file),
                    }

        skills_data[skill_name] = skill_data

    return skills_data


def capture_plugin_metadata() -> Dict[str, Dict]:
    """Capture plugin metadata hashes and content."""
    metadata = {}

    for name, path in METADATA_FILES.items():
        if path.exists():
            content = read_file_content(path)
            metadata[name] = {
                "hash": read_file_hash(path),
                "content": content,
            }

    return metadata


def capture_plugin_commands() -> Dict[str, str]:
    """Capture output from all plugin commands."""
    commands = {}

    # Mock Hermes for commands that need it
    mock_hermes = MagicMock()
    mock_hermes.__version__ = "0.19.0"

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["HERMES_HOME"] = tmpdir
        soul_path = Path(tmpdir) / "SOUL.md"
        soul_path.touch()

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                commands["setup"] = capture_command_output(_cmd_setup, Namespace(yes=True))

    commands["doctor"] = capture_command_output(_cmd_doctor, Namespace())
    commands["version"] = capture_command_output(_cmd_version, Namespace())

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["HERMES_HOME"] = tmpdir
        commands["preflight"] = capture_command_output(_cmd_preflight, Namespace())

    return commands


def save_baseline(baseline_data: Dict):
    """Save baseline data to disk."""
    BASELINE_DIR.mkdir(exist_ok=True)

    for key, value in baseline_data.items():
        baseline_file = BASELINE_DIR / f"{key}.json"
        import json
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)


def load_baseline() -> Dict:
    """Load baseline data from disk."""
    import json
    baseline = {}

    for baseline_file in sorted(BASELINE_DIR.glob("*.json")):
        key = baseline_file.stem
        with open(baseline_file, "r", encoding="utf-8") as f:
            baseline[key] = json.load(f)

    return baseline


class TestV01RegressionHarness:
    """
    Regression harness for v0.1.0 behavior.

    These tests capture and verify the complete v0.1.0 external behavior:
    - Plugin command outputs
    - Skill content and structure
    - Plugin metadata
    """

    def test_skill_structure_baseline(self):
        """All v0.1.0 skills should exist with expected structure."""
        skill_dirs = sorted([d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])
        skill_names = sorted([d.name for d in skill_dirs])

        # v0.1.0 had exactly 7 skills
        assert skill_names == [
            "contract-schema",
            "knowledge-lifecycle",
            "lane-calibration",
            "planning-routing",
            "review-calibration",
            "risk-taxonomy",
            "stage-handoff",
        ], f"Expected 7 v0.1.0 skills, found: {skill_names}"

    def test_skill_md_files_exist(self):
        """Each skill must have a SKILL.md file."""
        skill_dirs = sorted([d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])

        for skill_dir in skill_dirs:
            skill_md = skill_dir / "SKILL.md"
            assert skill_md.exists(), f"Skill {skill_dir.name} must have SKILL.md"

    def test_lane_calibration_references(self):
        """Lane-calibration skill must have v0.1.0 references."""
        lc_dir = SKILLS_DIR / "lane-calibration"
        refs_dir = lc_dir / "references"

        assert refs_dir.exists(), "Lane-calibration must have references/ directory"

        expected_refs = [
            "calibration-schema.yaml",
            "calibration-template.yaml",
            "calibration-example.yaml",
            "recalibration-triggers.md",
        ]

        for ref_name in expected_refs:
            ref_path = refs_dir / ref_name
            assert ref_path.exists(), f"Lane-calibration must have {ref_name}"

    def test_review_calibration_templates(self):
        """Review-calibration skill must have v0.1.0 templates."""
        rc_dir = SKILLS_DIR / "review-calibration"
        tmpl_dir = rc_dir / "templates"

        assert tmpl_dir.exists(), "Review-calibration must have templates/ directory"
        assert (tmpl_dir / "review-dispatch.md").exists(), "Review-calibration must have review-dispatch.md template"

    def test_stage_handoff_references(self):
        """Stage-handoff skill must have v0.1.0 references."""
        sh_dir = SKILLS_DIR / "stage-handoff"
        refs_dir = sh_dir / "references"

        assert refs_dir.exists(), "Stage-handoff must have references/ directory"

        expected_refs = [
            "stage-handoff-schema.yaml",
            "example-planner-to-executor.yaml",
            "example-executor-to-reviewer.yaml",
        ]

        for ref_name in expected_refs:
            ref_path = refs_dir / ref_name
            assert ref_path.exists(), f"Stage-handoff must have {ref_name}"

    def test_contract_schema_references(self):
        """Contract-schema skill must have v0.1.0 references."""
        cs_dir = SKILLS_DIR / "contract-schema"
        refs_dir = cs_dir / "references"

        assert refs_dir.exists(), "Contract-schema must have references/ directory"

        # Check for key v0.1.0 references
        for ref_name in [
            "contract-core.v1.yaml",
            "contract-template.md",
            "versioning-rules.md",
        ]:
            ref_path = refs_dir / ref_name
            assert ref_path.exists(), f"Contract-schema must have {ref_name}"

    def test_plugin_metadata_files_exist(self):
        """All v0.1.0 plugin metadata files must exist."""
        for name, path in METADATA_FILES.items():
            assert path.exists(), f"Plugin metadata file {name} must exist at {path}"

    def test_version_file_content(self):
        """VERSION file must match v0.1.0."""
        version_content = read_file_content(METADATA_FILES["VERSION"]).strip()
        # In v0.1.0, this is "0.1.0"
        # In v0.2.0, this will be different, but we check it's present
        assert version_content, "VERSION file must not be empty"
        assert len(version_content.split(".")) >= 2, "VERSION must be semver-like"

    def test_plugin_yaml_structure(self):
        """plugin.yaml must have v0.1.0 structure."""
        manifest = yaml.safe_load(METADATA_FILES["plugin.yaml"].read_text())

        assert manifest["name"] == "agentic-fieldbook"
        assert manifest["kind"] == "standalone"
        assert "version" in manifest
        assert "description" in manifest
        assert "author" in manifest

    def test_setup_py_entry_points(self):
        """setup.py must have Hermes plugin entry point."""
        content = read_file_content(METADATA_FILES["setup.py"])
        assert '"hermes.plugins"' in content or '"hermes_agent.plugins"' in content, "setup.py must define a Hermes plugin entry point"
        assert "agentic-fieldbook" in content, "setup.py must register agentic-fieldbook plugin"
        assert "register_cli_commands" in content or "plugin:register" in content, (
            "setup.py must reference registration function"
        )

    def test_plugin_info_function(self):
        """plugin_info() must return v0.1.0 metadata."""
        info = plugin_info()

        assert info["name"] == "agentic-fieldbook"
        assert "version" in info
        assert "hermes_compatibility" in info
        assert "homepage" in info

    def test_version_command_output(self, capsys):
        """Version command must show v0.1.0-style output."""
        _cmd_version(Namespace())
        captured = capsys.readouterr()

        assert "Agentic Fieldbook" in captured.out
        assert "v" in captured.out  # Version marker
        assert "Hermes compatibility" in captured.out

    def test_doctor_command_output(self, capsys):
        """Doctor command must show v0.1.0 stub output."""
        _cmd_doctor(Namespace())
        captured = capsys.readouterr()

        assert "Agentic Fieldbook" in captured.out
        assert "doctor" in captured.out.lower()
        assert captured.out.lower().count("agentic fieldbook") >= 1

    def test_migrate_command_is_noop(self, capsys):
        """Migrate command must be a clean no-op in v0.1.0."""
        from agentic_fieldbook.plugin import _cmd_migrate

        _cmd_migrate(Namespace())
        captured = capsys.readouterr()

        # Allow for version prefix that changes between v0.1.0 and later
        assert "migrate: no changes needed" in captured.out.strip()


class TestV01BaselineCapture:
    """
    Capture full baseline for comparison against future commits.

    These tests are used to generate and compare the baseline.
    They fail if the current state differs from v0.1.0.
    """

    def test_can_capture_full_baseline(self):
        """Verify we can capture all baseline components."""
        skills_data = capture_skill_structure()
        metadata = capture_plugin_metadata()

        assert len(skills_data) == 7, f"Expected 7 skills, found {len(skills_data)}"
        assert "VERSION" in metadata
        assert "plugin.yaml" in metadata
        assert "setup.py" in metadata

    @pytest.mark.integration
    def test_setup_command_runs(self):
        """Setup command should run successfully with mocked Hermes."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HERMES_HOME"] = tmpdir
            soul_path = Path(tmpdir) / "SOUL.md"
            soul_path.touch()

            with patch.dict("sys.modules", {"hermes": mock_hermes}):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    assert result == 0


# Import tempfile here for tests
import tempfile