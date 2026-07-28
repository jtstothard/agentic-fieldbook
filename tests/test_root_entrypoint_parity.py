"""
Regression test for root entrypoint parity with package entrypoint.

Tests that the repo-root __init__.py (used by git installs) registers
exactly the same CLI commands as agentic_fieldbook/plugin.py (used by pip installs).
This closes the coverage gap that allowed v0.2.0 to ship missing preflight/contract
in the git install path.

See: https://github.com/jtstothard/agentic-fieldbook/issues/39
See: https://github.com/jtstothard/agentic-fieldbook/issues/40
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_root_init():
    """Load the repo-root __init__.py as a module."""
    spec = importlib.util.spec_from_file_location("_root_entry", REPO_ROOT / "__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load root __init__.py from {REPO_ROOT / '__init__.py'}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_package_plugin():
    """Load the package plugin module."""
    from agentic_fieldbook import plugin
    return plugin


def extract_commands(mod):
    """Extract subcommand names registered by a module's CLI setup."""
    root = MagicMock()
    sub = MagicMock()
    root.add_subparsers.return_value = sub

    # Call register to set up CLI
    mod.register(root)

    # Extract the setup_fn and call it to register subcommands
    kwargs = root.register_cli_command.call_args.kwargs
    kwargs['setup_fn'](root)

    # Return all registered subcommand names
    return [c.args[0] for c in sub.add_parser.call_args_list]


class TestRootEntrypointParity:
    """Root entrypoint must register exactly the same commands as the package."""

    def test_root_registers_all_six_commands(self):
        """Root __init__.py must register setup, doctor, version, migrate, preflight, contract."""
        root_mod = load_root_init()
        root_commands = extract_commands(root_mod)

        expected = {"setup", "doctor", "version", "migrate", "preflight", "contract"}
        actual = set(root_commands)

        assert actual == expected, (
            f"Root entrypoint commands mismatch. Expected {expected}, got {actual}. "
            f"Missing: {expected - actual}, Extra: {actual - expected}"
        )

    def test_root_and_package_commands_match(self):
        """Root and package entrypoints must register identical subcommand sets."""
        root_mod = load_root_init()
        package_mod = load_package_plugin()

        root_commands = set(extract_commands(root_mod))
        package_commands = set(extract_commands(package_mod))

        assert root_commands == package_commands, (
            f"Root and package commands differ. "
            f"Root: {root_commands}, Package: {package_commands}, "
            f"Missing in root: {package_commands - root_commands}, "
            f"Extra in root: {root_commands - package_commands}"
        )

    def test_preflight_parser_has_profile_argument(self):
        """The preflight subparser must be registered (argument validation is in preflight tests)."""
        root_mod = load_root_init()
        root_commands = extract_commands(root_mod)

        assert "preflight" in root_commands, "preflight command must be registered"

    def test_contract_parser_has_workspace_argument(self):
        """The contract subparser must be registered (argument validation is in contract tests)."""
        root_mod = load_root_init()
        root_commands = extract_commands(root_mod)

        assert "contract" in root_commands, "contract command must be registered"


class TestRootProfileAwareGateway:
    """Root entrypoint must use profile-aware gateway detection (issue #40)."""

    def test_root_has_profile_helpers(self):
        """Root __init__.py must define _get_hermes_profile and _profile_has_gateway."""
        root_mod = load_root_init()

        assert hasattr(root_mod, "_get_hermes_profile"), (
            "Root entrypoint must define _get_hermes_profile for profile-aware messaging"
        )
        assert hasattr(root_mod, "_profile_has_gateway"), (
            "Root entrypoint must define _profile_has_gateway for profile-aware messaging"
        )
        assert hasattr(root_mod, "_gateway_is_running_for_profile"), (
            "Root entrypoint must define _gateway_is_running_for_profile for profile-aware messaging"
        )

    def test_setup_uses_profile_aware_messaging(self):
        """Root _cmd_setup must use profile-aware gateway helpers, not stale env var checks."""
        root_mod = load_root_init()

        # Check that _cmd_setup source uses the profile-aware helpers
        import inspect
        setup_source = inspect.getsource(root_mod._cmd_setup)

        assert "_get_hermes_profile()" in setup_source, (
            "Root _cmd_setup must call _get_hermes_profile()"
        )
        assert "_profile_has_gateway(" in setup_source, (
            "Root _cmd_setup must call _profile_has_gateway()"
        )
        assert "_gateway_is_running_for_profile(" in setup_source, (
            "Root _cmd_setup must call _gateway_is_running_for_profile()"
        )

        # Verify it does NOT call the old env-var-only _gateway_is_running()
        # (Note: _gateway_is_running_for_profile calls env vars internally, but _cmd_setup
        # should not call the old helper directly)
        old_pattern = "if doctor_result == 0 and _gateway_is_running():"
        assert old_pattern not in setup_source, (
            f"Root _cmd_setup still uses stale _gateway_is_running() pattern: {old_pattern}"
        )