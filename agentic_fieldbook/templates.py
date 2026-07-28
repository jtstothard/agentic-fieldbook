"""
Profile template system for Agentic Fieldbook starter-kit.

This module provides:
- Template directory structure under starter-kit/profile-templates/
- Templates for each canonical AOS role (planner, executor, reviewer, verifier)
- Template metadata file (YAML) defining role, required skills, profile settings
- Template instantiation logic: copy template to new profile path, substitute variables
- Bypass by --minimal install: templates not installed or referenced
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import shutil
import yaml

AOS_ROLES = ["planner", "executor", "reviewer", "verifier"]


def _is_minimal_mode() -> bool:
    """Check if running in minimal install mode."""
    return os.environ.get("HERMES_AOS_MODE", "").lower() == "minimal"


def get_templates_dir() -> Path:
    """
    Get the canonical path to the profile templates directory.

    Returns:
        Path: Path to starter-kit/profile-templates/ in the plugin directory.
              In minimal mode, returns a non-existent path.
    """
    if _is_minimal_mode():
        # Return a truly non-existent path for minimal mode
        return Path("/nonexistent/hermes-aos-templates")

    # Get the plugin directory (agentic_fieldbook/__init__.py location)
    plugin_dir = Path(__file__).resolve().parent.parent
    templates_dir = plugin_dir / "starter-kit" / "profile-templates"

    return templates_dir


def get_template_metadata(role: str) -> Dict[str, Any]:
    """
    Get metadata for a template role.

    Args:
        role: The AOS role (planner, executor, reviewer, verifier).

    Returns:
        Dict[str, Any]: Template metadata including role, description, required_skills.

    Raises:
        ValueError: If role is invalid.
        FileNotFoundError: If template directory or metadata.yaml doesn't exist.
    """
    if role not in AOS_ROLES:
        raise ValueError(f"Invalid AOS role: {role}. Must be one of {AOS_ROLES}")

    templates_dir = get_templates_dir()
    metadata_file = templates_dir / role / "metadata.yaml"

    if not metadata_file.exists():
        raise FileNotFoundError(f"Template metadata not found for role: {role}")

    with open(metadata_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _substitute_variables(content: str, variables: Dict[str, str]) -> str:
    """
    Substitute variables in template content.

    Args:
        content: Template content as string.
        variables: Dictionary of variable names to values.

    Returns:
        str: Content with variables substituted.
    """
    result = content
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def instantiate_template(role: str, profile_name: str) -> Optional[str]:
    """
    Instantiate a new profile from a template.

    Args:
        role: The AOS role template to use (planner, executor, reviewer, verifier).
        profile_name: Name for the new profile.

    Returns:
        Optional[str]: The profile name if successful, None if failed or minimal mode.

    Raises:
        ValueError: If role is invalid or in minimal mode.
        FileNotFoundError: If template doesn't exist and not in minimal mode.
    """
    if _is_minimal_mode():
        raise ValueError("Template instantiation is not available in minimal mode")

    if role not in AOS_ROLES:
        raise ValueError(f"Invalid AOS role: {role}. Must be one of {AOS_ROLES}")

    # Get Hermes home directory
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    profiles_dir = hermes_home / "profiles"

    # Create profiles directory if it doesn't exist
    profiles_dir.mkdir(parents=True, exist_ok=True)

    # New profile path
    new_profile_dir = profiles_dir / profile_name

    # Check if profile already exists
    if new_profile_dir.exists():
        raise ValueError(f"Profile '{profile_name}' already exists")

    # Get template directory
    templates_dir = get_templates_dir()
    template_dir = templates_dir / role

    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found for role: {role}")

    # Copy template files to new profile
    shutil.copytree(template_dir, new_profile_dir)

    # Substitute variables in copied files
    variables = {
        "PROFILE_NAME": profile_name,
        "AOS_ROLE": role,
    }

    # Substitute in profile.yaml if it exists
    profile_yaml = new_profile_dir / "profile.yaml"
    if profile_yaml.exists():
        with open(profile_yaml, 'r', encoding='utf-8') as f:
            content = f.read()
        substituted = _substitute_variables(content, variables)
        with open(profile_yaml, 'w', encoding='utf-8') as f:
            f.write(substituted)

    # Substitute in metadata.yaml if it exists
    metadata_yaml = new_profile_dir / "metadata.yaml"
    if metadata_yaml.exists():
        with open(metadata_yaml, 'r', encoding='utf-8') as f:
            content = f.read()
        substituted = _substitute_variables(content, variables)
        with open(metadata_yaml, 'w', encoding='utf-8') as f:
            f.write(substituted)

    return profile_name


def list_available_templates() -> Dict[str, Dict[str, Any]]:
    """
    List all available templates with their metadata.

    Returns:
        Dict[str, Dict[str, Any]]: Mapping of role to metadata.
                                    Empty dict in minimal mode or if no templates found.
    """
    if _is_minimal_mode():
        return {}

    templates_dir = get_templates_dir()
    result = {}

    for role in AOS_ROLES:
        metadata_file = templates_dir / role / "metadata.yaml"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    result[role] = yaml.safe_load(f)
            except Exception:
                # Skip invalid templates
                continue

    return result