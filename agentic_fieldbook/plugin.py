"""
Agentic Fieldbook v0.1 Hermes plugin.

Provides userland commands for setup, doctor, and versioned bundle management.
Stub implementations in v0.1; full runtime verification and calibration artifacts
are deferred to later tickets.

This plugin is userland: it adds commands but does not load skills in v0.1 pending
Hermes plugin APIs confirmation.
"""

import sys
import os
from pathlib import Path
import re
from typing import Any

PLUGIN_NAME = "agentic-fieldbook"
PLUGIN_VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
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
        hermes = _hermes_runtime_module()
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
    setup_parser = aos_subparsers.add_parser(
        "setup",
        help="Set up Agentic Fieldbook",
    )
    setup_parser.add_argument("--yes", action="store_true", help="accept SOUL.md changes")

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
    aos_subparsers.add_parser(
        "migrate",
        help="Apply bundle migrations (v0.1: no-op)",
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
    elif subcommand == "migrate":
        return _cmd_migrate(args)
    else:
        print(f"Unknown aos subcommand: {subcommand}")
        return 1


def _cmd_setup(args: Any) -> int:
    """Activate the bundle after validating the host and obtaining consent."""
    is_compatible, error_msg = _check_hermes_version()

    if not is_compatible:
        print(f"ERROR: {error_msg}", file=sys.stderr)
        print(
            f"Agentic Fieldbook v{PLUGIN_VERSION} requires Hermes "
            f"{HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}",
            file=sys.stderr
        )
        return 1

    try:
        hermes = _hermes_runtime_module()
    except ImportError:
        print("ERROR: Hermes is unavailable; setup must be run from Hermes", file=sys.stderr)
        return 1
    if os.environ.get("AOS_SKILLS_TOOLSET_DISABLED") == "1":
        print("ERROR: Hermes skills toolset is disabled; enable it before setup", file=sys.stderr)
        return 1
    if not _skills_toolset_available(hermes):
        print("ERROR: Hermes skills toolset is unavailable; enable it before setup", file=sys.stderr)
        return 1

    print(f"Agentic Fieldbook v{PLUGIN_VERSION} setup")
    print(f"Compatible with Hermes {HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}")
    soul = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "SOUL.md"
    begin, end = "<!-- aos:begin -->", "<!-- aos:end -->"
    existing = soul.read_text(encoding="utf-8") if soul.exists() else ""
    if begin in existing and end in existing:
        print(f"SOUL.md already contains the managed block: {soul}")
    else:
        if not getattr(args, "yes", False) and not sys.stdin.isatty():
            print("ERROR: setup requires --yes when stdin is not a TTY", file=sys.stderr)
            return 1
        if not getattr(args, "yes", False):
            answer = input("Insert Agentic Fieldbook instructions into SOUL.md? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Setup cancelled; SOUL.md was not modified.")
                return 1
        block = f"{begin}\n\nAgentic Fieldbook skills are available for agent workflows.\n\n{end}\n"
        separator = "\n" if existing and not existing.endswith("\n") else ""
        soul.parent.mkdir(parents=True, exist_ok=True)
        soul.write_text(existing + separator + block, encoding="utf-8")
        print(f"Inserted managed instructions into {soul}")
    print("Running doctor...")
    return _cmd_doctor(args)


def _skills_toolset_available(hermes: Any) -> bool:
    """Best-effort compatibility check for Hermes' skills toolset."""
    tools = getattr(hermes, "tools", None)
    if tools is None:
        return True  # older Hermes exposes tools through the runtime, not module attrs
    enabled = getattr(tools, "skills", None)
    return enabled is not False


def _hermes_runtime_module() -> Any:
    """Return the supported Hermes runtime module across CLI distributions."""
    try:
        import hermes
        return hermes
    except ImportError:
        import hermes_cli
        return hermes_cli


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


def _cmd_migrate(args: Any) -> int:
    """Run bundle migrations; v0.1 intentionally has nothing to migrate."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} migrate: no changes needed")
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