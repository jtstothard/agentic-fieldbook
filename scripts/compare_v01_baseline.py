#!/usr/bin/env python3
"""
Compare current state against v0.1.0 baseline.

Usage:
    python3 scripts/compare_v01_baseline.py

This script:
1. Loads the saved v0.1.0 baseline
2. Captures current state
3. Reports any differences (regressions)

Use this to verify v0.2.0 commits don't break v0.1.0 behavior.
"""

import sys
import os
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

# Add plugin root to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))

from agentic_fieldbook.plugin import (
    _cmd_setup,
    _cmd_doctor,
    _cmd_version,
    _cmd_migrate,
    plugin_info,
)

# Try to import preflight
try:
    from agentic_fieldbook.plugin import _cmd_preflight
    _PREFLIGHT_EXISTS = True
except ImportError:
    _PREFLIGHT_EXISTS = False


def read_file_hash(path: Path) -> str:
    """Return SHA256 hash of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_command_output(cmd_func, args: Namespace = None) -> dict:
    """Capture stdout/stderr and return code from a command function."""
    from io import StringIO
    import contextlib

    if args is None:
        args = Namespace()  # type: ignore[assignment]

    stdout_capture = StringIO()
    stderr_capture = StringIO()

    with contextlib.redirect_stdout(stdout_capture):
        with contextlib.redirect_stderr(stderr_capture):
            result = cmd_func(args)

    return {
        "return_code": result,
        "stdout": stdout_capture.getvalue(),
        "stderr": stderr_capture.getvalue(),
    }


def capture_skill_structure() -> dict:
    """Capture structure and content of all skills."""
    skills_dir = plugin_root / "skills"
    skill_dirs = sorted([d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])
    skills_data = {}

    for skill_dir in skill_dirs:
        skill_name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        references_dir = skill_dir / "references"
        templates_dir = skill_dir / "templates"

        skill_data = {
            "skill_md_hash": read_file_hash(skill_md),
            "references": {},
            "templates": {},
        }

        if references_dir.exists():
            for ref_file in sorted(references_dir.iterdir()):
                if ref_file.is_file():
                    skill_data["references"][ref_file.name] = {
                        "hash": read_file_hash(ref_file),
                        "size": ref_file.stat().st_size,
                    }

        if templates_dir.exists():
            for tmpl_file in sorted(templates_dir.iterdir()):
                if tmpl_file.is_file():
                    skill_data["templates"][tmpl_file.name] = {
                        "hash": read_file_hash(tmpl_file),
                        "size": tmpl_file.stat().st_size,
                    }

        skills_data[skill_name] = skill_data

    return skills_data


def capture_plugin_metadata() -> dict:
    """Capture plugin metadata hashes."""
    metadata = {}

    for name in ["VERSION", "plugin.yaml", "setup.py"]:
        if name == "VERSION":
            path = plugin_root / name
        elif name == "plugin.yaml":
            path = plugin_root / "agentic_fieldbook" / name
        else:
            path = plugin_root / name

        if path.exists():
            metadata[name] = {
                "hash": read_file_hash(path),
                "size": path.stat().st_size,
            }

    return metadata


def capture_all_commands() -> dict:
    """Capture output from all plugin commands."""
    commands = {}

    # Mock Hermes for commands that need it
    mock_hermes = MagicMock()
    mock_hermes.__version__ = "0.19.0"

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["HERMES_HOME"] = tmpdir
        soul_path = Path(tmpdir) / "SOUL.md"
        soul_path.touch()

        with patch.dict("sys.modules", {"hermes": mock_hermes}):
            with patch("agentic_fieldbook.plugin._cmd_doctor") as mock_doctor:
                mock_doctor.return_value = 0
                commands["setup"] = capture_command_output(_cmd_setup, Namespace(yes=True))

    commands["doctor"] = capture_command_output(_cmd_doctor, Namespace())
    commands["version"] = capture_command_output(_cmd_version, Namespace())
    commands["migrate"] = capture_command_output(_cmd_migrate, Namespace())

    if _PREFLIGHT_EXISTS:
        # _cmd_preflight is guaranteed to exist when _PREFLIGHT_EXISTS is True
        assert _cmd_preflight is not None
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HERMES_HOME"] = tmpdir
            commands["preflight"] = capture_command_output(_cmd_preflight, Namespace())

    return commands


def load_baseline() -> dict:
    """Load v0.1.0 baseline from disk."""
    baseline_file = plugin_root / "tests" / ".v01_baseline" / "v01_baseline.json"
    if not baseline_file.exists():
        print(f"ERROR: Baseline file not found: {baseline_file}")
        print("Run 'python3 scripts/capture_v01_baseline.py' from the v0.1.0 tag first.")
        sys.exit(1)

    with open(baseline_file, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_skill_structure(baseline: dict, current: dict) -> bool:
    """Compare skill structure and return True if different."""
    has_regression = False

    # Check for missing skills (regression)
    baseline_skills = set(baseline.keys())
    current_skills = set(current.keys())

    missing_skills = baseline_skills - current_skills
    if missing_skills:
        print(f"REGRESSION: Missing skills: {missing_skills}")
        has_regression = True

    # Check for changed content (regression)
    for skill_name in baseline_skills:
        if skill_name not in current:
            continue

        baseline_skill = baseline[skill_name]
        current_skill = current[skill_name]

        if baseline_skill["skill_md_hash"] != current_skill["skill_md_hash"]:
            print(f"REGRESSION: {skill_name}/SKILL.md content changed")
            has_regression = True

        # Check references
        for ref_name in baseline_skill["references"]:
            if ref_name not in current_skill["references"]:
                print(f"REGRESSION: {skill_name}/references/{ref_name} missing")
                has_regression = True
            elif baseline_skill["references"][ref_name]["hash"] != current_skill["references"][ref_name]["hash"]:
                print(f"REGRESSION: {skill_name}/references/{ref_name} content changed")
                has_regression = True

        # Check templates
        for tmpl_name in baseline_skill["templates"]:
            if tmpl_name not in current_skill["templates"]:
                print(f"REGRESSION: {skill_name}/templates/{tmpl_name} missing")
                has_regression = True
            elif baseline_skill["templates"][tmpl_name]["hash"] != current_skill["templates"][tmpl_name]["hash"]:
                print(f"REGRESSION: {skill_name}/templates/{tmpl_name} content changed")
                has_regression = True

    # New skills are allowed (additive superset)
    new_skills = current_skills - baseline_skills
    if new_skills:
        print(f"NEW SKILLS (allowed): {new_skills}")

    return has_regression


def compare_metadata(baseline: dict, current: dict) -> bool:
    """Compare metadata and return True if different."""
    has_regression = False

    for name in baseline:
        if name not in current:
            print(f"REGRESSION: Metadata file {name} missing")
            has_regression = True
            continue

        baseline_data = baseline[name]
        current_data = current[name]

        # VERSION may change (that's expected)
        if name == "VERSION":
            print(f"  VERSION changed: {baseline_data['hash'][:16]}... -> {current_data['hash'][:16]}... (allowed)")
            continue

        # Other metadata should not change
        if baseline_data["hash"] != current_data["hash"]:
            print(f"REGRESSION: {name} content changed")
            print(f"  Baseline: {baseline_data['hash'][:32]}...")
            print(f"  Current:  {current_data['hash'][:32]}...")
            has_regression = True

    return has_regression


def compare_commands(baseline: dict, current: dict) -> bool:
    """Compare command outputs and return True if different."""
    has_regression = False

    for cmd_name in baseline:
        if cmd_name not in current:
            print(f"REGRESSION: Command {cmd_name} missing")
            has_regression = True
            continue

        baseline_cmd = baseline[cmd_name]
        current_cmd = current[cmd_name]

        # Return code should be the same
        if baseline_cmd["return_code"] != current_cmd["return_code"]:
            print(f"REGRESSION: {cmd_name} return code changed")
            print(f"  Baseline: {baseline_cmd['return_code']}")
            print(f"  Current:  {current_cmd['return_code']}")
            has_regression = True

        # Version-prefixed output is allowed to change (VERSION changes)
        if cmd_name in ["version", "doctor", "migrate"]:
            # Just check return code, content is allowed to change due to version string
            continue

        # For other commands, stdout should be stable
        # Allow temp dir paths in setup output to vary
        if cmd_name == "setup":
            # Normalize temp dir paths in setup output
            import re
            baseline_stdout = re.sub(r'/tmp/[^/]+/', '/tmp/TMPDIR/', baseline_cmd["stdout"])
            current_stdout = re.sub(r'/tmp/[^/]+/', '/tmp/TMPDIR/', current_cmd["stdout"])
            if baseline_stdout != current_stdout:
                print(f"REGRESSION: {cmd_name} stdout changed (ignoring temp dir paths)")
                has_regression = True
        elif baseline_cmd["stdout"] != current_cmd["stdout"]:
            print(f"REGRESSION: {cmd_name} stdout changed")
            has_regression = True

        # Stderr should also be stable
        if baseline_cmd["stderr"] != current_cmd["stderr"]:
            print(f"REGRESSION: {cmd_name} stderr changed")
            has_regression = True

    # New commands are allowed (additive superset)
    new_commands = set(current.keys()) - set(baseline.keys())
    if new_commands:
        print(f"NEW COMMANDS (allowed): {new_commands}")

    return has_regression


def main():
    """Compare current state against v0.1.0 baseline."""
    print("Comparing against v0.1.0 baseline...")

    # Load baseline
    baseline = load_baseline()
    print(f"Loaded baseline version: {baseline['version']}")

    # Capture current state
    print("\nCapturing current state...")
    current_metadata = capture_plugin_metadata()
    current_skills = capture_skill_structure()
    current_commands = capture_all_commands()
    current_info = plugin_info()

    # Compare
    print("\n" + "=" * 60)
    print("REGRESSION CHECK RESULTS")
    print("=" * 60)

    has_regression = False

    print("\nChecking metadata...")
    if compare_metadata(baseline["metadata"], current_metadata):
        has_regression = True
    else:
        print("  OK (VERSION changes are allowed)")

    print("\nChecking skills...")
    if compare_skill_structure(baseline["skills"], current_skills):
        has_regression = True
    else:
        print("  OK")

    print("\nChecking commands...")
    if compare_commands(baseline["commands"], current_commands):
        has_regression = True
    else:
        print("  OK")

    # Summary
    print("\n" + "=" * 60)
    if has_regression:
        print("RESULT: REGRESSION DETECTED")
        print("=" * 60)
        print("\nOne or more v0.1.0 behaviors have changed.")
        print("This violates the additive-superset constraint.")
        return 1
    else:
        print("RESULT: NO REGRESSIONS")
        print("=" * 60)
        print("\nAll v0.1.0 behaviors are preserved.")
        print("v0.2.0 is a valid additive superset.")
        return 0


if __name__ == "__main__":
    sys.exit(main())