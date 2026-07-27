"""
Regression test for repo-root plugin layout required by `hermes plugins install`.

Hermes clones the repo into ~/.hermes/plugins/<name>/ and requires both
``plugin.yaml`` and a ``register(ctx)`` callable at the *installed* root.
This test asserts that layout so a future refactor does not silently break
remote installation again.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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
