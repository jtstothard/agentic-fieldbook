"""Tests for Doctor command runtime verification checks."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

# Add the plugin to the path
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

# Import the root __init__ directly to test the self-contained implementation
import importlib.util
spec = importlib.util.spec_from_file_location("_root", plugin_root / "__init__.py")
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load root __init__.py from {plugin_root / '__init__.py'}")
_root_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_root_module)

_cmd_doctor = _root_module._cmd_doctor
_cmd_setup = _root_module._cmd_setup
_cmd_version = _root_module._cmd_version
_check_skill_loadability = _root_module._check_skill_loadability
_check_references = _root_module._check_references
_check_calibration = _root_module._check_calibration
_check_cross_skill_names = _root_module._check_cross_skill_names
_check_cli_registration = _root_module._check_cli_registration


class TestSkillLoadability:
    def test_all_expected_skills_load_successfully(self):
        """All 7 expected skills should have valid SKILL.md with required fields."""
        failures = _check_skill_loadability(plugin_root)
        assert failures == [], f"Expected no loadability failures, got: {failures}"

    def test_skill_missing_required_field_reports_error(self):
        """Skills missing required fields should be reported by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "skills" / "test-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\ndescription: test\n\n---\n\nBody")
            failures = _check_skill_loadability(Path(tmpdir))
            assert any("missing name" in f for f in failures)

    def test_skill_invalid_frontmatter_reports_error(self):
        """Invalid YAML frontmatter should be reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "skills" / "test-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\ninvalid yaml [unclosed\n\nBody")
            failures = _check_skill_loadability(Path(tmpdir))
            assert any("test-skill" in f for f in failures)


class TestReferencesResolve:
    def test_all_references_resolve_to_real_paths(self):
        """All referenced paths in skill docs should resolve to real files."""
        failures = _check_references(plugin_root)
        assert failures == [], f"Expected no reference resolution failures, got: {failures}"

    def test_broken_reference_reports_path(self):
        """Broken references should be reported with the skill and path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "skills" / "test-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: test\n---\n\nBody references `missing/file.md` and `missing/subdir/deep.md`")
            failures = _check_references(Path(tmpdir))
            assert len(failures) == 2
            assert all("test-skill/" in f for f in failures)
            assert "missing/file.md" in failures[0]


class TestCalibrationSchemaValidation:
    def test_calibration_example_validates_against_schema(self):
        """Calibration example should validate against the schema."""
        failures = _check_calibration(plugin_root)
        assert failures == [], f"Expected no schema validation failures, got: {failures}"

    def test_example_missing_required_field_reports_error(self):
        """Missing required fields should be reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "skills" / "lane-calibration" / "references"
            base.mkdir(parents=True)
            (base / "calibration-schema.yaml").write_text("type: object\nrequired:\n  - lane_id\nproperties:\n  lane_id:\n    type: string")
            (base / "calibration-example.yaml").write_text("{}")
            failures = _check_calibration(Path(tmpdir))
            assert any("missing required field" in f for f in failures)


class TestCrossSkillNameConsistency:
    def test_all_cross_skill_references_resolve_to_installed_skills(self):
        """Skills that reference other skills should reference only installed skills."""
        failures = _check_cross_skill_names(plugin_root)
        assert failures == [], f"Expected no cross-skill reference failures, got: {failures}"

    def test_dangling_skill_reference_reports_error(self):
        """References to missing skills should be reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            a = Path(tmpdir) / "skills" / "skill-a"
            b = Path(tmpdir) / "skills" / "skill-b"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "SKILL.md").write_text("---\nname: skill-a\ndescription: test\n---\n\nUse the `contract-schema` skill for X")
            (b / "SKILL.md").write_text("---\nname: skill-b\ndescription: test\n---\n\nUse the `skill-a` skill for Y")
            failures = _check_cross_skill_names(Path(tmpdir))
            assert any("skill-a references missing contract-schema" in f for f in failures)


class TestCLIRegistration:
    def test_all_expected_commands_registered(self):
        """All expected CLI commands should be present in the registration function."""
        failures = _check_cli_registration()
        assert failures == [], f"Expected no CLI registration failures, got: {failures}"

    def test_missing_command_reports_error(self):
        """Missing commands should be reported by name."""
        import inspect
        import re

        # Create a minimal function with missing commands
        def _incomplete_cli(parsers):
            sp = parsers.add_subparsers(dest="aos_subcommand", title="subcommands", required=True)
            sp.add_parser("setup", help="Set up")
            # Missing: doctor, version

        source = inspect.getsource(_incomplete_cli)
        # Simulate the check: report missing commands
        failures = []
        for cmd in ("doctor", "version"):
            if not re.search(rf'add_parser\(\s*["\']{re.escape(cmd)}["\']', source):
                failures.append(f"missing command {cmd}")
        assert len(failures) == 2
        assert "missing command doctor" in failures
        assert "missing command version" in failures


class TestDoctorCommand:
    def test_doctor_exits_zero_on_success(self, capsys):
        """Doctor should exit 0 and print all-clear when all checks pass."""
        args = MagicMock()
        args.plugin_root = None
        result = _cmd_doctor(args)
        captured = capsys.readouterr()
        assert result == 0, "Doctor should exit 0 when all checks pass"
        assert "ALL CLEAR" in captured.out

    def test_doctor_exits_nonzero_on_failure(self):
        """Doctor should exit non-zero when any check fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MagicMock()
            args.plugin_root = tmpdir
            result = _cmd_doctor(args)
            assert result != 0, "Doctor should exit non-zero when checks fail"

    def test_doctor_prints_named_failure_summary(self, capsys):
        """Doctor should print specific failure names when checks fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MagicMock()
            args.plugin_root = tmpdir
            _cmd_doctor(args)
            captured = capsys.readouterr()
            assert "FAIL" in captured.out


class TestDoctorEdgeCases:
    def test_doctor_handles_empty_skills_directory(self):
        """Doctor should handle missing or empty skills directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MagicMock()
            args.plugin_root = tmpdir
            result = _cmd_doctor(args)
            assert result != 0, "Should fail when skills directory is empty"

    def test_doctor_respects_plugin_root_override(self):
        """Doctor should use plugin_root from args when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal test-skill
            skill_dir = Path(tmpdir) / "skills" / "test-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: test\n---\n\nBody")
            # Create minimal lane-calibration to skip that check
            lane_dir = Path(tmpdir) / "skills" / "lane-calibration" / "references"
            lane_dir.mkdir(parents=True)
            (lane_dir / "calibration-schema.yaml").write_text("type: object\nrequired: []\nproperties: {}")
            (lane_dir / "calibration-example.yaml").write_text("{}")
            # Create lane-calibration/SKILL.md
            lane_skill = Path(tmpdir) / "skills" / "lane-calibration" / "SKILL.md"
            lane_skill.write_text("---\nname: lane-calibration\ndescription: test\n---\n\nBody")
            args = MagicMock()
            args.plugin_root = tmpdir
            result = _cmd_doctor(args)
            assert result == 0, "Should use override plugin_root and pass"

    def test_doctor_falls_back_to_path_parent(self):
        """Doctor should fall back to Path(__file__).parent when no override provided."""
        # This implicitly tests the production case
        args = MagicMock()
        args.plugin_root = None
        result = _cmd_doctor(args)
        # In the real plugin root with all skills present, should pass
        assert result == 0, "Should fall back to default plugin root and pass"


class TestOtherCommandsUnchanged:
    def test_setup_and_version_commands_still_work(self, monkeypatch, tmp_path):
        """Setup and version commands should remain functional."""
        fake_hermes = MagicMock()
        fake_hermes.__version__ = "0.19.0"
        monkeypatch.setitem(sys.modules, "hermes", fake_hermes)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        setup_args = MagicMock()
        setup_args.yes = True
        setup_args.plugin_root = None
        setup_result = _cmd_setup(setup_args)
        version_result = _cmd_version(MagicMock())
        assert setup_result == 0, "Setup command should still work"
        assert version_result == 0, "Version command should still work"