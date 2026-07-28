"""
Wizard interactive flow for mapping Hermes profiles to AOS roles.

This module provides:
- Interactive CLI flow for each of the 4 AOS roles (planner, executor, reviewer, verifier)
- Per-role prompt offering three options: map existing profile, build from template, skip
- Profile discovery: list available Hermes profiles for map-existing option
- Multi-role support: allow one profile to be bound to multiple roles
- Skip degradation: mark role as unbound and continue gracefully
- Re-run preservation: read existing binding file on load, preserve unchanged roles
"""

import os
from pathlib import Path
from typing import Optional, List

from .config import read_config, write_config, LaneBindingConfig


AOS_ROLES = ["planner", "executor", "reviewer", "verifier"]


def discover_profiles() -> List[str]:
    """
    Discover available Hermes profiles.
    
    Returns:
        List[str]: List of profile names found in ~/.hermes/profiles/
    """
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    # When Hermes is launched with ``-p NAME``, HERMES_HOME may point at the
    # profile directory itself (…/.hermes/profiles/NAME), not the global home.
    # Prefer the normal global layout, then walk back to it from a profile dir.
    profiles_dir = hermes_home / "profiles"
    if not profiles_dir.is_dir() and hermes_home.parent.name == "profiles":
        profiles_dir = hermes_home.parent
    
    if not profiles_dir.exists():
        if "HERMES_HOME" not in os.environ:
            return []
        raise RuntimeError(f"Hermes profiles directory does not exist: {profiles_dir}")
    if not profiles_dir.is_dir():
        raise RuntimeError(f"Hermes profiles path is not a directory: {profiles_dir}")
    
    profiles = []
    for profile_path in profiles_dir.iterdir():
        if profile_path.is_dir():
            profiles.append(profile_path.name)
    
    return sorted(profiles)


def build_from_template(role: str) -> Optional[str]:
    """
    Build a new profile from a template.
    
    Args:
        role: The AOS role to create a profile for.
    
    Returns:
        Optional[str]: The new profile name, or None if failed/cancelled.
    
    Note:
        This function prompts the user for a profile name and instantiates
        a template. Returns None if in minimal mode or user cancels.
    """
    try:
        from .templates import instantiate_template, _is_minimal_mode, AOS_ROLES
        
        if _is_minimal_mode():
            print(f"\nTemplate instantiation is not available in minimal mode.")
            print(f"Please install with --starter flag or create profile manually.")
            return None
        
        if role not in AOS_ROLES:
            print(f"\nInvalid AOS role: {role}")
            return None
        
        # Prompt for profile name
        print(f"\n--- Building profile from template for role: {role} ---")
        
        # Get template metadata
        from .templates import get_template_metadata
        try:
            metadata = get_template_metadata(role)
            print(f"Template: {metadata.get('description', 'No description available')}")
        except FileNotFoundError:
            print(f"Template not found for role: {role}")
            return None
        
        # Prompt for profile name
        profile_name = input(f"Enter profile name for {role} [default: aos-{role}]: ").strip()
        
        if not profile_name:
            profile_name = f"aos-{role}"
        
        # Instantiate template
        try:
            result = instantiate_template(role, profile_name)
            if result:
                print(f"\n✓ Profile '{result}' created successfully from {role} template")
                print(f"  Run 'hermes profiles list' to see the new profile")
                return result
            else:
                print(f"\n✗ Failed to create profile '{profile_name}'")
                return None
        except ValueError as e:
            if "minimal mode" in str(e):
                # Already handled by _is_minimal_mode() check above, but just in case
                print(f"\n✗ Template instantiation is not available in minimal mode")
            else:
                print(f"\n✗ Error: {e}")
            return None
        except FileNotFoundError as e:
            print(f"\n✗ Template not found: {e}")
            return None
    
    except ImportError:
        # templates module not available (T05 not implemented)
        print(f"\nProfile templates are not yet available.")
        print(f"For now, please create the profile manually or use 'map existing'.")
        return None


def prompt_for_role(role: str) -> Optional[str]:
    """
    Prompt the user for a profile binding for a single AOS role.
    
    Args:
        role: The AOS role to prompt for (e.g., 'planner').
    
    Returns:
        Optional[str]: The profile name to bind, or None if skipped.
    """
    while True:
        print(f"\n--- Binding for role: {role} ---")
        print("Choose an option:")
        print("  1) Map existing profile")
        print("  2) Build from template (coming in T05)")
        print("  3) Skip (leave unbound)")
        
        choice = input("Enter choice [1/2/3]: ").strip().lower()
        
        if choice in ('1', 'map', 'existing'):
            return _prompt_map_existing(role)
        elif choice in ('2', 'template', 'build'):
            return build_from_template(role)
        elif choice in ('3', 'skip'):
            print(f"Skipping role: {role} (unbound)")
            return None
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")


def _prompt_map_existing(role: str) -> Optional[str]:
    """
    Prompt user to select from available Hermes profiles.
    
    Args:
        role: The AOS role being bound.
    
    Returns:
        Optional[str]: The selected profile name, or None if cancelled.
    """
    profiles = discover_profiles()
    
    if not profiles:
        print("\nNo Hermes profiles found.")
        print("To create a profile, run: hermes profiles create <name>")
        return None
    
    print(f"\nAvailable Hermes profiles:")
    for i, profile in enumerate(profiles, 1):
        print(f"  {i}) {profile}")
    print(f"  0) Cancel (skip this role)")
    
    while True:
        choice = input(f"Select profile for {role} [0-{len(profiles)}]: ").strip()
        
        if choice == '0':
            print(f"Skipping role: {role}")
            return None
        
        try:
            idx = int(choice)
            if 1 <= idx <= len(profiles):
                selected = profiles[idx - 1]
                print(f"Binding {role} -> {selected}")
                return selected
            else:
                print(f"Invalid number. Please enter 0-{len(profiles)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")


def run_wizard() -> int:
    """
    Run the interactive wizard flow for mapping AOS roles to profiles.
    
    Returns:
        int: Exit code (0 for success, non-zero for errors).
    """
    print("=" * 60)
    print("Agentic Fieldbook Profile Mapping Wizard")
    print("=" * 60)
    print()
    print("This wizard helps you bind Hermes profiles to AOS roles:")
    print("  - planner:   Plans and decomposes tasks")
    print("  - executor:  Executes tasks")
    print("  - reviewer:  Reviews task outcomes")
    print("  - verifier:  Verifies reviews and decisions")
    print()
    print("You can:")
    print("  - Map existing profiles to roles")
    print("  - Build new profiles from templates (T05)")
    print("  - Skip roles to leave them unbound")
    print()
    print("Note: One profile can serve multiple roles.")
    print()
    
    # Read existing config to preserve bindings on re-run
    existing_config = read_config()
    
    # Build new config, preserving existing bindings
    new_bindings = {}
    for role in AOS_ROLES:
        existing_profile = getattr(existing_config, role)
        
        if existing_profile:
            print(f"Role {role} is already bound to: {existing_profile}")
            change = input(f"Change binding for {role}? [y/N]: ").strip().lower()
            
            if change in ('y', 'yes'):
                new_profile = prompt_for_role(role)
                new_bindings[role] = new_profile
            else:
                print(f"Preserving existing binding: {role} -> {existing_profile}")
                new_bindings[role] = existing_profile
        else:
            new_profile = prompt_for_role(role)
            new_bindings[role] = new_profile
    
    # Create new config with updated bindings
    updated_config = LaneBindingConfig(
        planner=new_bindings.get("planner"),
        executor=new_bindings.get("executor"),
        reviewer=new_bindings.get("reviewer"),
        verifier=new_bindings.get("verifier"),
    )
    
    # Write config
    write_config(updated_config)
    
    # Summary
    print()
    print("=" * 60)
    print("Binding Summary")
    print("=" * 60)
    for role in AOS_ROLES:
        profile = getattr(updated_config, role)
        status = f"-> {profile}" if profile else "(unbound)"
        print(f"  {role:10s} {status}")
    print()
    print("Config saved. Run 'hermes aos doctor' to verify.")
    print()
    
    return 0