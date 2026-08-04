"""
Regression test for repo-root plugin layout required by `hermes plugins install`.

Hermes clones the repo into ~/.hermes/plugins/<name>/ and requires both
``plugin.yaml`` and a ``register(ctx)`` callable at the *installed* root.
This test asserts that layout so a future refactor does not silently break
remote installation again.
"""

import importlib.metadata
import subprocess
import sys
import venv
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPackageEntryPoints:
    """The setup configuration must expose both independently loadable plugins."""

    def test_setup_declares_discoverable_fieldbook_and_hitl_gate_plugins(self, monkeypatch):
        captured = {}
        setuptools = ModuleType("setuptools")
        setattr(setuptools, "find_packages", lambda: [])
        setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))
        monkeypatch.setitem(sys.modules, "setuptools", setuptools)

        runpy = __import__("runpy")
        runpy.run_path(str(REPO_ROOT / "setup.py"))

        entry_points = {
            entry_point.name: entry_point
            for entry_point in (
                importlib.metadata.EntryPoint(name, value, "hermes_agent.plugins")
                for name, value in (
                    item.split(" = ", maxsplit=1)
                    for item in captured["entry_points"]["hermes_agent.plugins"]
                )
            )
        }

        assert set(entry_points) == {"agentic-fieldbook", "hitl-gate"}
        assert entry_points["agentic-fieldbook"].value == "agentic_fieldbook.plugin"
        assert entry_points["hitl-gate"].value == "agentic_fieldbook.plugins.hitl_gate"
        assert callable(entry_points["agentic-fieldbook"].load().register)
        assert callable(entry_points["hitl-gate"].load().register)

    def test_built_distribution_exposes_entry_points_via_metadata(self, tmp_path):
        """Real discovery-path test: build the package and verify entry_points metadata.

        This test exercises the full packaging pipeline by:
        1. Building a wheel into a temporary directory
        2. Installing the wheel into an isolated virtual environment
        3. Querying the real importlib.metadata.entry_points() to confirm both
           'agentic-fieldbook' and 'hitl-gate' are discoverable

        This regression test would catch issues where the source setup.py declares
        entry points but the built/installed distribution does not expose them
        correctly (e.g. missing metadata files, incorrect packaging).
        """
        # Build a wheel into a temporary location
        wheel_dir = tmp_path / "wheel"
        wheel_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        # Find the built wheel
        wheels = list(wheel_dir.glob("*.whl"))
        assert len(wheels) == 1, f"Expected exactly one wheel, found {len(wheels)}"
        wheel_path = wheels[0]

        # Create an isolated virtual environment
        venv_path = tmp_path / "venv"
        venv.create(venv_path, with_pip=True)

        # Determine the python executable in the venv
        if sys.platform == "win32":
            python_exe = str(venv_path / "Scripts" / "python.exe")
        else:
            python_exe = str(venv_path / "bin" / "python")

        # Install the built wheel into the isolated venv
        subprocess.run(
            [python_exe, "-m", "pip", "install", str(wheel_path)],
            check=True,
            capture_output=True,
            text=True,
        )

        # Query entry_points from the built/installed distribution
        # Use the venv's python to import and inspect the package
        inspect_code = """
import importlib.metadata

# Get all entry points for the hermes_agent.plugins group
entry_points_dict = importlib.metadata.entry_points(group="hermes_agent.plugins")

# Convert to a dict by name for easier assertion
# Python 3.8-3.9: .entry_points() returns EntryPoints object (sequence-like)
# Python 3.10+: .entry_points() returns a dict
if isinstance(entry_points_dict, dict):
    eps_by_name = {ep.name: ep for ep in entry_points_dict.values()}
else:
    eps_by_name = {ep.name: ep for ep in entry_points_dict}

# Check both plugins are present
assert 'agentic-fieldbook' in eps_by_name, f"Missing 'agentic-fieldbook' entry point. Found: {list(eps_by_name.keys())}"
assert 'hitl-gate' in eps_by_name, f"Missing 'hitl-gate' entry point. Found: {list(eps_by_name.keys())}"

# Verify the entry point values point to the correct modules
assert eps_by_name['agentic-fieldbook'].value == 'agentic_fieldbook.plugin'
assert eps_by_name['hitl-gate'].value == 'agentic_fieldbook.plugins.hitl_gate'

print("SUCCESS")
"""

        result = subprocess.run(
            [python_exe, "-c", inspect_code],
            check=True,
            capture_output=True,
            text=True,
        )

        assert "SUCCESS" in result.stdout, (
            f"Entry point discovery failed in built distribution.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


class TestInstalledRootLayout:
    """The repo root must itself be a valid Hermes plugin directory."""

    def test_root_plugin_yaml_exists(self):
        """Root-level plugin.yaml must exist for Hermes discovery."""
        assert (REPO_ROOT / "plugin.yaml").exists(), (
            "plugin.yaml must live at repo root for `hermes plugins install` "
            "to discover the plugin (flat layout)."
        )

    def test_root_plugin_yaml_parses(self):
        """Root plugin.yaml must be valid YAML with the expected fields."""
        import yaml

        data = yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text())
        assert data["name"] == "agentic-fieldbook"
        assert data["version"]  # non-empty
        assert data["kind"] == "standalone"

    def test_root_version_matches_manifest(self):
        import yaml
        manifest = yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text())
        assert (REPO_ROOT / "VERSION").read_text().strip() == manifest["version"]

    def test_skills_do_not_claim_independent_versions(self):
        for skill_file in (REPO_ROOT / "skills").glob("*/SKILL.md"):
            frontmatter = skill_file.read_text().split("---", 2)[1]
            assert "\nversion:" not in frontmatter, skill_file

    def test_root_init_exposes_register(self):
        """Root __init__.py must expose a callable register(ctx)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_root_fieldbook_check", REPO_ROOT / "__init__.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "register", None)), (
            "repo-root __init__.py must expose register(ctx) so the Hermes "
            "loader finds it after `plugins install` clones the repo root."
        )

    def test_root_register_calls_through_to_package(self):
        """Root register() must delegate to the real package implementation."""
        from unittest.mock import MagicMock
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_root_fieldbook_check2", REPO_ROOT / "__init__.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mock_ctx = MagicMock()
        mock_ctx.register_cli_command = MagicMock()
        mod.register(mock_ctx)

        mock_ctx.register_cli_command.assert_called_once()
        call_kwargs = mock_ctx.register_cli_command.call_args[1]
        assert call_kwargs["name"] == "aos"

    def test_root_setup_is_real_handler(self, monkeypatch, tmp_path):
        """The Git-installed root entry point must not regress to the setup stub."""
        import importlib.util
        import sys
        from argparse import Namespace
        from unittest.mock import MagicMock

        spec = importlib.util.spec_from_file_location(
            "_root_fieldbook_setup_check", REPO_ROOT / "__init__.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_hermes = MagicMock()
        fake_hermes.__version__ = "0.19.0"
        monkeypatch.setitem(sys.modules, "hermes", fake_hermes)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(mod, "_cmd_doctor", lambda args: 0)

        assert mod._cmd_setup(Namespace(yes=True)) == 0
        content = (tmp_path / "SOUL.md").read_text()
        assert "<!-- aos:begin -->" in content
        assert "<!-- aos:end -->" in content

    def test_root_migrate_is_clean_noop(self, capsys):
        """The Git-installed root entry point exposes the v0.1 migration no-op."""
        import importlib.util
        from argparse import Namespace

        spec = importlib.util.spec_from_file_location(
            "_root_fieldbook_migrate_check", REPO_ROOT / "__init__.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod._cmd_migrate(Namespace()) == 0
        assert "migrate: no changes needed" in capsys.readouterr().out

    def test_root_doctor_reports_detected_installed_bundle_version(self, tmp_path, capsys):
        """Doctor must report VERSION from the installed bundle root, not source metadata."""
        import importlib.util
        from argparse import Namespace
        import shutil

        installed_root = tmp_path / "plugin"
        shutil.copytree(REPO_ROOT, installed_root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (installed_root / "VERSION").write_text("9.9.9\n", encoding="utf-8")

        spec = importlib.util.spec_from_file_location(
            "_root_fieldbook_detected_version_check", REPO_ROOT / "__init__.py"
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod._cmd_doctor(Namespace(plugin_root=str(installed_root))) == 0
        assert "Agentic Fieldbook v9.9.9 doctor" in capsys.readouterr().out
