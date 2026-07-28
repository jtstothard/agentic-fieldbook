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
import subprocess
from pathlib import Path
import re
from typing import Any
from .preflight import check_preflight
from .contract import check_contract

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
    # T07: Install mode flags (mutually exclusive)
    install_mode_group = setup_parser.add_mutually_exclusive_group()
    install_mode_group.add_argument(
        "--minimal",
        action="store_true",
        help="Install v0.1-equivalent (no starter-kit templates or first-pilot flow)",
    )
    install_mode_group.add_argument(
        "--starter",
        action="store_true",
        help="Install v0.2.0 starter-kit (includes templates and first-pilot flow)",
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
    aos_subparsers.add_parser(
        "migrate",
        help="Apply bundle migrations (v0.1: no-op)",
    )

    # preflight subcommand
    preflight_parser = aos_subparsers.add_parser(
        "preflight",
        help="Validate Fieldbook skills are available on a target profile",
    )
    preflight_parser.add_argument(
        "--profile",
        required=True,
        help="Name of the Hermes profile to check",
    )

    # contract subcommand
    contract_parser = aos_subparsers.add_parser(
        "contract",
        help="Discover the exact test command for a workspace",
    )
    contract_parser.add_argument(
        "--workspace",
        required=True,
        help="Path to the workspace to inspect",
    )

    # map-lanes subcommand
    map_lanes_parser = aos_subparsers.add_parser(
        "map-lanes",
        help="Profile mapping wizard for AOS lanes (T02-T03)",
    )
    map_lanes_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run interactive wizard (default in T03)",
    )

    # first-pilot subcommand (T06)
    aos_subparsers.add_parser(
        "first-pilot",
        help="Guided first-pilot flow for calibration (T06)",
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
    elif subcommand == "preflight":
        return _cmd_preflight(args)
    elif subcommand == "contract":
        return _cmd_contract(args)
    elif subcommand == "map-lanes":
        return _cmd_map_lanes(args)
    elif subcommand == "first-pilot":
        return _cmd_first_pilot(args)
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
    
    # T07: Determine install mode
    minimal = getattr(args, "minimal", False)
    starter = getattr(args, "starter", False)
    
    # Validate mutual exclusion
    if minimal and starter:
        print("ERROR: Cannot specify both --minimal and --starter", file=sys.stderr)
        return 1
    
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    
    # Determine install mode
    install_mode = None
    if minimal:
        install_mode = "minimal"
    elif starter:
        install_mode = "starter"
    else:
        # No explicit mode - check if this is a v0.1 upgrade
        if _is_v01_upgrade(hermes_home):
            install_mode = "minimal"
            print()
            print("⚠️  Detected v0.1 installation.")
            print("Installing in minimal mode (v0.1-equivalent).")
            print("To add the v0.2.0 starter-kit later, run:")
            print("  hermes aos setup --starter")
        else:
            # Fresh install - default to minimal
            install_mode = "minimal"
            print()
            print("Installing in minimal mode.")
            print("To install the v0.2.0 starter-kit, run:")
            print("  hermes aos setup --starter")
    
    # Persist install mode
    _save_install_mode(install_mode, hermes_home)
    
    if install_mode == "minimal":
        print()
        print("Minimal mode: v0.1-equivalent installation.")
        print("Starter-kit templates and first-pilot flow not installed.")
    else:
        print()
        print("Starter mode: v0.2.0 starter-kit installation.")
        print("Includes profile templates and first-pilot flow.")
    
    print()
    
    # Continue with SOUL.md setup
    soul = hermes_home / "SOUL.md"
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
    doctor_result = _cmd_doctor(args)

    # Profile-aware gateway messaging
    profile = _get_hermes_profile()
    if doctor_result == 0:
        if _profile_has_gateway(profile):
            # Gateway profile
            if _gateway_is_running_for_profile(profile):
                print()
                print("Restart the gateway for the plugin to take effect:")
                print("  hermes gateway restart")
            else:
                print()
                print("Start the gateway for the plugin to take effect:")
                print("  hermes gateway start")
        else:
            # Non-gateway profile (CLI/worker/TUI)
            print()
            print("Setup complete. The plugin is active for the next CLI/worker invocation.")
            print("Next step: run 'hermes aos map-lanes' to bind profiles to AOS roles")
    return doctor_result


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


def _get_hermes_profile() -> str | None:
    """Get the target Hermes profile name from environment.

    Returns None if running in the default profile or profile cannot be determined.
    """
    # HERMES_PROFILE is set when using -p/--profile flag
    profile = os.environ.get("HERMES_PROFILE")
    if profile and profile != "default":
        return profile

    # Check if HERMES_HOME points to a profile-specific directory
    hermes_home = os.environ.get("HERMES_HOME", "")
    if "/profiles/" in hermes_home:
        # Extract profile name from path like ~/.hermes/profiles/coder
        parts = Path(hermes_home).parts
        if "profiles" in parts:
            idx = parts.index("profiles")
            if idx + 1 < len(parts):
                profile_name = parts[idx + 1]
                if profile_name != "default":
                    return profile_name

    return None


def _profile_has_gateway(profile: str | None) -> bool:
    """Check if a profile has gateway configured.

    Uses hermes profile show to determine if the profile runs a gateway.
    Returns False if profile is None (default profile may have gateway but we assume no).

    This is profile-scoped: it checks the target profile's config, not inherited env vars.
    """
    if profile is None:
        # Default profile or couldn't determine profile - assume no gateway for safety
        return False

    try:
        result = subprocess.run(
            ["hermes", "profile", "show", profile],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False

        # hermes profile show output includes "Gateway: running" or "Gateway: stopped"
        # Any gateway status means the profile has gateway configured
        return "Gateway:" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def _gateway_is_running_for_profile(profile: str | None) -> bool:
    """Check if gateway is currently running for the target profile.

    This is the profile-aware version of _gateway_is_running.
    It combines:
    1. Profile config check (does this profile have a gateway?)
    2. Runtime check (is that gateway actually running?)

    This prevents false positives from env var bleed when running:
      hermes -p <dogfood> aos setup

    where the parent gateway process leaks env vars but the target profile
    is non-gateway (CLI/worker/TUI).
    """
    # First check: does this profile even have a gateway configured?
    if not _profile_has_gateway(profile):
        return False

    # Second check: is a gateway actually running (env vars as fallback)
    # This handles the case where the profile has gateway but it's stopped
    gateway_indicators = [
        "HERMES_GATEWAY_BUSY_INPUT_MODE",
        "HERMES_DASHBOARD_PORT",
        "HERMES_GATEWAY_PORT",
    ]
    return any(indicator in os.environ for indicator in gateway_indicators)


def _gateway_is_running() -> bool:
    """Detect if Hermes gateway is running for this profile.

    Checks for gateway-related environment variables that indicate
    a gateway session. Non-gateway profiles (CLI-only, dogfood, TUI)
    won't have these set.

    DEPRECATED: This function is NOT profile-aware. Use _gateway_is_running_for_profile
    instead to avoid false positives from env var bleed.
    Kept for backward compatibility with existing tests.
    """
    gateway_indicators = [
        "HERMES_GATEWAY_BUSY_INPUT_MODE",
        "HERMES_DASHBOARD_PORT",
        "HERMES_GATEWAY_PORT",
    ]
    return any(indicator in os.environ for indicator in gateway_indicators)


def _plugin_state_dir() -> Path:
    """Return the plugin state directory in HERMES_HOME."""
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    state_dir = hermes_home / "plugins" / PLUGIN_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_install_mode(hermes_home: Path | None = None) -> str | None:
    """Read the install mode from the marker file.

    Returns "minimal", "starter", or None if not found.
    """
    if hermes_home is None:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    
    marker_file = hermes_home / "plugins" / PLUGIN_NAME / "install-mode.txt"
    if not marker_file.exists():
        return None
    
    try:
        content = marker_file.read_text(encoding="utf-8").strip()
        return content
    except OSError:
        return None


def _save_install_mode(mode: str, hermes_home: Path | None = None) -> None:
    """Save the install mode to the marker file."""
    if hermes_home is None:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    
    state_dir = hermes_home / "plugins" / PLUGIN_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    
    marker_file = state_dir / "install-mode.txt"
    marker_file.write_text(mode, encoding="utf-8")


def _is_v01_upgrade(hermes_home: Path) -> bool:
    """Check if this appears to be a v0.1 installation (no marker file but SOUL.md exists)."""
    marker_file = hermes_home / "plugins" / PLUGIN_NAME / "install-mode.txt"
    soul_path = hermes_home / "SOUL.md"
    
    return (not marker_file.exists() and soul_path.exists() and 
            "<!-- aos:begin -->" in soul_path.read_text(encoding="utf-8"))


def _cmd_doctor(args: Any) -> int:
    """Doctor command - delegates to the real implementation from the root entrypoint.

    The root __init__.py contains the real doctor verification logic (skill loadability,
    reference resolution, calibration schema validation, cross-skill name consistency,
    and CLI registration). This function delegates to that implementation to maintain
    a single source of truth for doctor behavior across both entrypoints.
    """
    # Import the root's real doctor implementation
    import importlib.util
    from pathlib import Path

    # Find the plugin root (where __init__.py lives)
    # In package context, we're at agentic_fieldbook/plugin.py, so root is parent.parent
    plugin_root = Path(__file__).resolve().parent.parent

    # Load the root __init__.py directly
    spec = importlib.util.spec_from_file_location("_root_doctor_impl", plugin_root / "__init__.py")
    if spec is None or spec.loader is None:
        print("ERROR: Cannot load root doctor implementation", file=sys.stderr)
        return 1
    root_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(root_module)

    # Call the root's _cmd_doctor
    return root_module._cmd_doctor(args)


def _cmd_version(args: Any) -> int:
    """Print bundle version and compatibility range."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION}")
    print(f"Hermes compatibility: {HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}")
    return 0


def _cmd_migrate(args: Any) -> int:
    """Run bundle migrations; v0.1 intentionally has nothing to migrate."""
    print(f"Agentic Fieldbook v{PLUGIN_VERSION} migrate: no changes needed")
    return 0


def _cmd_preflight(args: Any) -> int:
    """Check if all Fieldbook skills are available on the target profile."""
    profile = getattr(args, "profile", None)
    if not profile:
        print("ERROR: --profile is required", file=sys.stderr)
        return 1
    return check_preflight(profile)


def _cmd_contract(args: Any) -> int:
    """Discover and print the test runner command for a workspace."""
    workspace = getattr(args, "workspace", None)
    if not workspace:
        print("ERROR: --workspace is required", file=sys.stderr)
        return 1
    return check_contract(workspace)


def _cmd_map_lanes(args: Any) -> int:
    """Run the profile-mapping wizard when explicitly requested."""
    # The no-argument path remains a non-interactive compatibility stub;
    # --interactive runs the T03 wizard.
    interactive = getattr(args, "interactive", False)

    if interactive:
        try:
            from .wizard import run_wizard
            return run_wizard()
        except ImportError:
            print("ERROR: wizard module not available", file=sys.stderr)
            return 1
    else:
        print("Profile mapping wizard is available via --interactive; the coming-soon stub remains non-interactive.")
        print("Lane bindings are persisted in the AOS configuration file.")
        return 0


def _cmd_first_pilot(args: Any) -> int:
    """Run the guided first-pilot flow for calibration data collection (T06)."""
    try:
        from .first_pilot import run_first_pilot_flow
        return run_first_pilot_flow(interactive=True)
    except ImportError:
        print("ERROR: first_pilot module not available", file=sys.stderr)
        return 1


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