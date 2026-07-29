"""Contract command for discovering test runner commands in workspaces."""

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


CAPABILITY_APPROVAL_REQUIRED_FIELDS = (
    "broker_type", "broker_endpoint", "lease_ttl", "operation_limit",
    "contract_digest", "verification_method", "target_immutable",
    "approval_channel", "target", "capability", "parameters",
    "approval_binding",
)


def _valid_target_identity(value: Any) -> bool:
    """Accept only concrete, non-empty target identity values."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if type(value) is int:
        return value >= 1
    if isinstance(value, Mapping):
        return bool(value) and all(
            isinstance(key, str) and key.strip() and _valid_target_identity(member)
            for key, member in value.items()
        )
    return False


def validate_capability_approval(contract: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors for a capability-approval contract.

    The domain YAML is a descriptive template; this function validates actual
    runtime contract data and therefore never treats its example defaults as
    proof that a contract is safe.
    """
    errors: list[str] = []
    for field in CAPABILITY_APPROVAL_REQUIRED_FIELDS:
        if field not in contract or contract[field] is None or contract[field] == "":
            errors.append(f"missing required field: {field}")

    if "lease_ttl" in contract:
        if type(contract["lease_ttl"]) is not int or contract["lease_ttl"] < 1:
            errors.append("lease_ttl must be an integer >= 1")
    if "operation_limit" in contract:
        if type(contract["operation_limit"]) is not int or contract["operation_limit"] < 1:
            errors.append("operation_limit must be an integer >= 1")
    if "target_immutable" in contract and contract["target_immutable"] is not True:
        errors.append("target_immutable must be true for capability-approval contracts")

    for field in ("broker_type", "broker_endpoint", "verification_method", "approval_channel",
                  "capability"):
        if field in contract and (not isinstance(contract[field], str) or not contract[field].strip()):
            errors.append(f"{field} must be a non-empty string")
    if "target" in contract and not _valid_target_identity(contract["target"]):
        errors.append("target must contain non-empty identity values")
    digest = contract.get("contract_digest")
    if "contract_digest" in contract and (
            not isinstance(digest, str) or
            not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
        errors.append("contract_digest must be a sha256:<64 hex characters> digest")
    if "parameters" in contract and not isinstance(contract["parameters"], Mapping):
        errors.append("parameters must be a mapping")

    binding = contract.get("approval_binding")
    if "approval_binding" in contract and not isinstance(binding, Mapping):
        errors.append("approval_binding must map contract_digest, target, capability, and parameters")
    elif isinstance(binding, Mapping):
        for field in ("contract_digest", "target", "capability", "parameters"):
            if field not in binding:
                errors.append(f"approval_binding missing field: {field}")
            elif field in contract and binding[field] != contract[field]:
                errors.append(f"approval_binding mismatch: {field}")
    return errors


def check_capability_approval(path: str) -> int:
    """Validate a YAML capability-approval contract and print named failures."""
    contract_path = Path(path)
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: cannot load capability-approval contract {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("ERROR: capability-approval contract must be a YAML mapping", file=sys.stderr)
        return 1
    errors = validate_capability_approval(data)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"Capability-approval contract valid: {path}")
    return 0


def _get_git_common_dir(workspace: Path) -> Optional[Path]:
    """Get the git common directory for a workspace.

    Returns the parent checkout root for git worktrees, or None if not a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        common_dir = result.stdout.strip()
        # The common dir is inside .git, so we need to get its parent
        # For a worktree, common_dir might be like: /path/to/main/.git/worktrees/<name>
        # The main repo root is the parent of the .git directory
        git_dir = Path(common_dir)
        if git_dir.name == ".git":
            # Main checkout: .git is the common dir
            return git_dir.parent
        elif git_dir.parent.name == "worktrees":
            # Worktree: common dir is .git/worktrees/<name>
            # Go up 4 levels: worktrees/<name>/../.. -> main/.git -> main
            return git_dir.parent.parent.parent.parent
        else:
            # Unexpected structure, try to find .git parent
            current = git_dir
            for _ in range(5):  # Limit depth
                parent = current.parent
                if (parent / ".git").exists():
                    return parent
                current = parent
            return None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _detect_venv(workspace: Path) -> Optional[Path]:
    """Detect Python venv in workspace or parent checkout.

    Returns path to python executable if found, None otherwise.
    """
    # Check workspace itself
    venv_python = workspace / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python

    # Check parent checkout (for worktrees)
    common_dir = _get_git_common_dir(workspace)
    if common_dir:
        parent_venv = common_dir / ".venv" / "bin" / "python"
        if parent_venv.exists():
            return parent_venv

    return None


def _has_pytest_config(workspace: Path) -> bool:
    """Check if workspace has pytest configuration."""
    pyproject = workspace / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            # Look for pytest in [tool.pytest] or [pytest] sections
            return "[tool.pytest" in content or "[pytest]" in content
        except (OSError, UnicodeDecodeError):
            return False
    return False


def discover_test_command(workspace: str) -> tuple[int, str]:
    """Discover the test command for a given workspace.

    Args:
        workspace: Path to the workspace directory.

    Returns:
        Tuple of (exit_code, command_or_error_message).
        Exit code 0 means a command was found, 1 means no environment detected.
    """
    workspace_path = Path(workspace).resolve()

    if not workspace_path.exists():
        return 1, f"ERROR: Workspace path does not exist: {workspace}"

    if not workspace_path.is_dir():
        return 1, f"ERROR: Workspace path is not a directory: {workspace}"

    # 1. Check for .venv in workspace or parent
    venv_python = _detect_venv(workspace_path)
    if venv_python:
        # Check if it's from parent checkout
        common_dir = _get_git_common_dir(workspace_path)
        if common_dir and common_dir != workspace_path:
            # Venv is in parent checkout
            return 0, f"{venv_python} -m pytest"
        else:
            # Venv is in workspace itself
            return 0, f"{venv_python} -m pytest"

    # 2. Check for uv.lock
    if (workspace_path / "uv.lock").exists():
        return 0, "uv run pytest"

    # 3. Check for tox.ini
    if (workspace_path / "tox.ini").exists():
        return 0, "tox"

    # 4. Check for pyproject.toml with pytest config
    if _has_pytest_config(workspace_path):
        return 0, "python3 -m pytest"

    # 5. No environment found
    return 1, (
        "No Python environment detected; install dependencies before testing\n"
        "Detected environment options (in order):\n"
        "  - .venv/bin/python in workspace or parent checkout\n"
        "  - uv.lock (for 'uv run pytest')\n"
        "  - tox.ini (for 'tox')\n"
        "  - pyproject.toml with pytest config (for 'python3 -m pytest')\n"
    )


def check_contract(workspace: str) -> int:
    """Check and print the test command for a workspace.

    Args:
        workspace: Path to the workspace directory.

    Returns:
        0 if command found, 1 if no environment detected.
    """
    exit_code, message = discover_test_command(workspace)

    if exit_code == 0:
        print(message)
    else:
        print(message, file=sys.stderr)

    return exit_code