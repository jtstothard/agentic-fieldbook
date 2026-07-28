"""
Tests for profile-aware gateway detection logic in root __init__.py entrypoint.

Tests the git-install entrypoint (root __init__.py) separately from the
package install entrypoint (agentic_fieldbook/plugin.py).
"""

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from argparse import Namespace
import pytest

# Add the plugin to the path
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

# Import from root __init__.py (git install entrypoint)
from __init__ import _get_hermes_profile, _profile_has_gateway, _gateway_is_running_for_profile, _cmd_setup


class TestProfileDetection:
    """Test profile name detection from environment."""

    def test_profile_from_hermes_profile_env(self, monkeypatch):
        """Should extract profile from HERMES_PROFILE env var."""
        monkeypatch.setenv("HERMES_PROFILE", "coder")
        assert _get_hermes_profile() == "coder"

    def test_profile_ignored_when_default(self, monkeypatch):
        """Should return None when HERMES_PROFILE is 'default'."""
        monkeypatch.setenv("HERMES_PROFILE", "default")
        assert _get_hermes_profile() is None

    def test_profile_from_hermes_home_path(self, monkeypatch):
        """Should extract profile from HERMES_HOME path."""
        monkeypatch.setenv("HERMES_HOME", "/home/user/.hermes/profiles/coder")
        assert _get_hermes_profile() == "coder"

    def test_profile_none_when_no_indicators(self, monkeypatch):
        """Should return None when no profile indicators exist."""
        monkeypatch.delenv("HERMES_PROFILE", raising=False)
        monkeypatch.setenv("HERMES_HOME", "/home/user/.hermes")
        assert _get_hermes_profile() is None


class TestProfileGatewayConfig:
    """Test detection of whether a profile has gateway configured."""

    def test_returns_false_when_profile_none(self, monkeypatch):
        """Should return False when profile is None."""
        assert _profile_has_gateway(None) is False

    @patch('subprocess.run')
    def test_detects_gateway_in_profile_output(self, mock_run, monkeypatch):
        """Should return True when 'Gateway:' appears in profile show output."""
        mock_run.return_value = Mock(returncode=0, stdout="Gateway: running")
        assert _profile_has_gateway("coder") is True

    @patch('subprocess.run')
    def test_returns_false_when_gateway_missing(self, mock_run, monkeypatch):
        """Should return False when 'Gateway:' does not appear in output."""
        mock_run.return_value = Mock(returncode=0, stdout="Profile: coder")
        assert _profile_has_gateway("coder") is False

    @patch('subprocess.run')
    def test_returns_false_on_command_error(self, mock_run, monkeypatch):
        """Should return False when profile show command fails."""
        mock_run.return_value = Mock(returncode=1, stdout="")
        assert _profile_has_gateway("coder") is False

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_returns_false_on_missing_command(self, mock_run, monkeypatch):
        """Should return False when hermes command is not found."""
        assert _profile_has_gateway("coder") is False


class TestGatewayRunningForProfile:
    """Test detection of gateway runtime state for specific profile."""

    def test_returns_false_when_profile_has_no_gateway(self, monkeypatch):
        """Should return False when profile doesn't have gateway configured."""
        monkeypatch.delenv("HERMES_GATEWAY_BUSY_INPUT_MODE", raising=False)
        monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_PORT", raising=False)

        with patch('__init__._profile_has_gateway', return_value=False):
            assert _gateway_is_running_for_profile("coder") is False

    @patch('__init__._profile_has_gateway', return_value=True)
    def test_detects_running_gateway_via_env_vars(self, mock_has_gateway, monkeypatch):
        """Should return True when gateway env vars are present."""
        monkeypatch.setenv("HERMES_DASHBOARD_PORT", "9119")
        assert _gateway_is_running_for_profile("coder") is True

    @patch('__init__._profile_has_gateway', return_value=True)
    def test_returns_false_without_env_vars(self, mock_has_gateway, monkeypatch):
        """Should return False when profile has gateway but it's not running."""
        monkeypatch.delenv("HERMES_GATEWAY_BUSY_INPUT_MODE", raising=False)
        monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_PORT", raising=False)
        assert _gateway_is_running_for_profile("coder") is False

    @patch('__init__._profile_has_gateway', return_value=True)
    def test_any_env_var_indicator_sufficient(self, mock_has_gateway, monkeypatch):
        """Should return True when ANY gateway indicator is present."""
        monkeypatch.setenv("HERMES_GATEWAY_BUSY_INPUT_MODE", "interrupt")
        assert _gateway_is_running_for_profile("coder") is True

        monkeypatch.delenv("HERMES_GATEWAY_BUSY_INPUT_MODE", raising=False)
        monkeypatch.setenv("HERMES_GATEWAY_PORT", "8000")
        assert _gateway_is_running_for_profile("coder") is True


class TestRootSetupGatewayMessaging:
    """Test setup gateway messaging in root __init__.py entrypoint."""

    def test_setup_messages_for_non_gateway_profile(self, capsys, tmp_path, monkeypatch):
        """Setup should show CLI/worker completion message for non-gateway profile."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        # Simulate non-gateway profile (no profile, so _get_hermes_profile returns None)
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert "Setup complete. The plugin is active for the next CLI/worker invocation." in captured.out
                assert "gateway" not in captured.out.lower()

    @patch('__init__._profile_has_gateway', return_value=True)
    @patch('__init__._gateway_is_running_for_profile', return_value=True)
    @patch('__init__._get_hermes_profile', return_value='coder')
    def test_setup_messages_for_running_gateway(self, mock_profile, mock_running, mock_has_gateway, capsys, tmp_path, monkeypatch):
        """Setup should show restart message when gateway is running."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert "Restart the gateway for the plugin to take effect:" in captured.out

    @patch('__init__._profile_has_gateway', return_value=True)
    @patch('__init__._gateway_is_running_for_profile', return_value=False)
    @patch('__init__._get_hermes_profile', return_value='coder')
    def test_setup_messages_for_stopped_gateway(self, mock_profile, mock_running, mock_has_gateway, capsys, tmp_path, monkeypatch):
        """Setup should show start message when gateway is configured but stopped."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert "Start the gateway for the plugin to take effect:" in captured.out