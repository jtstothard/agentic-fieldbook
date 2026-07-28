"""Repo-root Hermes plugin entry point (self-contained for git installs)."""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Hermes loads this file as hermes_plugins.agentic_fieldbook via
# importlib.util.spec_from_file_location, which does NOT add the plugin
# directory to sys.path. Without this, `from agentic_fieldbook.plugin import`
# raises ModuleNotFoundError on Git installs. See issue #43.
sys.path.insert(0, str(Path(__file__).resolve().parent))

PLUGIN_NAME = "agentic-fieldbook"
_VERSION_FILE = Path(__file__).with_name("VERSION")
PLUGIN_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
HERMES_COMPATIBILITY = {"min": "0.18.0", "max": "0.20.0"}
EXPECTED_COMMANDS = ("setup", "doctor", "version", "migrate", "preflight", "contract")
EXPECTED_SKILLS = {
    "lane-calibration", "planning-routing", "risk-taxonomy", "review-calibration",
    "stage-handoff", "contract-schema", "knowledge-lifecycle",
}
__version__ = PLUGIN_VERSION


def register(ctx: Any) -> None:
    """Register plugin commands by delegating to the package implementation.

    This ensures the root entrypoint (used by git installs) and the package
    entrypoint (used by pip installs) expose exactly the same CLI commands.
    """
    # Import the package's CLI registration to maintain one source of truth
    from agentic_fieldbook.plugin import _register_aos_cli

    ctx.register_cli_command(
        name="aos", help="Agentic Fieldbook commands", setup_fn=_register_aos_cli,
        handler_fn=_handle_aos_command,
        description="Agentic Fieldbook — setup, doctor, version, migrate, preflight, contract.",
    )


def _handle_aos_command(args: Any) -> int:
    """Dispatch aos subcommands to their handlers.

    This bridges the CLI registration (from the package) with the root's
    command implementations, preserving the root's real doctor and version gap
    checking logic while gaining the package's preflight/contract commands.
    """
    subcommand = getattr(args, "aos_subcommand", None)
    if subcommand == "setup": return _cmd_setup(args)
    if subcommand == "doctor": return _cmd_doctor(args)
    if subcommand == "version": return _cmd_version(args)
    if subcommand == "migrate": return _cmd_migrate(args)
    if subcommand == "preflight": return _cmd_preflight(args)
    if subcommand == "contract": return _cmd_contract(args)
    print(f"Unknown aos subcommand: {subcommand}")
    return 1


def _cmd_preflight(args: Any) -> int:
    """Check if all Fieldbook skills are available on the target profile."""
    from agentic_fieldbook.plugin import _cmd_preflight as package_preflight
    return package_preflight(args)


def _cmd_contract(args: Any) -> int:
    """Discover and print the test runner command for a workspace."""
    from agentic_fieldbook.plugin import _cmd_contract as package_contract
    return package_contract(args)


def _cmd_setup(args: Any) -> int:
    is_compatible, error_msg = _check_hermes_version()
    if not is_compatible:
        print(f"ERROR: {error_msg}", file=sys.stderr)
        print(
            f"Agentic Fieldbook v{PLUGIN_VERSION} requires Hermes "
            f"{HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}",
            file=sys.stderr,
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

    # Check for version gap
    _check_and_prompt_version_update()

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
    return doctor_result


def _parse_version(version_str: str) -> tuple[int, int, int]:
    parts = version_str.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version_str}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _check_hermes_version() -> tuple[bool, str]:
    try:
        hermes = _hermes_runtime_module()
        version_str = getattr(hermes, "__version__", None)
        if not version_str:
            return False, "Cannot determine Hermes version: __version__ not found"
        version = _parse_version(version_str)
        minimum = _parse_version(HERMES_COMPATIBILITY["min"])
        maximum = _parse_version(HERMES_COMPATIBILITY["max"])
        if version < minimum:
            return False, f"Hermes version {version_str} is below minimum {HERMES_COMPATIBILITY['min']}"
        if version > maximum:
            return False, f"Hermes version {version_str} exceeds maximum {HERMES_COMPATIBILITY['max']}"
        return True, ""
    except ImportError:
        return False, "Hermes module not found (running outside Hermes?)"
    except Exception as exc:
        return False, f"Version check error: {exc}"


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


def _skills_toolset_available(hermes: Any) -> bool:
    tools = getattr(hermes, "tools", None)
    if tools is None:
        return True
    enabled = getattr(tools, "skills", None)
    return enabled is not False


def _plugin_root(args: Any = None) -> Path:
    override = getattr(args, "plugin_root", None) if args is not None else None
    return Path(override or os.environ.get("AGENTIC_FIELD_BOOK_PLUGIN_ROOT", Path(__file__).parent)).resolve()


def _bundle_version(root: Path) -> str:
    """Read the coupled bundle version from the installed plugin root."""
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return PLUGIN_VERSION
    return version or PLUGIN_VERSION


def _plugin_state_dir() -> Path:
    """Return the plugin state directory in HERMES_HOME."""
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    state_dir = hermes_home / "plugins" / PLUGIN_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _load_plugin_state() -> dict[str, Any]:
    """Load plugin state from state.json, return empty dict if missing."""
    state_file = _plugin_state_dir() / "state.json"
    if not state_file.exists():
        return {}
    import json
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_plugin_state(state: dict[str, Any]) -> None:
    """Save plugin state to state.json."""
    import json
    state_file = _plugin_state_dir() / "state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _get_latest_github_version() -> tuple[bool, str]:
    """
    Fetch the latest release version from GitHub.

    Returns (success, version_string). On failure, version_string is empty.
    """
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(
            "https://api.github.com/repos/jtstothard/agentic-fieldbook/releases/latest",
            timeout=5
        ) as response:
            data = json.loads(response.read().decode())
            tag = data.get("tag_name", "")
            if tag and tag.startswith("v"):
                return True, tag[1:]  # Strip 'v' prefix
            return False, ""
    except Exception:
        return False, ""


def _get_available_version() -> str:
    """
    Get the available bundle version from GitHub.

    Falls back to current installed version if GitHub check fails.
    """
    success, remote_version = _get_latest_github_version()
    if success and remote_version:
        return remote_version
    # Fallback to current installed version
    return PLUGIN_VERSION


def _check_and_prompt_version_update() -> None:
    """
    Check for version gap and prompt user if needed.

    Offers three choices: apply (y), skip this version (s), remind later (n).
    Persists choice per version so same version never re-prompts.
    """
    available = _get_available_version()
    if available == PLUGIN_VERSION:
        return  # No version gap

    state = _load_plugin_state()
    version_decisions = state.get("version_decisions", {})

    # Check if we already have a decision for this version
    if available in version_decisions:
        decision = version_decisions[available]
        if decision in {"skipped", "remind_later"}:
            # Skip prompt for previously decided versions
            return

    # Version gap detected - prompt user
    print(f"\n📦 Update available: Agentic Fieldbook v{available} (you have v{PLUGIN_VERSION})")
    print("Your choices:")
    print("  [y] Apply update")
    print(f"  [s] Skip this version (never prompt for v{available} again)")
    print("  [n] Remind later (do not prompt again for this version)")

    if not sys.stdin.isatty():
        # Non-interactive mode: skip prompt
        return

    answer = input("Your choice [y/s/n]: ").strip().lower()

    # Save decision
    state.setdefault("version_decisions", {})[available] = {
        "y": "applied",
        "s": "skipped",
        "n": "remind_later"
    }.get(answer, "remind_later")
    _save_plugin_state(state)

    if answer in {"y", "yes"}:
        print(f"Apply update: run 'pip install --upgrade git+https://github.com/jtstothard/agentic-fieldbook.git@v{available}'")
    elif answer in {"s", "skip"}:
        print(f"Skipped v{available}. You won't be prompted for this version again.")
    else:
        print(f"Reminder set. You may be prompted again later.")


def _skills(root: Path) -> list[Path]:
    directory = root / "skills"
    return sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def _frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("unterminated YAML frontmatter")
    import yaml
    data = yaml.safe_load(text[3:end])
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data, text[end + 4:]


def _check_skill_loadability(root: Path) -> list[str]:
    failures = []
    skills = _skills(root)
    if not skills:
        return ["skills-loadability: skills directory is missing or empty"]
    for directory in skills:
        path = directory / "SKILL.md"
        try:
            data, _ = _frontmatter(path)
            for field in ("name", "description"):
                if not data.get(field): failures.append(f"skills-loadability: {directory.name}/SKILL.md missing {field}")
            if data.get("name") != directory.name:
                failures.append(f"skills-loadability: {directory.name}/SKILL.md name is {data.get('name')!r}")
        except Exception as exc:
            failures.append(f"skills-loadability: {directory.name}/SKILL.md ({exc})")
    return failures


def _check_references(root: Path) -> list[str]:
    failures = []
    for directory in _skills(root):
        skill = directory / "SKILL.md"
        if not skill.exists(): continue
        try: _, body = _frontmatter(skill)
        except Exception: continue
        # Extract paths from markdown backticks, filter for plausible file paths
        for raw in re.findall(r"`([^`]+)`", body):
            candidate = raw.strip().lstrip("./")
            # Filter: must contain slash, not start with http, look like a real file path
            if "/" not in candidate or candidate.startswith(("http:", "https:")):
                continue
            if len(candidate) > 200:  # arbitrary length guard
                continue
            # Skip if it looks like a code function call or command
            if "(" in candidate or ")" in candidate or " -type " in candidate or candidate.startswith(("~", "$")):
                continue
            # Skip template variables like <case_id>
            if "<" in candidate and ">" in candidate:
                continue
            # Check if it has a file extension
            if not any(candidate.endswith(ext) for ext in (".md", ".yaml", ".yml", ".txt", ".json")):
                continue
            if not (directory / candidate).is_file():
                failures.append(f"references-resolve: {directory.name}/{candidate}")
    return failures


def _type_ok(value: Any, typ: str) -> bool:
    return {"object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool)}.get(typ, True)


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors = []
    typ = schema.get("type")
    # Handle nullable: true by accepting None for any type
    if value is None and schema.get("nullable"):
        return errors
    if typ and not _type_ok(value, typ): return [f"{path}: expected {typ}"]
    if "enum" in schema and value not in schema["enum"]: errors.append(f"{path}: not one of {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: errors.append(f"{path}: missing required field {key}")
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}: unexpected field {key}" for key in value if key not in schema.get("properties", {}))
        for key, subschema in schema.get("properties", {}).items():
            if key in value: errors.extend(_validate(value[key], subschema, f"{path}.{key}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value): errors.extend(_validate(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, (int, float)) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below minimum {schema['minimum']}")
    return errors


def _check_calibration(root: Path) -> list[str]:
    try:
        import yaml
        base = root / "skills" / "lane-calibration" / "references"
        schema = yaml.safe_load((base / "calibration-schema.yaml").read_text())
        example = yaml.safe_load((base / "calibration-example.yaml").read_text())
        return [f"calibration-schema: {error}" for error in _validate(example, schema)]
    except Exception as exc:
        return [f"calibration-schema: {exc}"]


def _check_cross_skill_names(root: Path) -> list[str]:
    installed = set()
    bodies = []
    failures = []
    for directory in _skills(root):
        try:
            data, body = _frontmatter(directory / "SKILL.md")
            installed.add(data.get("name"))
            bodies.append((directory.name, body))
        except Exception: continue
    # Look for references to expected skills with skill or skills keyword
    for owner, body in bodies:
        for name in EXPECTED_SKILLS:
            # Check if body references this skill with skill/keyword
            if re.search(rf"`{re.escape(name)}`\s*(?:skill|skills)", body, re.IGNORECASE):
                if name not in installed:
                    failures.append(f"cross-skill-references: {owner} references missing {name}")
    return failures


def _check_cli_registration() -> list[str]:
    # Check the package's CLI registration since root delegates to it
    from agentic_fieldbook.plugin import _register_aos_cli as package_register
    source = inspect.getsource(package_register)
    missing = []
    for name in EXPECTED_COMMANDS:
        # Look for add_parser calls - they may be multi-line like:
        #   aos_subparsers.add_parser(
        #       "setup",
        # or
        #   setup_parser = aos_subparsers.add_parser(
        #       "setup",
        # So we check for the presence of both add_parser and the quoted name
        if 'add_parser' not in source:
            missing.append(f"cli-registration: missing command {name} (no add_parser)")
            continue
        # Check for the name being quoted in either single or double quotes
        if f'"{name}"' not in source and f"'{name}'" not in source:
            missing.append(f"cli-registration: missing command {name}")
    return missing


def _check_lane_binding_file() -> list[str]:
    """Validate lane-binding config file existence and schema."""
    failures = []
    from agentic_fieldbook.config import validate_binding_file, get_config_path
    
    result = validate_binding_file()
    
    if result["status"] == "error":
        failures.append(f"lane-binding-config: {result['message']} - {result['details'].get('error', '')}")
    elif result["status"] == "warning":
        # Missing file is a warning, not a hard failure
        # Still report it but don't fail the whole check
        pass
    
    return failures


def _check_starter_kit_assets() -> list[str]:
    """Verify starter-kit asset resolution when --starter installed."""
    failures = []
    from agentic_fieldbook.plugin import get_install_mode
    
    install_mode = get_install_mode()
    
    # If minimal mode or unknown, skip asset checks
    if install_mode != "starter":
        return failures
    
    # In starter mode, verify profile-templates exist
    plugin_root = Path(__file__).parent
    starter_kit_dir = plugin_root / "starter-kit"
    
    if not starter_kit_dir.exists():
        failures.append("starter-kit-assets: starter-kit directory missing")
        return failures
    
    profile_templates_dir = starter_kit_dir / "profile-templates"
    if not profile_templates_dir.exists():
        failures.append("starter-kit-assets: profile-templates directory missing")
        return failures
    
    # Check for all 4 role templates
    expected_roles = ["planner", "executor", "reviewer", "verifier"]
    for role in expected_roles:
        role_dir = profile_templates_dir / role
        if not role_dir.exists():
            failures.append(f"starter-kit-assets: missing profile template for role '{role}'")
        else:
            # Check for metadata file
            metadata_file = role_dir / "metadata.yaml"
            if not metadata_file.exists():
                failures.append(f"starter-kit-assets: missing metadata.yaml for role '{role}'")
            else:
                # Validate metadata structure
                try:
                    import yaml
                    metadata = yaml.safe_load(metadata_file.read_text())
                    if not isinstance(metadata, dict):
                        failures.append(f"starter-kit-assets: malformed metadata.yaml for role '{role}' (not a dict)")
                    elif "role" not in metadata:
                        failures.append(f"starter-kit-assets: missing 'role' field in metadata.yaml for '{role}'")
                except Exception as e:
                    failures.append(f"starter-kit-assets: error reading metadata.yaml for role '{role}': {e}")
    
    return failures


def _check_install_mode() -> list[str]:
    """Report install mode (minimal vs starter)."""
    failures = []
    from agentic_fieldbook.plugin import get_install_mode
    
    install_mode = get_install_mode()
    
    # This check is informational, not a failure
    # The doctor output will show the mode
    return failures


def _doctor_failures(root: Path) -> list[str]:
    failures = []
    failures += _check_skill_loadability(root)
    failures += _check_references(root)
    failures += _check_calibration(root)
    failures += _check_cross_skill_names(root)
    failures += _check_cli_registration()
    # T08: Add new v0.2 doctor checks
    failures += _check_lane_binding_file()
    failures += _check_starter_kit_assets()
    failures += _check_install_mode()
    return failures


def _cmd_doctor(args: Any) -> int:
    root = _plugin_root(args)
    failures = _doctor_failures(root)
    print(f"Agentic Fieldbook v{_bundle_version(root)} doctor")
    
    # Report install mode (T08)
    from agentic_fieldbook.plugin import get_install_mode
    install_mode = get_install_mode()
    if install_mode:
        print(f"Install mode: {install_mode}")
    else:
        print("Install mode: not detected (v0.1 or fresh install)")
    
    # Report lane-binding status (T08)
    from agentic_fieldbook.config import validate_binding_file
    binding_status = validate_binding_file()
    if binding_status["status"] == "ok":
        bound = binding_status["details"]["bound_roles"]
        unbound = binding_status["details"]["unbound_roles"]
        print(f"Lane bindings: {len(bound)} bound, {len(unbound)} unbound")
        if bound:
            print(f"  Bound roles: {', '.join(bound)}")
        if unbound:
            print(f"  Unbound roles: {', '.join(unbound)}")
    elif binding_status["status"] == "warning":
        print(f"Lane bindings: not configured (run 'hermes aos map-lanes')")
    else:
        print(f"Lane bindings: ERROR - {binding_status['message']}")
    
    if failures:
        print(f"FAIL: {len(failures)} named check(s) failed")
        for failure in failures: print(f"- {failure}")
        return 1
    print(f"ALL CLEAR: skills, references, calibration schema, cross-skill names, and CLI registration verified")
    return 0


def _cmd_version(args: Any) -> int:
    print(f"Agentic Fieldbook v{PLUGIN_VERSION}")
    print(f"Hermes compatibility: {HERMES_COMPATIBILITY['min']}–{HERMES_COMPATIBILITY['max']}")
    return 0
def _cmd_migrate(args: Any) -> int:
    """Run bundle migrations; v0.1 intentionally has nothing to migrate."""
    print(f"Agentic Fieldbook v{_bundle_version(_plugin_root(args))} migrate: no changes needed")
    return 0


__all__ = ["register", "__version__"]