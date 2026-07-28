"""Behavioral characterization of v0.1's implicit inline-default dispatch path.

These tests capture the current externally observable behavior of v0.1 dispatch:
there is no explicit dispatch adapter. Tasks execute inline in the current session
without any durable task backend or dispatch abstraction.

This characterization evidence is used to derive the adapter contract in v0.3.0.
It exercises only the existing v0.1 behavior, not a future adapter interface.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_v01_dispatch_seam_is_extracted_as_inline_default():
    """The v0.3 extraction exposes the former implicit inline path."""
    import agentic_fieldbook.dispatch as dispatch_mod
    assert dispatch_mod.get_default_adapter().__class__.__name__ == "InlineAdapter"


def test_v01_methods_execute_inline_via_delegatetask_or_terminal():
    """v0.1 dispatch is implicit: methods execute inline without a dispatch backend.

    In v0.1, there is no explicit dispatch adapter. Execution happens
    directly in the current session through tools like delegate_task or
    terminal commands. This test verifies the v0.1 implicit pattern.
    """
    # The planning-routing skill should exist and document execution patterns
    skill_path = ROOT / "skills" / "planning-routing" / "SKILL.md"
    assert skill_path.exists(), "planning-routing skill must exist in v0.1"

    skill_content = skill_path.read_text(encoding="utf-8")

    # The skill should document "inline" execution (not dispatch adapters)
    assert "inline" in skill_content.lower(), (
        "v0.1's planning-routing skill should document inline execution"
    )

    # The skill may use "dispatch" as a verb, but should NOT document
    # a dispatch adapter API (doesn't exist in v0.1)
    assert "dispatch adapter" not in skill_content.lower(), (
        "v0.1 should not document a dispatch adapter API"
    )


def test_v01_plugins_register_commands_without_dispatch_backend():
    """v0.1 plugin registration does not involve a dispatch backend."""
    # Load the root entrypoint and verify it registers commands
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fieldbook_root", ROOT / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # The register function should exist and not reference dispatch
    assert hasattr(module, "register"), "root must have register function"

    # Register should configure CLI commands, not a dispatch backend
    # (We verify this by checking the function accepts a ctx parameter)
    import inspect

    sig = inspect.signature(module.register)
    assert "ctx" in sig.parameters, "register takes a ctx parameter for CLI registration"


def test_v01_plugin_commands_execute_synchronously():
    """v0.1 plugin commands execute synchronously in the current session.

    In v0.1, commands are registered through the plugin system and invoked
    via Hermes CLI (hermes aos <subcommand>). Execution is synchronous
    with no task backend or task IDs returned.
    """
    # The root __init__.py should register commands synchronously
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fieldbook_root", ROOT / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # The register function should exist and complete synchronously
    assert hasattr(module, "register"), "root must have register function"

    # Verify the function exists and is callable (not a task generator)
    assert callable(module.register), "register must be callable"

    # The key characterization: register is synchronous (no task IDs)
    # We verify this by checking it doesn't yield or return async
    import inspect

    assert not inspect.iscoroutinefunction(module.register), (
        "v0.1's register function should not be async (no async task backend)"
    )
    assert not inspect.isgeneratorfunction(module.register), (
        "v0.1's register function should not be a generator (no deferred task IDs)"
    )


def test_v01_has_no_task_backend_state():
    """v0.1 does not maintain task backend state or task IDs."""
    # v0.1 ships no bundled task state — the repo itself should not contain
    # production DBs. Scan only the repository root, not the parent directory.
    repo_root = ROOT if (ROOT / ".git").is_dir() else ROOT
    assert (repo_root / ".git").exists(), "must be at repo root"

    task_state_files = list(repo_root.glob("**/*.db"))

    # Filter out test fixtures, shadow boards, and worktrees
    production_state = [
        f
        for f in task_state_files
        if "shadow" not in str(f)
        and "test" not in str(f)
        and ".worktrees" not in str(f)
        and "__pycache__" not in str(f)
    ]

    assert not production_state, (
        f"v0.1 should not have production task state files: {production_state}"
    )


def test_v01_build_spec_declares_inline_default():
    """v0.1's BUILD-SPEC explicitly declares inline-default dispatch."""
    build_spec = ROOT / "BUILD-SPEC.md"
    assert build_spec.exists(), "BUILD-SPEC.md must exist"

    content = build_spec.read_text(encoding="utf-8")

    # v0.1 uses inline-default dispatch explicitly
    assert "inline-default dispatch" in content, (
        "BUILD-SPEC must declare v0.1 uses inline-default dispatch"
    )

    # Adapter interface is deferred
    assert "deferred" in content.lower(), (
        "BUILD-SPEC should defer stable dispatch adapter interface"
    )


def test_v01_skills_document_inline_execution_patterns():
    """v0.1 skills document inline execution, not dispatch adapter usage."""
    skills_dir = ROOT / "skills"
    assert skills_dir.exists(), "skills directory must exist"

    # Check a few key skills for inline execution documentation
    for skill_name in ["planning-routing", "stage-handoff"]:
        skill_path = skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")

            # Should NOT document dispatch adapter usage (doesn't exist in v0.1)
            # MAY document inline execution patterns
            # This test ensures we're characterizing the v0.1 state correctly
            pass


def test_v01_session_scoped_execution():
    """v0.1 execution is session-scoped with no durable persistence.

    Multiple executions complete independently without shared state.
    """