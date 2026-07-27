"""Agentic Fieldbook — repo-root plugin entry point for Hermes Git-install.

Hermes's ``plugins install`` clones this repository into
``~/.hermes/plugins/<name>/`` and loads the installed directory root as the
plugin module. The loader does **not** put the plugin directory itself on
``sys.path``, so a sibling package (``agentic_fieldbook/``) is not importable
from the root ``__init__.py``. Therefore ``register(ctx)`` and its helpers are
defined here directly (self-contained), and the ``agentic_fieldbook`` package
remains available for tests and pip installs.
"""

from typing import Any

PLUGIN_NAME = "agentic-fieldbook"
PLUGIN_VERSION = "0.1.0"
HERMES_COMPATIBILITY = ">=0.18.0"

__version__ = PLUGIN_VERSION


def register(ctx: Any) -> None:
    """Register the ``hermes aos`` command group with Hermes.

    Called once by the plugin loader when the plugin is enabled via
    ``plugins.enabled`` in config.yaml.
    """
    ctx.register_cli_command(
        name="aos",
        help="Agentic Fieldbook commands (v0.1 stub)",
        setup_fn=_register_aos_cli,
        handler_fn=_handle_aos_command,
        description=(
            "Agentic Fieldbook v0.1 — setup, doctor, and version commands. "
            "Stub implementations; full functionality in later tickets."
        ),
    )


def _register_aos_cli(subparsers: Any) -> None:
    """Set up the ``hermes aos`` argument parser structure."""
    aos_subparsers = subparsers.add_subparsers(
        dest="aos_subcommand",
        title="subcommands",
        required=True,
    )
    aos_subparsers.add_parser("setup", help="Set up Agentic Fieldbook (v0.1: stub)")
    aos_subparsers.add_parser("doctor", help="Verify Agentic Fieldbook installation (v0.1: stub)")
    aos_subparsers.add_parser("version", help="Show Agentic Fieldbook bundle version")


def _handle_aos_command(args: Any) -> int:
    """Dispatch ``hermes aos <subcommand>``."""
    subcommand = getattr(args, "aos_subcommand", None)
    if subcommand == "setup":
        return _cmd_setup(args)
    if subcommand == "doctor":
        return _cmd_doctor(args)
    if subcommand == "version":
        return _cmd_version(args)
    print(f"Unknown aos subcommand: {subcommand}")
    return 1


def _cmd_setup(args: Any) -> int:
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} setup — stub")
    print("Full setup implementation will be added in later tickets.")
    print("This stub proves command registration; real installation logic coming soon.")
    return 0


def _cmd_doctor(args: Any) -> int:
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} doctor — stub")
    print("Full doctor verification will be added in later tickets.")
    print("This stub proves command registration; real checks coming soon.")
    return 0


def _cmd_version(args: Any) -> int:
    print(f"Agentic Fieldbook v{PLUGIN_VERSION}")
    print(f"Hermes compatibility: {HERMES_COMPATIBILITY}")
    return 0


__all__ = ["register", "__version__"]
