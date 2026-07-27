"""Tests for aos contract test-runner discovery."""

from pathlib import Path
from unittest.mock import patch

from agentic_fieldbook.contract import check_contract, discover_test_command


def test_contract_worktree_venv(tmp_path: Path):
    """A workspace-local venv takes priority."""
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()

    exit_code, command = discover_test_command(str(tmp_path))

    assert exit_code == 0
    assert command == f"{python} -m pytest"


def test_contract_parent_venv(tmp_path: Path):
    """A venv in the git common checkout is used for worktrees."""
    common_root = tmp_path / "main"
    worktree = tmp_path / "worktree"
    common_root.mkdir()
    worktree.mkdir()
    python = common_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()

    with patch("agentic_fieldbook.contract._get_git_common_dir", return_value=common_root):
        exit_code, command = discover_test_command(str(worktree))

    assert exit_code == 0
    assert command == f"{python} -m pytest"


def test_contract_uv_lock(tmp_path: Path):
    """uv.lock selects uv's test runner."""
    (tmp_path / "uv.lock").touch()

    assert discover_test_command(str(tmp_path)) == (0, "uv run pytest")


def test_contract_tox(tmp_path: Path):
    """tox.ini selects tox."""
    (tmp_path / "tox.ini").touch()

    assert discover_test_command(str(tmp_path)) == (0, "tox")


def test_contract_pyproject_pytest_config(tmp_path: Path):
    """Pytest configuration in pyproject selects the system runner."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")

    assert discover_test_command(str(tmp_path)) == (0, "python3 -m pytest")


def test_contract_no_env(tmp_path: Path):
    """A workspace without a supported environment warns and exits 1."""
    exit_code, message = discover_test_command(str(tmp_path))

    assert exit_code == 1
    assert "No Python environment detected; install dependencies before testing" in message


def test_contract_no_env_prints_warning(tmp_path: Path, capsys):
    """The CLI helper writes no-environment diagnostics to stderr."""
    assert check_contract(str(tmp_path)) == 1
    captured = capsys.readouterr()
    assert "No Python environment detected" in captured.err
