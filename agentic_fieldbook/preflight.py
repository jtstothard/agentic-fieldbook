"""Preflight command for validating Fieldbook skills on target profiles."""

import subprocess
import sys
from typing import List, Optional

FIELDBOOK_SKILLS = [
    "contract-schema",
    "risk-taxonomy",
    "stage-handoff",
    "lane-calibration",
    "knowledge-lifecycle",
    "planning-routing",
    "review-calibration",
]


def _get_profile_skills(profile: str) -> Optional[List[str]]:
    """Get list of installed skill names for a profile via Hermes CLI.

    Returns None if an error occurs.
    """
    try:
        result = subprocess.run(
            ["hermes", "--profile", profile, "skills", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        print("ERROR: hermes command not found. Run from a Hermes environment.", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        stderr_lower = e.stderr.lower() if e.stderr else ""
        if "profile" in stderr_lower and "not found" in stderr_lower:
            print(f"ERROR: Profile '{profile}' not found.", file=sys.stderr)
        else:
            print(f"ERROR: Failed to list skills for profile '{profile}': {e.stderr}", file=sys.stderr)
        return None

    # Parse skill names from table output (first column after header)
    skills = []
    lines = result.stdout.strip().split("\n")
    for line in lines:
        # Skip header/separator lines (header has "Name", separator has "━")
        if not line or "Name" in line or "━" in line:
            continue
        # Extract first token after the leading │ (skill name)
        parts = line.split("│")
        if len(parts) > 1:
            skill_name = parts[1].strip()
            # Filter out table formatting artifacts and empty rows
            if skill_name and not skill_name.startswith("┃"):
                skills.append(skill_name)

    return skills


def check_preflight(profile: str) -> int:
    """Check if all Fieldbook skills are available on the target profile.

    Args:
        profile: Name of the Hermes profile to check.

    Returns:
        0 if all skills present, 1 if any missing or error occurs.
    """
    installed_skills = _get_profile_skills(profile)
    if installed_skills is None:
        return 1

    missing_skills = [s for s in FIELDBOOK_SKILLS if s not in installed_skills]

    if not missing_skills:
        print(f"✓ All {len(FIELDBOOK_SKILLS)} Fieldbook skills available on profile '{profile}'")
        return 0
    else:
        print(f"✗ Missing {len(missing_skills)} Fieldbook skill(s) on profile '{profile}':", file=sys.stderr)
        for skill in missing_skills:
            print(f"  - {skill}", file=sys.stderr)
        print()
        print("To fix this:", file=sys.stderr)
        print(f"  1. Install the agentic-fieldbook plugin on profile '{profile}':", file=sys.stderr)
        print(f"     hermes --profile {profile} plugins install git+https://github.com/jtstothard/agentic-fieldbook.git", file=sys.stderr)
        print(f"  2. Or remove the forced skill from the kanban card and copy the method inline.", file=sys.stderr)
        return 1