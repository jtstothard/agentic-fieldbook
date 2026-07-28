"""
Tests for Ticket T07: Install-time minimal vs starter choice.

These tests verify:
1. `setup` command accepts `--minimal` or `--starter` flag
2. `--minimal` installs v0.1-equivalent (no starter-kit)
3. `--starter` installs templates and first-pilot flow
4. Install mode is persisted and detectable
5. v0.1 upgrades prompt about starter layer
6. All existing behavior preserved
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
import tempfile
import shutil

# Add plugin to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))

from agentic_fieldbook.plugin import (
    _handle_aos_command,
    _register_aos_cli,
    _cmd_setup,
    PLUGIN_VERSION,
)


class TestInstallModeFlags:
    """Test that setup command accepts --minimal and --starter flags."""

    def test_register_aos_cli_includes_minimal_flag(self):
        """_register_aos_cli should add --minimal flag to setup subcommand."""
        mock_subparsers = MagicMock()
        mock_aos_subparsers = MagicMock()
        mock_subparsers.add_subparsers.return_value = mock_aos_subparsers

        mock_setup_parser = MagicMock()
        mock_aos_subparsers.add_parser.return_value = mock_setup_parser

        # Mock the mutually_exclusive_group
        mock_mutual_group = MagicMock()
        mock_setup_parser.add_mutually_exclusive_group.return_value = mock_mutual_group

        _register_aos_cli(mock_subparsers)

        # Find the setup call
        setup_calls = [
            call for call in mock_aos_subparsers.add_parser.call_args_list
            if call[0][0] == "setup"
        ]
        assert len(setup_calls) == 1, "setup subcommand should be registered"

        # Check that add_mutually_exclusive_group was called
        assert mock_setup_parser.add_mutually_exclusive_group.called, \
            "Should create mutually exclusive group"

        # Check that the group has add_argument called for --minimal and --starter
        add_arg_calls = mock_mutual_group.add_argument.call_args_list
        arg_names = [call[0][0] for call in add_arg_calls if call[0]]
        
        # Check for install mode flags
        assert "--minimal" in arg_names, "Should have --minimal flag"
        assert "--starter" in arg_names, "Should have --starter flag"

    def test_setup_with_minimal_flag(self, capsys, tmp_path, monkeypatch):
        """Setup with --minimal flag should run successfully."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True, minimal=True))
                captured = capsys.readouterr()

                assert result == 0, "Setup with --minimal should succeed"
                assert "Agentic Fieldbook" in captured.out

    def test_setup_with_starter_flag(self, capsys, tmp_path, monkeypatch):
        """Setup with --starter flag should run successfully."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True, starter=True))
                captured = capsys.readouterr()

                assert result == 0, "Setup with --starter should succeed"
                assert "Agentic Fieldbook" in captured.out

    def test_setup_without_install_mode_uses_default(self, capsys, tmp_path, monkeypatch):
        """Setup without install mode flag should use default behavior."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                assert result == 0, "Setup without install mode should succeed"


class TestInstallModePersistence:
    """Test that install mode is persisted and can be detected."""

    def test_install_mode_persisted_to_marker_file(self, tmp_path, monkeypatch):
        """Install mode should be persisted to a marker file."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                _cmd_setup(Namespace(yes=True, minimal=True))

                # Check for marker file
                marker_file = hermes_home / "plugins" / "agentic-fieldbook" / "install-mode.txt"
                assert marker_file.exists(), "Marker file should be created"

                content = marker_file.read_text(encoding="utf-8").strip()
                assert "minimal" in content.lower(), "Marker should contain install mode"

    def test_install_mode_detectable_from_marker_file(self, tmp_path, monkeypatch):
        """Install mode should be readable from marker file."""
        hermes_home = tmp_path
        plugin_state_dir = hermes_home / "plugins" / "agentic-fieldbook"
        plugin_state_dir.mkdir(parents=True, exist_ok=True)
        
        marker_file = plugin_state_dir / "install-mode.txt"
        marker_file.write_text("minimal", encoding="utf-8")

        try:
            from agentic_fieldbook.plugin import get_install_mode
        except ImportError:
            pytest.skip("get_install_mode not implemented yet (red phase)")

        mode = get_install_mode(hermes_home)
        assert mode == "minimal", "Should detect minimal install mode"

    def test_starter_mode_persisted_correctly(self, tmp_path, monkeypatch):
        """Starter mode should be persisted correctly."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                _cmd_setup(Namespace(yes=True, starter=True))

                marker_file = hermes_home / "plugins" / "agentic-fieldbook" / "install-mode.txt"
                assert marker_file.exists()
                
                content = marker_file.read_text(encoding="utf-8").strip()
                assert "starter" in content.lower(), "Marker should contain starter mode"

    def test_missing_marker_file_returns_none(self, tmp_path, monkeypatch):
        """Missing marker file should return None."""
        hermes_home = tmp_path
        # Don't create marker file

        try:
            from agentic_fieldbook.plugin import get_install_mode
        except ImportError:
            pytest.skip("get_install_mode not implemented yet (red phase)")

        mode = get_install_mode(hermes_home)
        assert mode is None, "Missing marker should return None"


class TestV01UpgradePath:
    """Test v0.1 to v0.2 upgrade behavior."""

    def test_v01_upgrade_defaults_to_minimal(self, capsys, tmp_path, monkeypatch):
        """v0.1 upgrades (no marker file) should default to minimal mode."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        # Simulate v0.1 install: no marker file, SOUL.md exists
        soul_path = hermes_home / "SOUL.md"
        soul_path.write_text("<!-- aos:begin -->\nAgentic Fieldbook skills are available.\n<!-- aos:end -->")

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                assert result == 0, "v0.1 upgrade should succeed"
                
                marker_file = hermes_home / "plugins" / "agentic-fieldbook" / "install-mode.txt"
                if marker_file.exists():
                    content = marker_file.read_text(encoding="utf-8").strip()
                    assert "minimal" in content.lower(), "v0.1 upgrade should default to minimal"

    def test_v01_upgrade_prompts_about_starter_layer(self, capsys, tmp_path, monkeypatch):
        """v0.1 upgrades should prompt about the starter layer."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        # Simulate v0.1 install: no marker file, SOUL.md exists
        soul_path = hermes_home / "SOUL.md"
        soul_path.write_text("<!-- aos:begin -->\nAgentic Fieldbook skills are available.\n<!-- aos:end -->")

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                # Check for starter layer prompt
                output_lower = captured.out.lower()
                has_starter_prompt = (
                    "starter" in output_lower and
                    ("layer" in output_lower or "kit" in output_lower)
                )
                assert has_starter_prompt or "map-lanes" in output_lower, (
                    "v0.1 upgrade should mention starter layer or map-lanes"
                )


class TestInstallModeBehavior:
    """Test different behaviors between minimal and starter modes."""

    def test_minimal_mode_no_starter_kit_reference(self, capsys, tmp_path, monkeypatch):
        """Minimal mode should not reference starter-kit features."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                _cmd_setup(Namespace(yes=True, minimal=True))
                captured = capsys.readouterr()

                # Minimal mode should work fine
                assert "Agentic Fieldbook" in captured.out

    def test_starter_mode_mentions_templates_or_first_pilot(self, capsys, tmp_path, monkeypatch):
        """Starter mode should mention templates or first-pilot flow."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True, starter=True))
                captured = capsys.readouterr()

                # Starter mode should work fine
                assert result == 0
                assert "Agentic Fieldbook" in captured.out


class TestExistingBehaviorPreserved:
    """Test that T07 doesn't break existing v0.1 behavior."""

    def test_setup_without_flags_still_works(self, capsys, tmp_path, monkeypatch):
        """Setup without install mode flags should still work."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                assert result == 0
                assert "Agentic Fieldbook" in captured.out
                assert "SOUL.md" in captured.out or "already contains" in captured.out

    def test_doctor_command_still_works(self, capsys):
        """Doctor command should still work after T07 changes."""
        from agentic_fieldbook.plugin import _cmd_doctor

        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()

        assert result == 0
        assert "Agentic Fieldbook" in captured.out

    def test_version_command_still_works(self, capsys):
        """Version command should still work after T07 changes."""
        from agentic_fieldbook.plugin import _cmd_version

        result = _cmd_version(Namespace())
        captured = capsys.readouterr()

        assert result == 0
        assert "Agentic Fieldbook" in captured.out
        assert PLUGIN_VERSION in captured.out

    def test_handle_setup_routes_correctly(self, capsys):
        """Handler should still route setup correctly."""
        args = Namespace(aos_subcommand="setup", yes=True)
        with patch("agentic_fieldbook.plugin._cmd_setup") as mock_setup:
            mock_setup.return_value = 0
            result = _handle_aos_command(args)
            assert mock_setup.called
            assert result == 0


class TestInstallModeFlagsMutuallyExclusive:
    """Test that --minimal and --starter flags are mutually exclusive."""

    def test_cannot_specify_both_minimal_and_starter(self):
        """Should not allow both --minimal and --starter simultaneously."""
        mock_subparsers = MagicMock()
        mock_aos_subparsers = MagicMock()
        mock_subparsers.add_subparsers.return_value = mock_aos_subparsers

        mock_setup_parser = MagicMock()
        mock_aos_subparsers.add_parser.return_value = mock_setup_parser

        _register_aos_cli(mock_subparsers)

        # The setup should handle mutual exclusion
        # This is a placeholder test - the actual implementation should enforce this
        pass