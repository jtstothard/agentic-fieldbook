"""
Integration tests for setup command prereqs, consent, idempotency, and doctor invocation.

These tests use temp HERMES_HOME to avoid affecting the real installation.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace
import pytest

# Add the plugin to the path
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

from agentic_fieldbook.plugin import (
    _cmd_setup,
    _check_hermes_version,
    _skills_toolset_available,
)


class TestSetupPrerequisites:
    """Test that setup checks Hermes and skills toolset availability."""

    def test_hermes_unavailable_fails(self, capsys, monkeypatch):
        """Setup should fail fast when Hermes is unavailable."""
        # Mock version check to pass, then mock hermes import to fail
        with patch("agentic_fieldbook.plugin._check_hermes_version") as mock_check:
            mock_check.return_value = (True, "")
            # Remove hermes from sys.modules to simulate unavailability
            monkeypatch.delenv("HERMES_HOME", raising=False)
            result = _cmd_setup(Namespace())
            captured = capsys.readouterr()
            assert result != 0
            assert "ERROR: Hermes is unavailable" in captured.err

    def test_skills_toolset_disabled_fails(self, capsys, monkeypatch):
        """Setup should fail when AOS_SKILLS_TOOLSET_DISABLED=1."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("AOS_SKILLS_TOOLSET_DISABLED", "1")
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            result = _cmd_setup(Namespace())
            captured = capsys.readouterr()
            assert result != 0
            assert "ERROR: Hermes skills toolset is disabled" in captured.err

    def test_skills_toolset_unavailable_fails(self, capsys, monkeypatch):
        """Setup should fail when skills toolset is marked unavailable."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        mock_tools = MagicMock()
        mock_tools.skills = False
        mock_hermes.tools = mock_tools
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            result = _cmd_setup(Namespace())
            captured = capsys.readouterr()
            assert result != 0
            assert "ERROR: Hermes skills toolset is unavailable" in captured.err


class TestConsentAndIdempotency:
    """Test SOUL.md insertion consent gating and idempotent re-runs."""

    def test_requires_yes_flag_when_not_tty(self, capsys, tmp_path, monkeypatch):
        """Setup should require --yes when stdin is not a TTY."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("sys.stdin.isatty", return_value=False):
                result = _cmd_setup(Namespace(yes=False))
                captured = capsys.readouterr()
                assert result != 0
                assert "ERROR: setup requires --yes" in captured.err

    def test_inserts_block_with_yes_flag(self, capsys, tmp_path, monkeypatch):
        """Setup should insert block when --yes is passed."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result == 0
                assert "Inserted managed instructions" in captured.out
                soul = tmp_path / "SOUL.md"
                assert soul.exists()
                content = soul.read_text()
                assert "<!-- aos:begin -->" in content
                assert "<!-- aos:end -->" in content
                assert "Agentic Fieldbook skills are available" in content

    def test_idempotent_rerun_skips_insertion(self, capsys, tmp_path, monkeypatch):
        """Running setup twice should not duplicate the block."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                # First run
                result1 = _cmd_setup(Namespace(yes=True))
                assert result1 == 0
                soul = tmp_path / "SOUL.md"
                first_content = soul.read_text()
                # Second run
                result2 = _cmd_setup(Namespace(yes=True))
                captured = capsys.readouterr()
                assert result2 == 0
                assert "SOUL.md already contains the managed block" in captured.out
                second_content = soul.read_text()
                assert first_content == second_content
                # Only one block marker pair
                assert second_content.count("<!-- aos:begin -->") == 1
                assert second_content.count("<!-- aos:end -->") == 1

    def test_respects_existing_soul_content(self, capsys, tmp_path, monkeypatch):
        """Setup should preserve existing SOUL.md content."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        existing_soul = tmp_path / "SOUL.md"
        existing_soul.write_text("# My Operating Instructions\n\nBe helpful.\n")
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                assert result == 0
                content = existing_soul.read_text()
                assert "# My Operating Instructions" in content
                assert "Be helpful." in content
                assert "<!-- aos:begin -->" in content
                assert "<!-- aos:end -->" in content

    def test_creates_hermes_home_if_missing(self, capsys, tmp_path, monkeypatch):
        """Setup should create HERMES_HOME directory if it doesn't exist."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        hermes_home = tmp_path / "nonexistent" / "hermes"
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                assert result == 0
                assert hermes_home.exists()
                soul = hermes_home / "SOUL.md"
                assert soul.exists()


class TestDoctorInvocation:
    """Test that setup automatically runs doctor after successful activation."""

    def test_doctor_called_after_successful_setup(self, tmp_path, monkeypatch):
        """Setup should invoke doctor after SOUL.md insertion."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                result = _cmd_setup(Namespace(yes=True))
                assert result == 0
                assert mock_doctor.called

    def test_setup_returns_doctor_exit_code(self, tmp_path, monkeypatch):
        """Setup should return doctor's exit code."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 1  # Doctor fails
                result = _cmd_setup(Namespace(yes=True))
                assert result == 1

    def test_doctor_not_called_on_cancelled_consent(self, tmp_path, monkeypatch):
        """Doctor should not be called if user cancels consent."""
        mock_hermes = MagicMock()
        mock_hermes.__version__ = "0.19.0"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("builtins.input", return_value="n"):
                with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                    result = _cmd_setup(Namespace(yes=False))
                    assert result != 0
                    assert not mock_doctor.called


class TestSkillsToolsetCheck:
    """Test _skills_toolset_available helper."""

    def test_returns_true_when_tools_attr_missing(self):
        """Should return True when hermes.tools is None (older Hermes)."""
        mock_hermes = MagicMock(spec=["__version__"])
        assert _skills_toolset_available(mock_hermes) is True

    def test_returns_true_when_tools_skills_not_false(self):
        """Should return True when tools.skills is not explicitly False."""
        mock_hermes = MagicMock()
        mock_tools = MagicMock()
        mock_tools.skills = True
        mock_hermes.tools = mock_tools
        assert _skills_toolset_available(mock_hermes) is True

    def test_returns_false_when_tools_skills_is_false(self):
        """Should return False when tools.skills is False."""
        mock_hermes = MagicMock()
        mock_tools = MagicMock()
        mock_tools.skills = False
        mock_hermes.tools = mock_tools
        assert _skills_toolset_available(mock_hermes) is False

    def test_returns_true_when_tools_skills_is_none(self):
        """Should return True when tools.skills is None."""
        mock_hermes = MagicMock()
        mock_tools = MagicMock()
        mock_tools.skills = None
        mock_hermes.tools = mock_tools
        assert _skills_toolset_available(mock_hermes) is True