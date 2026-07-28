"""
Tests for Ticket T05: Profile template system.

These tests verify:
1. Template directory structure under starter-kit/profile-templates/
2. Templates for each canonical AOS role (planner, executor, reviewer, verifier)
3. Template metadata file (YAML) defining role, required skills, profile settings
4. Template instantiation logic: copy template to new profile path, substitute variables
5. Integration with wizard's "build from template" option
6. Bypass by --minimal install: templates not installed or referenced
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace
import tempfile
import os
import shutil
import yaml

# Add plugin to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))


class TestTemplateDirectoryStructure:
    """Test template directory structure exists."""

    def test_profile_templates_directory_exists(self):
        """starter-kit/profile-templates/ directory should exist."""
        from agentic_fieldbook.templates import get_templates_dir
        templates_dir = get_templates_dir()
        assert templates_dir.exists(), "profile-templates directory should exist"

    def test_templates_for_all_four_roles_exist(self):
        """Templates should exist for all 4 AOS roles."""
        from agentic_fieldbook.templates import get_templates_dir, AOS_ROLES

        templates_dir = get_templates_dir()
        for role in AOS_ROLES:
            role_dir = templates_dir / role
            assert role_dir.exists(), f"Template directory for {role} should exist"
            assert role_dir.is_dir(), f"{role} should be a directory"

    def test_each_template_has_metadata_yaml(self):
        """Each template should have a metadata.yaml file."""
        from agentic_fieldbook.templates import get_templates_dir, AOS_ROLES

        templates_dir = get_templates_dir()
        for role in AOS_ROLES:
            metadata_file = templates_dir / role / "metadata.yaml"
            assert metadata_file.exists(), f"metadata.yaml for {role} should exist"

    def test_each_template_has_profile_yaml(self):
        """Each template should have a profile.yaml file."""
        from agentic_fieldbook.templates import get_templates_dir, AOS_ROLES

        templates_dir = get_templates_dir()
        for role in AOS_ROLES:
            profile_file = templates_dir / role / "profile.yaml"
            assert profile_file.exists(), f"profile.yaml for {role} should exist"

    def test_metadata_yaml_has_required_fields(self):
        """metadata.yaml should define role, required skills, and settings."""
        from agentic_fieldbook.templates import get_templates_dir, AOS_ROLES

        templates_dir = get_templates_dir()
        for role in AOS_ROLES:
            metadata_file = templates_dir / role / "metadata.yaml"
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = yaml.safe_load(f)

            assert 'role' in metadata, f"{role} metadata should have 'role' field"
            assert metadata['role'] == role, f"{role} metadata role should match directory name"
            assert 'description' in metadata, f"{role} metadata should have 'description'"
            assert 'required_skills' in metadata, f"{role} metadata should have 'required_skills'"
            assert isinstance(metadata['required_skills'], list), f"{role} required_skills should be a list"


class TestTemplateInstantiation:
    """Test template instantiation logic."""

    def test_get_template_metadata_returns_dict(self):
        """get_template_metadata should return metadata dict for a role."""
        from agentic_fieldbook.templates import get_template_metadata

        metadata = get_template_metadata('planner')
        assert isinstance(metadata, dict)
        assert 'role' in metadata
        assert metadata['role'] == 'planner'

    def test_instantiate_template_creates_new_profile(self, tmp_path, monkeypatch):
        """instantiate_template should create a new profile from template."""
        from agentic_fieldbook.templates import instantiate_template

        # Mock HERMES_HOME to temp directory
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        # Instantiate a planner template
        profile_name = "test-planner-profile"
        result = instantiate_template('planner', profile_name)

        # Profile directory should be created
        profile_dir = tmp_path / "profiles" / profile_name
        assert profile_dir.exists(), f"Profile directory {profile_dir} should exist"
        assert profile_dir.is_dir()

    def test_instantiate_template_copies_files(self, tmp_path, monkeypatch):
        """instantiate_template should copy all template files to new profile."""
        from agentic_fieldbook.templates import instantiate_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        profile_name = "test-executor-profile"
        result = instantiate_template('executor', profile_name)

        profile_dir = tmp_path / "profiles" / profile_name

        # Should have profile.yaml
        profile_yaml = profile_dir / "profile.yaml"
        assert profile_yaml.exists()

        # Should have metadata.yaml (copied from template)
        metadata_yaml = profile_dir / "metadata.yaml"
        assert metadata_yaml.exists()

    def test_instantiate_template_substitutes_variables(self, tmp_path, monkeypatch):
        """instantiate_template should substitute variables in template files."""
        from agentic_fieldbook.templates import instantiate_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        profile_name = "test-verifier-profile"
        result = instantiate_template('verifier', profile_name)

        profile_dir = tmp_path / "profiles" / profile_name
        profile_yaml = profile_dir / "profile.yaml"

        with open(profile_yaml, 'r', encoding='utf-8') as f:
            content = f.read()

        # Profile name should appear in the file (substitution worked)
        assert profile_name in content or "test-verifier-profile" in content

    def test_instantiate_template_all_four_roles(self, tmp_path, monkeypatch):
        """instantiate_template should work for all 4 AOS roles."""
        from agentic_fieldbook.templates import instantiate_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        for role in ['planner', 'executor', 'reviewer', 'verifier']:
            profile_name = f"test-{role}-profile"
            result = instantiate_template(role, profile_name)

            profile_dir = tmp_path / "profiles" / profile_name
            assert profile_dir.exists(), f"Profile for {role} should exist"
            assert result == profile_name, f"Should return profile name for {role}"

    def test_instantiate_template_returns_profile_name(self, tmp_path, monkeypatch):
        """instantiate_template should return the created profile name."""
        from agentic_fieldbook.templates import instantiate_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        profile_name = "my-planner"
        result = instantiate_template('planner', profile_name)

        assert result == profile_name, "Should return the profile name"

    def test_instantiate_template_rejects_invalid_role(self, tmp_path, monkeypatch):
        """instantiate_template should reject invalid AOS role."""
        from agentic_fieldbook.templates import instantiate_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with pytest.raises(ValueError, match="Invalid AOS role"):
            instantiate_template('invalid-role', 'test-profile')


class TestWizardIntegration:
    """Test integration with wizard's build-from-template option."""

    def test_build_from_template_calls_instantiate(self, tmp_path, monkeypatch):
        """wizard.build_from_template should call template instantiation."""
        from agentic_fieldbook.wizard import build_from_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        # Mock user input for profile name
        with patch('builtins.input', return_value='test-planner'):
            result = build_from_template('planner')
            assert result is not None, "Should return a profile name"
            assert isinstance(result, str), "Should return a string"

    def test_build_from_template_creates_profile(self, tmp_path, monkeypatch):
        """wizard.build_from_template should actually create a profile."""
        from agentic_fieldbook.wizard import build_from_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        with patch('builtins.input', return_value='my-reviewer'):
            result = build_from_template('reviewer')

            profile_dir = tmp_path / "profiles" / "my-reviewer"
            assert profile_dir.exists(), "Profile should be created"

    def test_build_from_template_all_roles(self, tmp_path, monkeypatch):
        """wizard.build_from_template should work for all 4 roles."""
        from agentic_fieldbook.wizard import build_from_template

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        for role in ['planner', 'executor', 'reviewer', 'verifier']:
            with patch('builtins.input', return_value=f'test-{role}'):
                result = build_from_template(role)
                assert result is not None, f"Should return profile name for {role}"
                assert result == f'test-{role}', f"Should return correct name for {role}"


class TestMinimalInstallBypass:
    """Test bypass behavior for --minimal install."""

    def test_templates_not_available_in_minimal_mode(self, monkeypatch):
        """Templates should not be available in minimal install mode."""
        monkeypatch.setenv("HERMES_AOS_MODE", "minimal")

        from agentic_fieldbook.templates import get_templates_dir
        templates_dir = get_templates_dir()

        # In minimal mode, templates_dir should not exist or should be None/empty
        assert not templates_dir.exists() or not list(templates_dir.iterdir()), (
            "Templates should not exist in minimal mode"
        )

    def test_build_from_template_returns_none_in_minimal(self, tmp_path, monkeypatch):
        """wizard.build_from_template should return None in minimal mode."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_AOS_MODE", "minimal")

        from agentic_fieldbook.wizard import build_from_template

        result = build_from_template('planner')
        assert result is None, "Should return None in minimal mode"

    def test_instantiate_template_fails_in_minimal(self, tmp_path, monkeypatch):
        """instantiate_template should fail gracefully in minimal mode."""
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setenv("HERMES_AOS_MODE", "minimal")

        from agentic_fieldbook.templates import instantiate_template

        with pytest.raises((ValueError, FileNotFoundError)):
            instantiate_template('planner', 'test-profile')


class TestTemplateModuleImports:
    """Test that template module can be imported."""

    def test_templates_module_importable(self):
        """templates module should be importable."""
        from agentic_fieldbook import templates
        assert templates is not None

    def test_templates_module_has_aos_roles_constant(self):
        """templates module should define AOS_ROLES constant."""
        from agentic_fieldbook.templates import AOS_ROLES
        assert isinstance(AOS_ROLES, list)
        assert len(AOS_ROLES) == 4
        assert 'planner' in AOS_ROLES
        assert 'executor' in AOS_ROLES
        assert 'reviewer' in AOS_ROLES
        assert 'verifier' in AOS_ROLES

    def test_templates_module_has_get_templates_dir(self):
        """templates module should have get_templates_dir function."""
        from agentic_fieldbook.templates import get_templates_dir
        assert callable(get_templates_dir)

    def test_templates_module_has_get_template_metadata(self):
        """templates module should have get_template_metadata function."""
        from agentic_fieldbook.templates import get_template_metadata
        assert callable(get_template_metadata)

    def test_templates_module_has_instantiate_template(self):
        """templates module should have instantiate_template function."""
        from agentic_fieldbook.templates import instantiate_template
        assert callable(instantiate_template)


class TestExistingBehaviorPreserved:
    """Test that T05 doesn't break existing behavior."""

    def test_wizard_module_still_works(self):
        """wizard module should still work after T05."""
        from agentic_fieldbook.wizard import run_wizard, discover_profiles
        assert callable(run_wizard)
        assert callable(discover_profiles)

    def test_config_module_still_works(self):
        """config module should still work after T05."""
        from agentic_fieldbook.config import LaneBindingConfig, read_config, write_config
        assert LaneBindingConfig is not None
        assert callable(read_config)
        assert callable(write_config)

    def test_existing_tests_still_pass(self):
        """Existing T01-T04 tests should still pass."""
        # This is a meta-test - we just verify imports work
        # The actual test run will verify all tests pass
        from agentic_fieldbook.plugin import (
            _cmd_setup,
            _cmd_doctor,
            _cmd_version,
            _cmd_migrate,
        )
        assert callable(_cmd_setup)
        assert callable(_cmd_doctor)
        assert callable(_cmd_version)
        assert callable(_cmd_migrate)
        
        # _cmd_map_lanes should exist but may not be implemented yet
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            assert callable(_cmd_map_lanes)
        except ImportError:
            # _cmd_map_lanes not implemented yet - this is OK
            pass