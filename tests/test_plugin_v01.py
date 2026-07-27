"""
Tests for Agentic Fieldbook v0.1 plugin commands (setup, doctor, version).

These are stub-level tests that verify the commands are registered and respond.
Full runtime verification and skill loading tests will be added in later tickets.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
import sys
from pathlib import Path

# Add the plugin to the path
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

from agentic_fieldbook.plugin import (
    _cmd_setup,
    _cmd_doctor,
    _cmd_version,
    _cmd_migrate,
    _handle_aos_command,
    _register_aos_cli,
    plugin_info,
    _parse_version,
    _check_hermes_version,
    _skills_toolset_available,
)


class TestCommandStubs:
    """Test that stub commands are callable and return expected outputs."""

    def test_setup_command_returns_zero(self, capsys):
        """Setup command should succeed when Hermes is compatible and --yes is passed."""
        # Mock Hermes as compatible for this test
        from unittest.mock import MagicMock
        import sys
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        import tempfile
        import os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            soul_path = Path(tmpdir) / "SOUL.md"
            os.environ["HERMES_HOME"] = tmpdir
            with patch.dict("sys.modules", {"hermes": mock_hermes}):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()
                    assert result == 0
                    assert "Agentic Fieldbook" in captured.out
                    assert "Inserted managed instructions" in captured.out

    def test_doctor_command_returns_zero(self, capsys):
        """Doctor command stub should print message and return 0."""
        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "Agentic Fieldbook" in captured.out
        assert "doctor — stub" in captured.out

    def test_version_command_returns_zero_and_shows_version(self, capsys):
        """Version command should show bundle version and compatibility."""
        result = _cmd_version(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "0.1.0" in captured.out
        assert "Hermes compatibility" in captured.out
        assert "0.18.0–0.20.0" in captured.out

    def test_migrate_command_is_clean_noop(self, capsys):
        result = _cmd_migrate(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "migrate: no changes needed" in captured.out

    def test_migrate_command_is_idempotent(self, capsys):
        first = _cmd_migrate(Namespace())
        first_output = capsys.readouterr().out
        second = _cmd_migrate(Namespace())
        second_output = capsys.readouterr().out
        assert (first, first_output) == (second, second_output)


class TestVersionChecking:
    """Test Hermes version checking logic."""

    def test_parse_version_valid(self):
        """Version parsing should work for valid semver strings."""
        assert _parse_version("0.18.0") == (0, 18, 0)
        assert _parse_version("1.2.3") == (1, 2, 3)
        assert _parse_version("10.20.30") == (10, 20, 30)

    def test_parse_version_invalid(self):
        """Version parsing should raise for invalid strings."""
        with pytest.raises(ValueError, match="Invalid version format"):
            _parse_version("1.2")
        with pytest.raises(ValueError, match="Invalid version format"):
            _parse_version("1.2.3.4")

    def test_check_hermes_version_success(self):
        """Should return success when Hermes version is in range."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.5"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            is_compatible, error_msg = _check_hermes_version()
            assert is_compatible is True
            assert error_msg == ""

    def test_check_hermes_version_below_floor(self):
        """Should return error when Hermes version is below minimum."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.17.0"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            is_compatible, error_msg = _check_hermes_version()
            assert is_compatible is False
            assert "below minimum 0.18.0" in error_msg

    def test_check_hermes_version_above_ceiling(self):
        """Should return error when Hermes version exceeds maximum."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.21.0"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            is_compatible, error_msg = _check_hermes_version()
            assert is_compatible is False
            assert "exceeds maximum 0.20.0" in error_msg

    def test_check_hermes_version_no_module(self):
        """Should return error when Hermes runtime modules are not found."""
        with patch(
            "agentic_fieldbook.plugin._hermes_runtime_module",
            side_effect=ImportError,
        ):
            is_compatible, error_msg = _check_hermes_version()
            assert is_compatible is False
            assert "Hermes module not found" in error_msg

    def test_check_hermes_version_no_version_attr(self):
        """Should return error when Hermes lacks __version__."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock(spec=[])  # Empty spec means no attributes

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            is_compatible, error_msg = _check_hermes_version()
            assert is_compatible is False
            assert "__version__ not found" in error_msg

    def test_setup_command_passes_version_check(self, capsys, tmp_path, monkeypatch):
        """Setup should succeed when Hermes version is compatible."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert "Agentic Fieldbook v0.1.0 setup" in captured.out
                assert "0.18.0–0.20.0" in captured.out

    def test_setup_command_fails_below_floor(self, capsys):
        """Setup should fail when Hermes version is below floor."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.17.0"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            result = _cmd_setup(Namespace(yes=True))
            captured = capsys.readouterr()
            assert result != 0
            assert "ERROR" in captured.err
            assert "below minimum 0.18.0" in captured.err
            assert "0.18.0–0.20.0" in captured.err

    def test_setup_command_fails_above_ceiling(self, capsys):
        """Setup should fail when Hermes version exceeds ceiling."""
        from unittest.mock import MagicMock

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.21.0"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            result = _cmd_setup(Namespace(yes=True))
            captured = capsys.readouterr()
            assert result != 0
            assert "ERROR" in captured.err
            assert "exceeds maximum 0.20.0" in captured.err


class TestCommandHandler:
    """Test the command dispatcher routes to correct handlers."""

    def test_handle_setup_subcommand(self):
        """Handler should route 'setup' to _cmd_setup."""
        args = Namespace(aos_subcommand="setup")
        with patch("agentic_fieldbook.plugin._cmd_setup") as mock_setup:
            mock_setup.return_value = 0
            result = _handle_aos_command(args)
            assert mock_setup.called
            assert result == 0

    def test_handle_doctor_subcommand(self):
        """Handler should route 'doctor' to _cmd_doctor."""
        args = Namespace(aos_subcommand="doctor")
        with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
            mock_doctor.return_value = 0
            result = _handle_aos_command(args)
            assert mock_doctor.called
            assert result == 0

    def test_handle_version_subcommand(self):
        """Handler should route 'version' to _cmd_version."""
        args = Namespace(aos_subcommand="version")
        with patch("agentic_fieldbook.plugin._cmd_version") as mock_version:
            mock_version.return_value = 0
            result = _handle_aos_command(args)
            assert mock_version.called
            assert result == 0

    def test_handle_unknown_subcommand_returns_error(self, capsys):
        """Handler should return non-zero for unknown subcommands."""
        args = Namespace(aos_subcommand="unknown")
        result = _handle_aos_command(args)
        captured = capsys.readouterr()
        assert result == 1
        assert "Unknown aos subcommand" in captured.out


class TestPluginMetadata:
    """Test plugin discovery and registration hooks."""

    def test_plugin_info_returns_expected_metadata(self):
        """plugin_info should return correct metadata dict."""
        info = plugin_info()
        assert info["name"] == "agentic-fieldbook"
        assert info["version"] == "0.1.0"
        assert info["hermes_compatibility"] == {"min": "0.18.0", "max": "0.20.0"}
        assert "homepage" in info

    def test_register_cli_structure(self):
        """_register_aos_cli should add aos subcommand structure."""
        mock_subparsers = MagicMock()
        mock_aos_subparsers = MagicMock()
        mock_subparsers.add_subparsers.return_value = mock_aos_subparsers

        _register_aos_cli(mock_subparsers)

        # Verify four subcommands were added (setup, doctor, version, migrate)
        assert mock_aos_subparsers.add_parser.call_count == 4

        # Verify subcommand names
        call_args = [call[0][0] for call in mock_aos_subparsers.add_parser.call_args_list]
        assert "setup" in call_args
        assert "doctor" in call_args
        assert "version" in call_args
        assert "migrate" in call_args


class TestSkillArtifacts:
    """Test that lane-calibration skill artifacts exist and are valid."""

    def test_lane_calibration_skill_exists(self):
        """Lane-calibration SKILL.md should exist."""
        skill_path = plugin_root / "skills" / "lane-calibration" / "SKILL.md"
        assert skill_path.exists(), "Lane-calibration SKILL.md should exist"

    def test_calibration_schema_exists(self):
        """Calibration schema YAML should exist."""
        schema_path = (
            plugin_root
            / "skills"
            / "lane-calibration"
            / "references"
            / "calibration-schema.yaml"
        )
        assert schema_path.exists(), "Calibration schema should exist"

    def test_calibration_template_exists(self):
        """Calibration template should exist with uncalibrated status."""
        template_path = (
            plugin_root
            / "skills"
            / "lane-calibration"
            / "references"
            / "calibration-template.yaml"
        )
        assert template_path.exists(), "Calibration template should exist"
        content = template_path.read_text()
        assert "calibration_status: uncalibrated" in content, (
            "Template should start uncalibrated"
        )

    def test_calibration_example_exists_and_is_synthetic(self):
        """Calibration example should exist and be marked as synthetic."""
        example_path = (
            plugin_root
            / "skills"
            / "lane-calibration"
            / "references"
            / "calibration-example.yaml"
        )
        assert example_path.exists(), "Calibration example should exist"
        content = example_path.read_text()
        assert "synthetic" in content.lower(), "Example should be marked synthetic"
        assert "fabricated" in content.lower(), "Example should warn about fabricated IDs"

    def test_recalibration_triggers_doc_exists(self):
        """Recalibration triggers documentation should exist."""
        triggers_path = (
            plugin_root
            / "skills"
            / "lane-calibration"
            / "references"
            / "recalibration-triggers.md"
        )
        assert triggers_path.exists(), "Recalibration triggers doc should exist"

    def test_example_uses_no_real_identifiers(self):
        """Worked example should contain no real IDs or credentials."""
        example_path = (
            plugin_root
            / "skills"
            / "lane-calibration"
            / "references"
            / "calibration-example.yaml"
        )
        content = example_path.read_text()

        # Common real patterns that should NOT appear
        forbidden = [
            "api_key",
            "password",
            "token",
            "192.168",
            "10.",
            "172.16",
            "github.com/",
            "jtstothard",  # User's real handle
        ]

        for pattern in forbidden:
            assert pattern.lower() not in content.lower(), (
                f"Example should not contain real pattern: {pattern}"
            )


class TestPluginManifest:
    """Test the manifest required by Hermes' plugin loader."""

    def test_plugin_manifest_exists_and_has_required_fields(self):
        """plugin.yaml must be discoverable and contain loader metadata."""
        import yaml

        manifest_path = plugin_root / "agentic_fieldbook" / "plugin.yaml"
        assert manifest_path.exists(), "agentic_fieldbook/plugin.yaml should exist"
        manifest = yaml.safe_load(manifest_path.read_text())
        assert isinstance(manifest, dict)
        for field in ("name", "version", "kind"):
            assert manifest.get(field), f"plugin.yaml must define {field}"
        assert manifest["kind"] == "standalone"


class TestBundleVersioning:
    """Test bundle version consistency."""

    def test_version_file_exists(self):
        """VERSION file should exist."""
        version_path = plugin_root / "VERSION"
        assert version_path.exists(), "VERSION file should exist"

    def test_version_file_content_matches_plugin(self):
        """VERSION file should match plugin metadata."""
        version_path = plugin_root / "VERSION"
        version_content = version_path.read_text().strip()
        info = plugin_info()
        assert version_content == info["version"], (
            "VERSION file should match plugin version"
        )
        assert version_content == "0.1.0", "v0.1.0 is the expected version"

    def test_setup_py_exists_and_is_valid_python(self):
        """setup.py should exist and be valid Python."""
        setup_path = plugin_root / "setup.py"
        assert setup_path.exists(), "setup.py should exist"
        # Should be syntactically valid
        with open(setup_path) as f:
            compile(f.read(), setup_path, "exec")

    def test_pyproject_toml_exists(self):
        """pyproject.toml should exist."""
        pyproject_path = plugin_root / "pyproject.toml"
        assert pyproject_path.exists(), "pyproject.toml should exist"


class TestDoctorDetection:
    """Test that doctor can detect skill presence (v0.1 stub)."""

    def test_doctor_reports_detected_bundle_version(self, capsys):
        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "Agentic Fieldbook v0.1.0 doctor" in captured.out

    def test_doctor_stub_detects_plugin(self, capsys):
        """Doctor stub should indicate it detects the plugin."""
        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        # In v0.1 this is a stub, but it should at least respond
        assert "doctor" in captured.out.lower()

    def test_doctor_stub_mentions_verification(self, capsys):
        """Doctor stub should mention verification is coming."""
        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "verification" in captured.out.lower() or "checks" in captured.out.lower()


@pytest.mark.integration
class TestPluginRegistrationSimulation:
    """
    Simulate Hermes plugin registration without loading actual Hermes.

    This verifies the plugin structure matches Hermes expectations.
    """

    def test_register_function_exists(self):
        """Plugin should have a register() function."""
        from agentic_fieldbook import plugin

        assert hasattr(plugin, "register"), "Plugin should have register() function"
        assert callable(plugin.register), "register() should be callable"

    def test_register_accepts_context(self):
        """register() should accept a context argument."""
        from agentic_fieldbook import plugin

        mock_ctx = MagicMock()
        mock_ctx.register_cli_command = MagicMock()

        # Should not raise
        plugin.register(mock_ctx)

        # Should have registered a CLI command
        mock_ctx.register_cli_command.assert_called_once()
        call_kwargs = mock_ctx.register_cli_command.call_args[1]
        assert call_kwargs["name"] == "aos"
        assert "Agentic Fieldbook" in call_kwargs["help"]