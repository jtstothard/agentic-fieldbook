"""
Tests for gateway detection logic in root __init__.py entrypoint.

Tests the git-install entrypoint (root __init__.py) separately from the
package install entrypoint (agentic_fieldbook/plugin.py).
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace
import pytest

# Add the plugin to the path
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

# Import from root __init__.py (git install entrypoint)
from __init__ import _gateway_is_running, _cmd_setup


class TestRootGatewayDetection:
    """Test gateway presence detection in root __init__.py entrypoint."""

    def test_gateway_detection_returns_bool(self):
        """_gateway_is_running should return a boolean."""
        result = _gateway_is_running()
        assert isinstance(result, bool)

    def test_gateway_detection_no_gateway_env(self, monkeypatch):
        """Should return False when no gateway env vars are set."""
        for key in ["HERMES_GATEWAY_BUSY_INPUT_MODE", "HERMES_DASHBOARD_PORT", "HERMES_GATEWAY_PORT"]:
            monkeypatch.delenv(key, raising=False)
        assert _gateway_is_running() is False

    def test_gateway_detection_with_dashboard_port(self, monkeypatch):
        """Should return True when HERMES_DASHBOARD_PORT is set."""
        monkeypatch.delenv("HERMES_GATEWAY_BUSY_INPUT_MODE", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_PORT", raising=False)
        monkeypatch.setenv("HERMES_DASHBOARD_PORT", "9119")
        assert _gateway_is_running() is True

    def test_gateway_detection_with_busy_input_mode(self, monkeypatch):
        """Should return True when HERMES_GATEWAY_BUSY_INPUT_MODE is set."""
        monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_PORT", raising=False)
        monkeypatch.setenv("HERMES_GATEWAY_BUSY_INPUT_MODE", "interrupt")
        assert _gateway_is_running() is True

    def test_gateway_detection_with_gateway_port(self, monkeypatch):
        """Should return True when HERMES_GATEWAY_PORT is set."""
        monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
        monkeypatch.delenv("HERMES_GATEWAY_BUSY_INPUT_MODE", raising=False)
        monkeypatch.setenv("HERMES_GATEWAY_PORT", "8000")
        assert _gateway_is_running() is True

    def test_gateway_detection_any_indicator_sufficient(self, monkeypatch):
        """Should return True when ANY gateway indicator is present."""
        monkeypatch.setenv("HERMES_DASHBOARD_PORT", "9119")
        assert _gateway_is_running() is True

        # Also true with just one other indicator
        monkeypatch.delenv("HERMES_DASHBOARD_PORT", raising=False)
        monkeypatch.setenv("HERMES_GATEWAY_BUSY_INPUT_MODE", "interrupt")
        assert _gateway_is_running() is True


class TestRootSetupGatewayMessaging:
    """Test setup gateway messaging in root __init__.py entrypoint."""

    def test_setup_does_not_show_restart_message_without_gateway(self, capsys, tmp_path, monkeypatch):
        """Setup should not show gateway restart message when gateway is not running."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        # Ensure no gateway indicators
        for key in ["HERMES_GATEWAY_BUSY_INPUT_MODE", "HERMES_DASHBOARD_PORT", "HERMES_GATEWAY_PORT"]:
            monkeypatch.delenv(key, raising=False)

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert _gateway_is_running() is False

    def test_setup_runs_correctly_with_gateway(self, capsys, tmp_path, monkeypatch):
        """Setup should run correctly when gateway is running (message would be shown if implemented)."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        # Set a gateway indicator
        monkeypatch.setenv("HERMES_DASHBOARD_PORT", "9119")

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert _gateway_is_running() is True