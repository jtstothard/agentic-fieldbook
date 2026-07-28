"""
Tests for Ticket T01: Profile-mapping wizard command structure.

These tests verify:
1. `hermes aos map-lanes` command registration
2. Basic CLI argument parsing
3. Stub handler that prints coming-soon message
4. Setup command prints pointer to map-lanes
5. All existing plugin commands remain functional
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

# Add plugin to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))

from agentic_fieldbook.plugin import (
    _handle_aos_command,
    _register_aos_cli,
    _cmd_setup,
)


class TestMapLanesCommandRegistration:
    """Test that map-lanes command is registered correctly."""

    def test_register_aos_cli_includes_map_lanes(self):
        """_register_aos_cli should add map-lanes subcommand."""
        mock_subparsers = MagicMock()
        mock_aos_subparsers = MagicMock()
        mock_subparsers.add_subparsers.return_value = mock_aos_subparsers

        _register_aos_cli(mock_subparsers)

        # Should have 7 subcommands now (setup, doctor, version, migrate, preflight, contract, map-lanes)
        assert mock_aos_subparsers.add_parser.call_count == 8

        # Verify subcommand names
        call_args = [call[0][0] for call in mock_aos_subparsers.add_parser.call_args_list]
        assert "map-lanes" in call_args, "map-lanes should be registered"
        assert "setup" in call_args
        assert "doctor" in call_args
        assert "version" in call_args

    def test_map_lanes_parser_has_basic_help(self):
        """map-lanes parser should have help text."""
        mock_subparsers = MagicMock()
        mock_aos_subparsers = MagicMock()
        mock_subparsers.add_subparsers.return_value = mock_aos_subparsers

        _register_aos_cli(mock_subparsers)

        # Find the map-lanes call
        for call in mock_aos_subparsers.add_parser.call_args_list:
            if call[0][0] == "map-lanes":
                assert "help" in call[1], "map-lanes should have help parameter"
                assert "lanes" in call[1]["help"].lower(), "Help should mention lanes"
                return
        pytest.fail("map-lanes parser not found in registration")


class TestMapLanesCommandHandler:
    """Test that map-lanes command routes to correct handler."""

    def test_handle_map_lanes_subcommand(self):
        """Handler should route 'map-lanes' to _cmd_map_lanes."""
        args = Namespace(aos_subcommand="map-lanes")
        with patch("agentic_fieldbook.plugin._cmd_map_lanes") as mock_map_lanes:
            mock_map_lanes.return_value = 0
            result = _handle_aos_command(args)
            assert mock_map_lanes.called, "_cmd_map_lanes should be called"
            assert result == 0


class TestMapLanesStubHandler:
    """Test the map-lanes stub handler implementation."""

    def test_cmd_map_lanes_exists_and_is_callable(self):
        """_cmd_map_lanes function should exist and be callable."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            assert callable(_cmd_map_lanes), "_cmd_map_lanes should be callable"
        except ImportError:
            pytest.skip("_cmd_map_lanes not implemented yet (red phase)")

    def test_cmd_map_lanes_returns_zero(self, capsys):
        """_cmd_map_lanes should return 0 (success)."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            result = _cmd_map_lanes(Namespace())
            assert result == 0
        except ImportError:
            pytest.skip("_cmd_map_lanes not implemented yet (red phase)")

    def test_cmd_map_lanes_prints_coming_soon_message(self, capsys):
        """_cmd_map_lanes should print coming-soon message pointing to next ticket."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            _cmd_map_lanes(Namespace())
            captured = capsys.readouterr()

            assert "coming" in captured.out.lower() or "T03" in captured.out, (
                "Should mention coming soon or T03"
            )
        except ImportError:
            pytest.skip("_cmd_map_lanes not implemented yet (red phase)")

    def test_cmd_map_lanes_mentions_profile_mapping(self, capsys):
        """_cmd_map_lanes should mention profile mapping or wizard."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            _cmd_map_lanes(Namespace())
            captured = capsys.readouterr()

            # Should mention at least one of these key terms
            has_profile = "profile" in captured.out.lower()
            has_mapping = "mapping" in captured.out.lower()
            has_wizard = "wizard" in captured.out.lower()

            assert has_profile or has_mapping or has_wizard, (
                "Should mention profile, mapping, or wizard"
            )
        except ImportError:
            pytest.skip("_cmd_map_lanes not implemented yet (red phase)")


class TestSetupCommandMapLanesPointer:
    """Test that setup command prints pointer to map-lanes on completion."""

    def test_setup_prints_map_lanes_pointer_on_success(self, capsys, tmp_path, monkeypatch):
        """Setup should print pointer to map-lanes when it succeeds."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                assert result == 0, "Setup should succeed"
                assert "map-lanes" in captured.out.lower(), (
                    "Setup should mention map-lanes command"
                )
                assert "next step" in captured.out.lower() or "run" in captured.out.lower(), (
                    "Should indicate next action"
                )

    def test_setup_map_lanes_pointer_shows_command(self, capsys, tmp_path, monkeypatch):
        """Setup should show the exact map-lanes command to run."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()

                assert result == 0
                # Should show the command format
                assert "hermes" in captured.out.lower() or "aos" in captured.out.lower(), (
                    "Should show command context"
                )
                assert "map-lanes" in captured.out.lower()


class TestExistingCommandsRemainFunctional:
    """Test that T01 doesn't break existing v0.1 commands."""

    def test_setup_command_still_works(self, capsys, tmp_path, monkeypatch):
        """Setup command should still work after map-lanes addition."""
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

    def test_doctor_command_still_works(self, capsys):
        """Doctor command should still work after map-lanes addition."""
        from agentic_fieldbook.plugin import _cmd_doctor

        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()

        assert result == 0
        assert "Agentic Fieldbook" in captured.out

    def test_version_command_still_works(self, capsys):
        """Version command should still work after map-lanes addition."""
        from agentic_fieldbook.plugin import _cmd_version

        result = _cmd_version(Namespace())
        captured = capsys.readouterr()

        assert result == 0
        assert "Agentic Fieldbook" in captured.out

    def test_migrate_command_still_works(self, capsys):
        """Migrate command should still work after map-lanes addition."""
        from agentic_fieldbook.plugin import _cmd_migrate

        result = _cmd_migrate(Namespace())
        captured = capsys.readouterr()

        assert result == 0
        assert "no changes needed" in captured.out

    def test_handle_setup_still_routes(self, capsys):
        """Handler should still route setup correctly."""
        args = Namespace(aos_subcommand="setup")
        with patch("agentic_fieldbook.plugin._cmd_setup") as mock_setup:
            mock_setup.return_value = 0
            result = _handle_aos_command(args)
            assert mock_setup.called
            assert result == 0

    def test_handle_doctor_still_routes(self, capsys):
        """Handler should still route doctor correctly."""
        args = Namespace(aos_subcommand="doctor")
        with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
            mock_doctor.return_value = 0
            result = _handle_aos_command(args)
            assert mock_doctor.called
            assert result == 0