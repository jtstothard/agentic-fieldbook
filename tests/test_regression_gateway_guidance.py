"""
Regression tests for gateway-restart/start guidance in aos setup.

These tests exercise the REAL code path (not mocked detection functions)
to catch any future re-introduction of unconditional gateway messages for
non-gateway profiles. This is the 3rd recurrence of this bug (#32 → #40 → #46).

Tests mock subprocess.run at the subprocess level (profile show output)
rather than mocking _profile_has_gateway itself, ensuring the real detection
logic runs and we verify actual stdout behavior.
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


class TestRealCodePathRootEntrypoint:
    """Test gateway guidance via real code path in root __init__.py (git install)."""

    def test_no_gateway_message_profile_without_gateway(self, capsys, tmp_path, monkeypatch):
        """
        AC-3a: Profile with no gateway key in show output -> NO gateway messages.

        This test exercises the REAL _profile_has_gateway code path by
        mocking subprocess.run (profile show output) instead of mocking
        the detection function itself.
        """
        from __init__ import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "worker")

        # Mock subprocess.run to return profile show output WITHOUT gateway
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Profile: worker\nPath: /home/user/.hermes/profiles/worker\nModel: quick-tasks\nSkills: 127"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("__init__._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()
                    assert result == 0
                    # Should show CLI/worker completion message
                    assert "CLI/worker invocation" in captured.out
                    # Should NOT show gateway action messages
                    assert "restart the gateway" not in captured.out.lower()
                    assert "start the gateway" not in captured.out.lower()
                    assert "hermes gateway restart" not in captured.out.lower()
                    assert "hermes gateway start" not in captured.out.lower()

    def test_no_gateway_message_none_profile(self, capsys, tmp_path, monkeypatch):
        """
        AC-3b: None profile (default) -> NO gateway messages.

        When HERMES_PROFILE is not set or is 'default', _get_hermes_profile
        returns None, and _profile_has_gateway(None) returns False.
        """
        from __init__ import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_PROFILE", raising=False)

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("__init__._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                # Should show CLI/worker completion message
                assert "CLI/worker invocation" in captured.out
                # Should NOT show gateway action messages
                assert "restart the gateway" not in captured.out.lower()
                assert "start the gateway" not in captured.out.lower()
                assert "hermes gateway restart" not in captured.out.lower()
                assert "hermes gateway start" not in captured.out.lower()

    def test_no_gateway_message_profile_show_fails(self, capsys, tmp_path, monkeypatch):
        """
        AC-3c: Profile show command failure -> NO gateway messages.

        When subprocess.run fails (returncode != 0), _profile_has_gateway
        returns False, so no gateway messages should appear.
        """
        from __init__ import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "nonexistent")

        # Mock subprocess.run to return failure
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = "ERROR: Profile not found"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("__init__._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()
                    assert result == 0
                    # Should show CLI/worker completion message
                    assert "CLI/worker invocation" in captured.out
                    # Should NOT show gateway action messages
                    assert "restart the gateway" not in captured.out.lower()
                    assert "start the gateway" not in captured.out.lower()
                    assert "hermes gateway restart" not in captured.out.lower()
                    assert "hermes gateway start" not in captured.out.lower()


class TestRealCodePathPackageEntrypoint:
    """Test gateway guidance via real code path in agentic_fieldbook/plugin.py (pip install)."""

    def test_no_gateway_message_profile_without_gateway(self, capsys, tmp_path, monkeypatch):
        """
        AC-3a: Profile with no gateway key in show output -> NO gateway messages.

        Package entrypoint test exercising the real code path.
        """
        from agentic_fieldbook.plugin import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "worker")

        # Mock subprocess.run to return profile show output WITHOUT gateway
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Profile: worker\nPath: /home/user/.hermes/profiles/worker\nModel: quick-tasks\nSkills: 127"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()
                    assert result == 0
                    # Should show CLI/worker completion message
                    assert "CLI/worker invocation" in captured.out
                    # Should NOT show gateway action messages
                    assert "restart the gateway" not in captured.out.lower()
                    assert "start the gateway" not in captured.out.lower()
                    assert "hermes gateway restart" not in captured.out.lower()
                    assert "hermes gateway start" not in captured.out.lower()

    def test_no_gateway_message_none_profile(self, capsys, tmp_path, monkeypatch):
        """
        AC-3b: None profile (default) -> NO gateway messages.

        Package entrypoint test for default profile case.
        """
        from agentic_fieldbook.plugin import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("HERMES_PROFILE", raising=False)

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                # Should show CLI/worker completion message
                assert "CLI/worker invocation" in captured.out
                # Should NOT show gateway action messages
                assert "restart the gateway" not in captured.out.lower()
                assert "start the gateway" not in captured.out.lower()
                assert "hermes gateway restart" not in captured.out.lower()
                assert "hermes gateway start" not in captured.out.lower()

    def test_no_gateway_message_profile_show_fails(self, capsys, tmp_path, monkeypatch):
        """
        AC-3c: Profile show command failure -> NO gateway messages.

        Package entrypoint test for subprocess failure case.
        """
        from agentic_fieldbook.plugin import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "nonexistent")

        # Mock subprocess.run to return failure
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = "ERROR: Profile not found"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    result = _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()
                    assert result == 0
                    # Should show CLI/worker completion message
                    assert "CLI/worker invocation" in captured.out
                    # Should NOT show gateway action messages
                    assert "restart the gateway" not in captured.out.lower()
                    assert "start the gateway" not in captured.out.lower()
                    assert "hermes gateway restart" not in captured.out.lower()
                    assert "hermes gateway start" not in captured.out.lower()


class TestRegressionSafetyGuard:
    """Tests that would fail if the bug re-introduces itself."""

    def test_regression_catches_unconditional_gateway_message_root(self, capsys, tmp_path, monkeypatch):
        """
        This test FAILS if the code emits gateway messages unconditionally
        (bypassing the _profile_has_gateway check).
        """
        from __init__ import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "worker")

        # Simulate a profile WITHOUT gateway configuration
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Profile: worker\nModel: quick-tasks"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("__init__._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()

                    # These assertions would FAIL if gateway guidance is emitted
                    # for non-gateway profiles (the bug we're preventing)
                    gateway_action_phrases = [
                        "restart the gateway",
                        "start the gateway",
                        "hermes gateway restart",
                        "hermes gateway start",
                    ]
                    for phrase in gateway_action_phrases:
                        assert phrase not in captured.out.lower(), (
                            f"REGRESSION DETECTED: Gateway guidance '{phrase}' "
                            f"should NOT appear for non-gateway profiles"
                        )

    def test_regression_catches_unconditional_gateway_message_package(self, capsys, tmp_path, monkeypatch):
        """
        Same regression check but for the package entrypoint.
        """
        from agentic_fieldbook.plugin import _cmd_setup

        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_hermes.tools = None
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_PROFILE", "worker")

        # Simulate a profile WITHOUT gateway configuration
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Profile: worker\nModel: quick-tasks"

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("subprocess.run", return_value=mock_result):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    mock_doctor.return_value = 0
                    _cmd_setup(Namespace(yes=True))
                    captured = capsys.readouterr()

                    gateway_action_phrases = [
                        "restart the gateway",
                        "start the gateway",
                        "hermes gateway restart",
                        "hermes gateway start",
                    ]
                    for phrase in gateway_action_phrases:
                        assert phrase not in captured.out.lower(), (
                            f"REGRESSION DETECTED: Gateway guidance '{phrase}' "
                            f"should NOT appear for non-gateway profiles"
                        )