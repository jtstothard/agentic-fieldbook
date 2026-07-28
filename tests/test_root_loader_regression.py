"""
Regression test for issue #43: root __init__.py must load under the real
Hermes plugin loader without ModuleNotFoundError.

Hermes loads root __init__.py via importlib.util.spec_from_file_location as
module `hermes_plugins.agentic_fieldbook`. This does NOT add the plugin
directory to sys.path, so `from agentic_fieldbook.plugin import ...` fails
unless __init__.py injects its own directory into sys.path first.

This test reproduces the exact loader conditions: no inherited sys.path
containing the plugin dir, spec-based loading, namespace module name.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_sys_path():
    """Remove the repo root and plugin dirs from sys.path so we test the
    real loader conditions (Hermes does not add them)."""
    original = sys.path[:]
    original_modules = set(sys.modules.keys())
    # Remove any entry that points at the repo root or agentic_fieldbook package
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != REPO_ROOT.resolve()]
    yield
    sys.path[:] = original
    # Clean up any modules we imported during the test
    for mod_name in list(sys.modules.keys() - original_modules):
        del sys.modules[mod_name]


class TestRootEntrypointLoadsUnderHermesLoader:
    """The root __init__.py must load without agentic_fieldbook on sys.path."""

    def test_root_init_imports_without_module_not_found(self):
        """Loading root __init__.py via spec must not raise ModuleNotFoundError.

        This is the exact failure from v0.2.1: the delegation `from
        agentic_fieldbook.plugin import _register_aos_cli` fails because
        Hermes's loader does not put the plugin dir on sys.path.
        """
        plugin_dir = REPO_ROOT
        init_file = plugin_dir / "__init__.py"

        spec = importlib.util.spec_from_file_location(
            "hermes_plugins.agentic_fieldbook",
            init_file,
            submodule_search_locations=[str(plugin_dir)],
        )
        assert spec is not None and spec.loader is not None

        mod = importlib.util.module_from_spec(spec)
        mod.__path__ = [str(plugin_dir)]

        # This must not raise ModuleNotFoundError
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "register", None))

    def test_root_register_wires_all_six_commands(self):
        """After loading via the Hermes loader path, register() must expose
        all six commands (proves the delegation actually works)."""
        plugin_dir = REPO_ROOT
        init_file = plugin_dir / "__init__.py"

        spec = importlib.util.spec_from_file_location(
            "hermes_plugins.agentic_fieldbook_register_test",
            init_file,
            submodule_search_locations=[str(plugin_dir)],
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        mod.__path__ = [str(plugin_dir)]
        spec.loader.exec_module(mod)

        root = MagicMock()
        sub = MagicMock()
        root.add_subparsers.return_value = sub

        mod.register(root)
        kwargs = root.register_cli_command.call_args.kwargs
        kwargs["setup_fn"](root)

        cmds = {c.args[0] for c in sub.add_parser.call_args_list}
        # v0.2 adds map-lanes (T01) and first-pilot (T06) commands
        expected = {"setup", "doctor", "version", "migrate", "preflight", "contract", "map-lanes", "first-pilot"}
        assert cmds == expected, f"Missing: {expected - cmds}, Extra: {cmds - expected}"
