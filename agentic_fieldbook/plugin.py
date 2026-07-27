"""
Agentic Fieldbook v0.1 Hermes plugin.

Provides userland commands for setup, doctor, and versioned bundle management.
Stub implementations in v0.1; full runtime verification and calibration artifacts
are deferred to later tickets.

This plugin is userland: it adds commands but does not load skills in v0.1 pending
Hermes plugin APIs confirmation.
"""

import sys
import re
from typing import Any

PLUGIN_NAME = "agentic-fieldbook"
PLUGIN_VERSION = "0.1.0"
HERMES_COMPATIBILITY = {"min": "0.18.0", "max": "0.20.0"}


def _parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a version string like '0.18.0' into (0, 18, 0)."""
    parts = version_str.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version_str}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _check_hermes_version() -> tuple[bool, str]:
    """
    Check if the running Hermes version meets compatibility requirements.

    Returns (is_compatible, error_message).
    """
    try:
        import hermes
        hermes_version_str = getattr(hermes, "__version__", None)
        if not hermes_version_str:
            return False, "Cannot determine Hermes version: __version__ not found"

        hermes_version = _parse_version(hermes_version_str)
        min_version = _parse_version(HERMES_COMPATIBILITY["min"])
        max_version = _parse_version(HERMES_COMPATIBILITY["max"])

        if hermes_version < min_version:
            return (
                False,
                f"Hermes version {hermes_version_str} is below minimum {HERMES_COMPATIBILITY['min']}"
            )
        if hermes_version > max_version:
            return (
                False,
                f"Hermes version {hermes_version_str} exceeds maximum {HERMES_COMPATIBILITY['max']}"
            )
        return True, ""
    except ImportError:
        return False, "Hermes module not found (running outside Hermes?)"
    except Exception as e:
        return False, f"Version check error: {e}"


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

    # setup subcommand (stub with real version check)
    aos_subparsers.add_parser(
        "setup",
        help="Set up Agentic Fieldbook (v0.1: version check only)",
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
    """Setup command with Hermes version check (v0.1)."""
    is_compatible, error_msg = _check_hermes_version()

    if not is_compatible:
        print(f"ERROR: {error_msg}", file=sys.stderr)
        print(
            f"Agentic Fieldbook v{PLUGIN_VERSION} requires Hermes "
            f"{HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}",
            file=sys.stderr
        )
        return 1

    print(f"Agentic Fieldbook v{PLUGIN_VERSION} setup")
    print(f"Compatible with Hermes {HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}")
    print("Full setup implementation will be added in later tickets.")
    print("This stub proves version checking; real installation logic coming soon.")
    return 0


def _cmd_doctor(args: Any) -> int:
    """Stub doctor command (v0.1)."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} doctor — stub")
    print("Full doctor verification will be added in later tickets.")
    print("This stub proves command registration; real checks coming soon.")
    return 0


def _cmd_version(args: Any) -> int:
    """Print bundle version and compatibility range."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION}")
    print(f"Hermes compatibility: {HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}")
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