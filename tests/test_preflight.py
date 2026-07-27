"""Tests for aos preflight command."""

import subprocess
from unittest.mock import patch, MagicMock
import pytest

from agentic_fieldbook.preflight import check_preflight, FIELDBOOK_SKILLS


class TestPreflightAllPresent:
    def test_all_present_exit_code(self):
        """When all 7 Fieldbook skills are present, exit code is 0."""
        mock_output = (
            "                                Installed Skills                                \n"
            "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓\n"
            "┃ Name                 ┃ Category            ┃ Source    ┃ Trust     ┃ Status  ┃\n"
            "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩\n"
        )
        for skill in FIELDBOOK_SKILLS:
            mock_output += f"│ {skill:<20} │ fieldbook           │ plugin    │ local     │ enabled │\n"
        mock_output += "└──────────────────────┴─────────────────────┴───────────┴───────────┴─────────┘\n"

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = mock_output
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            exit_code = check_preflight("test-profile")
            assert exit_code == 0
            mock_run.assert_called_once_with(
                ["hermes", "--profile", "test-profile", "skills", "list"],
                capture_output=True,
                text=True,
                check=True,
            )

    def test_all_present_output(self, capsys):
        """When all skills present, success message is printed."""
        mock_output = (
            "                                Installed Skills                                \n"
            "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓\n"
            "┃ Name                 ┃ Category            ┃ Source    ┃ Trust     ┃ Status  ┃\n"
            "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩\n"
        )
        for skill in FIELDBOOK_SKILLS:
            mock_output += f"│ {skill:<20} │ fieldbook           │ plugin    │ local     │ enabled │\n"
        mock_output += "└──────────────────────┴─────────────────────┴───────────┴───────────┴─────────┘\n"

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = mock_output
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            check_preflight("test-profile")
            captured = capsys.readouterr()
            assert "✓ All 7 Fieldbook skills available on profile 'test-profile'" in captured.out


class TestPreflightMissing:
    def test_missing_skills_exit_code(self):
        """When some skills are missing, exit code is 1."""
        # Only include 3 of 7 skills
        mock_output = (
            "                                Installed Skills                                \n"
            "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓\n"
            "┃ Name                 ┃ Category            ┃ Source    ┃ Trust     ┃ Status  ┃\n"
            "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩\n"
        )
        present_skills = FIELDBOOK_SKILLS[:3]
        for skill in present_skills:
            mock_output += f"│ {skill:<20} │ fieldbook           │ plugin    │ local     │ enabled │\n"
        mock_output += "└──────────────────────┴─────────────────────┴───────────┴───────────┴─────────┘\n"

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = mock_output
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            exit_code = check_preflight("test-profile")
            assert exit_code == 1

    def test_missing_skills_diagnostic(self, capsys):
        """When skills are missing, diagnostic names them clearly."""
        # Only include 2 of 7 skills
        mock_output = (
            "                                Installed Skills                                \n"
            "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓\n"
            "┃ Name                 ┃ Category            ┃ Source    ┃ Trust     ┃ Status  ┃\n"
            "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩\n"
        )
        present_skills = FIELDBOOK_SKILLS[:2]
        for skill in present_skills:
            mock_output += f"│ {skill:<20} │ fieldbook           │ plugin    │ local     │ enabled │\n"
        mock_output += "└──────────────────────┴─────────────────────┴───────────┴───────────┴─────────┘\n"

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = mock_output
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            check_preflight("test-profile")
            captured = capsys.readouterr()

            # Check that missing skills are named
            missing_skills = set(FIELDBOOK_SKILLS) - set(present_skills)
            for skill in missing_skills:
                assert skill in captured.err

            # Check actionable suggestion is present
            assert "Install the agentic-fieldbook plugin" in captured.err
            assert "remove the forced skill from the kanban card" in captured.err

    def test_all_missing_skills(self, capsys):
        """When all skills are missing, all 7 are reported."""
        mock_output = (
            "                                Installed Skills                                \n"
            "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓\n"
            "┃ Name                 ┃ Category            ┃ Source    ┃ Trust     ┃ Status  ┃\n"
            "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩\n"
            "│ other-skill          │ other               │ builtin   │ builtin   │ enabled │\n"
            "└──────────────────────┴─────────────────────┴───────────┴───────────┴─────────┘\n"
        )

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = mock_output
            mock_result.returncode = 0
            mock_run.return_value = mock_result

            exit_code = check_preflight("test-profile")
            assert exit_code == 1

            # Check that all 7 skills are reported as missing
            captured = capsys.readouterr()
            for skill in FIELDBOOK_SKILLS:
                assert skill in captured.err


class TestPreflightProfileNotFound:
    def test_profile_not_found_exits_1(self):
        """When profile doesn't exist, exit code is 1."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["hermes", "--profile", "nonexistent", "skills", "list"],
                stderr="Profile 'nonexistent' not found",
            )

            exit_code = check_preflight("nonexistent")
            assert exit_code == 1

    def test_profile_not_found_diagnostic(self, capsys):
        """When profile doesn't exist, clear error message is shown."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["hermes", "--profile", "nonexistent", "skills", "list"],
                stderr="Profile 'nonexistent' not found",
            )

            check_preflight("nonexistent")
            captured = capsys.readouterr()
            assert "Profile 'nonexistent' not found" in captured.err

    def test_hermes_command_not_found(self, capsys):
        """When hermes CLI is not available, clear error is shown."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            exit_code = check_preflight("test-profile")
            assert exit_code == 1

            captured = capsys.readouterr()
            assert "hermes command not found" in captured.err