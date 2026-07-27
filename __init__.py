"""Repo-root Hermes plugin entry point (self-contained for git installs)."""

from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any

PLUGIN_NAME = "agentic-fieldbook"
_VERSION_FILE = Path(__file__).with_name("VERSION")
PLUGIN_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip()
HERMES_COMPATIBILITY = {"min": "0.18.0", "max": "0.20.0"}
EXPECTED_COMMANDS = ("setup", "doctor", "version", "migrate")
EXPECTED_SKILLS = {
    "lane-calibration", "planning-routing", "risk-taxonomy", "review-calibration",
    "stage-handoff", "contract-schema", "knowledge-lifecycle",
}
__version__ = PLUGIN_VERSION


def register(ctx: Any) -> None:
    ctx.register_cli_command(
        name="aos", help="Agentic Fieldbook commands", setup_fn=_register_aos_cli,
        handler_fn=_handle_aos_command,
        description="Agentic Fieldbook — setup, doctor, and version commands.",
    )


def _register_aos_cli(subparsers: Any) -> None:
    parsers = subparsers.add_subparsers(dest="aos_subcommand", title="subcommands", required=True)
    setup_parser = parsers.add_parser("setup", help="Set up Agentic Fieldbook")
    setup_parser.add_argument("--yes", action="store_true", help="accept SOUL.md changes")
    parsers.add_parser("doctor", help="Verify Agentic Fieldbook installation")
    parsers.add_parser("version", help="Show Agentic Fieldbook bundle version")
    parsers.add_parser("migrate", help="Apply bundle migrations (v0.1: no-op)")


def _handle_aos_command(args: Any) -> int:
    subcommand = getattr(args, "aos_subcommand", None)
    if subcommand == "setup": return _cmd_setup(args)
    if subcommand == "doctor": return _cmd_doctor(args)
    if subcommand == "version": return _cmd_version(args)
    if subcommand == "migrate": return _cmd_migrate(args)
    print(f"Unknown aos subcommand: {subcommand}")
    return 1


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
    if doctor_result == 0 and _gateway_is_running():
        print()
        print("Restart the gateway for the plugin to take effect:")
        print("  hermes gateway restart")
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


def _gateway_is_running() -> bool:
    """Detect if Hermes gateway is running for this profile.

    Checks for gateway-related environment variables that indicate
    a gateway session. Non-gateway profiles (CLI-only, dogfood, TUI)
    won't have these set.
    """
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
    source = inspect.getsource(_register_aos_cli)
    return [f"cli-registration: missing command {name}" for name in EXPECTED_COMMANDS
            if not re.search(rf'add_parser\(\s*["\']{re.escape(name)}["\']', source)]


def _doctor_failures(root: Path) -> list[str]:
    failures = []
    failures += _check_skill_loadability(root)
    failures += _check_references(root)
    failures += _check_calibration(root)
    failures += _check_cross_skill_names(root)
    failures += _check_cli_registration()
    return failures


def _cmd_doctor(args: Any) -> int:
    root = _plugin_root(args)
    failures = _doctor_failures(root)
    print(f"Agentic Fieldbook v{_bundle_version(root)} doctor")
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