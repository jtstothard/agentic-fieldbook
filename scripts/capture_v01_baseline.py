#!/usr/bin/env python3
"""
Capture v0.1.0 regression baseline.

Usage:
    python3 scripts/capture_v01_baseline.py

This script:
1. Captures all v0.1.0 external behavior
2. Saves it to tests/.v01_baseline/
3. Produces a summary report

Must be run from the v0.1.0 tag.
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

# Try to import preflight, but handle if it doesn't exist (v0.1.0)
try:
    from agentic_fieldbook.plugin import _cmd_preflight
    _PREFLIGHT_EXISTS = True
except ImportError:
    _PREFLIGHT_EXISTS = False


def read_file_hash(path: Path) -> str:
    """Return SHA256 hash of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_file_content(path: Path) -> str:
    """Return file content as string."""
    return path.read_text(encoding="utf-8")


def capture_command_output(cmd_func, args: Namespace = None) -> dict:
    """Capture stdout/stderr and return code from a command function."""
    from io import StringIO
    import contextlib

    if args is None:
        args = Namespace()

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
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HERMES_HOME"] = tmpdir
            commands["preflight"] = capture_command_output(_cmd_preflight, Namespace())

    return commands


def main():
    """Capture and save v0.1.0 baseline."""
    print("Capturing v0.1.0 regression baseline...")

    # Read current version
    version_path = plugin_root / "VERSION"
    current_version = version_path.read_text().strip()
    print(f"Current version: {current_version}")

    if current_version != "0.1.0":
        print(f"WARNING: Current version is {current_version}, not 0.1.0")
        print("This script should be run from the v0.1.0 tag.")
        response = input("Continue anyway? [y/N] ")
        if response.lower() != "y":
            sys.exit(1)

    # Capture all components
    print("\nCapturing plugin metadata...")
    metadata = capture_plugin_metadata()

    print("Capturing skill structure...")
    skills = capture_skill_structure()

    print("Capturing command outputs...")
    commands = capture_all_commands()

    print("Capturing plugin_info()...")
    info = plugin_info()

    # Build baseline dict
    baseline = {
        "version": current_version,
        "metadata": metadata,
        "skills": skills,
        "commands": commands,
        "plugin_info": info,
    }

    # Save baseline
    baseline_dir = plugin_root / "tests" / ".v01_baseline"
    baseline_dir.mkdir(exist_ok=True)

    baseline_file = baseline_dir / "v01_baseline.json"
    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)

    print(f"\nBaseline saved to {baseline_file}")

    # Print summary
    print("\n" + "=" * 60)
    print("BASELINE SUMMARY")
    print("=" * 60)
    print(f"Version: {baseline['version']}")
    print(f"Skills: {len(baseline['skills'])}")
    print(f"Commands: {len(baseline['commands'])}")

    for skill_name, skill_data in baseline["skills"].items():
        n_refs = len(skill_data["references"])
        n_tmpl = len(skill_data["templates"])
        print(f"  - {skill_name}: {n_refs} refs, {n_tmpl} templates")

    print("\nMetadata files:")
    for name, data in baseline["metadata"].items():
        print(f"  - {name}: {data['size']} bytes, SHA256: {data['hash'][:16]}...")

    print("\nCommand return codes:")
    for cmd_name, cmd_data in baseline["commands"].items():
        print(f"  - {cmd_name}: exit code {cmd_data['return_code']}")

    print("\nBaseline capture complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())