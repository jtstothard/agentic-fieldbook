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
