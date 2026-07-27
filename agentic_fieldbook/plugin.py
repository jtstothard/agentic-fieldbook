"""
Agentic Fieldbook v0.1 Hermes plugin.

Provides userland commands for setup, doctor, and versioned bundle management.
Stub implementations in v0.1; full runtime verification and calibration artifacts
are deferred to later tickets.

This plugin is userland: it adds commands but does not load skills in v0.1 pending
Hermes plugin APIs confirmation.
"""

from typing import Any

PLUGIN_NAME = "agentic-fieldbook"
PLUGIN_VERSION = "0.1.0"
HERMES_COMPATIBILITY = ">=0.18.0"


def register(ctx: Any) -> None:
    """Register plugin commands with Hermes.

    Called once by the plugin loader when the plugin is enabled via
    plugins.enabled in config.yaml.
    """
    # Register the main 'aos' command group
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
    """Set up the 'hermes aos' argument parser structure.

    Called by Hermes during CLI setup to register subcommands.
    """
    aos_subparsers = subparsers.add_subparsers(
        dest="aos_subcommand",
        title="subcommands",
        required=True,
    )

    # setup subcommand (stub)
    aos_subparsers.add_parser(
        "setup",
        help="Set up Agentic Fieldbook (v0.1: stub)",
    )

    # doctor subcommand (stub)
    aos_subparsers.add_parser(
        "doctor",
        help="Verify Agentic Fieldbook installation (v0.1: stub)",
    )

    # version subcommand
    aos_subparsers.add_parser(
        "version",
        help="Show Agentic Fieldbook bundle version",
    )


def _handle_aos_command(args: Any) -> int:
    """Handle 'hermes aos' subcommand execution.

    Called by Hermes when 'hermes aos <subcommand>' is invoked.
    Returns exit code (0 for success, non-zero for errors).
    """
    subcommand = getattr(args, "aos_subcommand", None)

    if subcommand == "setup":
        return _cmd_setup(args)
    elif subcommand == "doctor":
        return _cmd_doctor(args)
    elif subcommand == "version":
        return _cmd_version(args)
    else:
        print(f"Unknown aos subcommand: {subcommand}")
        return 1


def _cmd_setup(args: Any) -> int:
    """Stub setup command (v0.1)."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} setup — stub")
    print("Full setup implementation will be added in later tickets.")
    print("This stub proves command registration; real installation logic coming soon.")
    return 0


def _cmd_doctor(args: Any) -> int:
    """Stub doctor command (v0.1)."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} doctor — stub")
    print("Full doctor verification will be added in later tickets.")
    print("This stub proves command registration; real checks coming soon.")
    return 0


def _cmd_version(args: Any) -> int:
    """Print bundle version."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION}")
    print(f"Hermes compatibility: {HERMES_COMPATIBILITY}")
    return 0


# Metadata for plugin discovery (not used by Hermes plugin loader but useful for tooling)
def plugin_info() -> dict:
    """Return plugin metadata for discovery."""
    return {
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "description": "An operating methodology for autonomous agents — plugin bundle",
        "hermes_compatibility": HERMES_COMPATIBILITY,
        "homepage": "https://github.com/jtstothard/agentic-fieldbook",
    }