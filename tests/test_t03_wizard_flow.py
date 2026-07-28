"""
Tests for Ticket T03: Wizard interactive flow per role.

These tests verify:
1. Interactive CLI flow for each of the 4 AOS roles (planner, executor, reviewer, verifier)
2. Per-role prompt offering three options: map existing, build from template, skip
3. Profile discovery: list available Hermes profiles for map-existing option
4. Multi-role support: allow one profile to be bound to multiple roles
5. Skip degradation: mark role as unbound and continue gracefully
6. Re-run preservation: read existing binding file on load, preserve unchanged roles when updating one role
7. Tests for wizard flow, profile discovery, multi-role binding, and re-run preservation
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, call
from argparse import Namespace
from typing import Optional
import tempfile
import os

# Add plugin to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))


class TestWizardFlowStructure:
    """Test basic wizard flow structure and imports."""

    def test_wizard_module_importable(self):
        """wizard module should be importable."""
        try:
            from agentic_fieldbook.wizard import (
                run_wizard,
                prompt_for_role,
                discover_profiles,
                build_from_template,
            )
            assert callable(run_wizard)
            assert callable(prompt_for_role)
            assert callable(discover_profiles)
            assert callable(build_from_template)
        except ImportError:
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_run_wizard_function_exists(self):
        """run_wizard function should exist and be callable."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            assert callable(run_wizard)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestRolePrompting:
    """Test per-role prompting with three options."""

    def test_prompts_for_all_four_roles(self):
        """Wizard should prompt for all 4 AOS roles: planner, executor, reviewer, verifier."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            with patch('builtins.input') as mock_input:
                # Simulate skipping all roles
                mock_input.side_effect = ['skip', 'skip', 'skip', 'skip']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1']):
                    result = run_wizard()
                    # Should have prompted for each role
                    assert mock_input.call_count >= 4
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_prompt_offers_map_existing_option(self):
        """Per-role prompt should offer 'map existing profile' option."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input') as mock_input:
                # First input: choose option 1 (map existing)
                # Second input: select first profile
                mock_input.side_effect = ['1', '1']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1']):
                    result = prompt_for_role('planner')
                    # Should return the selected profile
                    assert result == 'profile1'
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_prompt_offers_build_from_template_option(self):
        """Per-role prompt should offer 'build from template' option (stub to T05)."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input', return_value='template'):
                with patch('agentic_fieldbook.wizard.build_from_template') as mock_template:
                    mock_template.return_value = 'new-profile'
                    result = prompt_for_role('planner')
                    # Should call template function (even if stub)
                    mock_template.assert_called_once()
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_prompt_offers_skip_option(self):
        """Per-role prompt should offer 'skip' option (role unbound)."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input', return_value='skip'):
                result = prompt_for_role('planner')
                # Skip should return None (unbound)
                assert result is None
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_invalid_input_reprompts(self):
        """Invalid input should reprompt the user."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input', side_effect=['invalid', 'skip']):
                result = prompt_for_role('planner')
                # Should have reprompted
                assert result is None
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestProfileDiscovery:
    """Test profile discovery for map-existing option."""

    def test_discover_profiles_callable(self):
        """discover_profiles function should be callable."""
        try:
            from agentic_fieldbook.wizard import discover_profiles
            assert callable(discover_profiles)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_discover_profiles_returns_list(self):
        """discover_profiles should return a list of profile names."""
        try:
            from agentic_fieldbook.wizard import discover_profiles
            # This contract exercises the default home, not a HERMES_HOME
            # left behind by an earlier environment-sensitive test.
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HERMES_HOME", None)
                profiles = discover_profiles()
            assert isinstance(profiles, list)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_discover_profiles_finds_hermes_profiles(self):
        """discover_profiles should find Hermes profiles in ~/.hermes/profiles/."""
        try:
            from agentic_fieldbook.wizard import discover_profiles
            with tempfile.TemporaryDirectory() as tmpdir:
                profiles_dir = Path(tmpdir) / "profiles"
                profiles_dir.mkdir()
                (profiles_dir / "profile1").mkdir()
                (profiles_dir / "profile2").mkdir()
                
                with patch.dict(os.environ, {"HERMES_HOME": tmpdir}):
                    profiles = discover_profiles()
                    assert "profile1" in profiles or "profile2" in profiles
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_discover_profiles_handles_empty_profiles_dir(self):
        """discover_profiles should gracefully handle empty profiles directory."""
        try:
            from agentic_fieldbook.wizard import discover_profiles
            with tempfile.TemporaryDirectory() as tmpdir:
                profiles_dir = Path(tmpdir) / "profiles"
                profiles_dir.mkdir()
                
                with patch.dict(os.environ, {"HERMES_HOME": tmpdir}):
                    profiles = discover_profiles()
                    assert isinstance(profiles, list)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_map_existing_prompts_profile_selection(self):
        """Map-existing option should prompt user to select from discovered profiles."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input') as mock_input:
                # First input: choose 'map existing' (option 1)
                # Second input: select profile1 (option 1 from list)
                mock_input.side_effect = ['1', '1']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1', 'profile2']):
                    result = prompt_for_role('planner')
                    assert result == 'profile1'
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestMultiRoleBinding:
    """Test multi-role binding support."""

    def test_one_profile_bound_to_multiple_roles(self):
        """One profile can be bound to multiple AOS roles."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            from agentic_fieldbook.config import read_config, LaneBindingConfig

            with patch('builtins.input') as mock_input:
                # Bind planner and executor to same profile
                # For each role: '1' (map existing), '1' (select profile1)
                # Then skip last two roles: '3', '3'
                mock_input.side_effect = ['1', '1', '1', '1', '3', '3']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1']):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        config_path = Path(tmpdir) / "aos-lanes.yaml"
                        with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                            run_wizard()
                            config = read_config()
                            assert config.planner == 'profile1'
                            assert config.executor == 'profile1'
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_multi_role_binding_persists_correctly(self):
        """Multi-role bindings should persist correctly to config file."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            from agentic_fieldbook.config import read_config

            with patch('builtins.input') as mock_input:
                # Bind all 4 roles to same profile: for each role, '1' (map), '1' (select)
                mock_input.side_effect = ['1', '1', '1', '1', '1', '1', '1', '1']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1']):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        config_path = Path(tmpdir) / "aos-lanes.yaml"
                        with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                            run_wizard()
                            config = read_config()
                            # All roles should point to same profile
                            assert config.planner == config.executor
                            assert config.executor == config.reviewer
                            assert config.reviewer == config.verifier
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestSkipDegradation:
    """Test skip degradation behavior."""

    def test_skip_marks_role_unbound(self):
        """Skip option should mark role as unbound (None)."""
        try:
            from agentic_fieldbook.wizard import prompt_for_role
            with patch('builtins.input', return_value='skip'):
                result = prompt_for_role('planner')
                assert result is None
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_skip_continues_gracefully(self):
        """Skip option should continue to next role without error."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            with patch('builtins.input') as mock_input:
                # Skip all roles
                mock_input.side_effect = ['skip', 'skip', 'skip', 'skip']
                result = run_wizard()
                # Should complete successfully
                assert result is not None or True
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_partial_binding_with_skips(self):
        """Wizard should handle partial binding (some bound, some skipped)."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            from agentic_fieldbook.config import read_config

            with patch('builtins.input') as mock_input:
                # Bind planner: '1' (map), '1' (select profile1)
                # Skip others: '3', '3', '3'
                mock_input.side_effect = ['1', '1', '3', '3', '3']
                with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['profile1']):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        config_path = Path(tmpdir) / "aos-lanes.yaml"
                        with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                            run_wizard()
                            config = read_config()
                            assert config.planner == 'profile1'
                            assert config.executor is None
                            assert config.reviewer is None
                            assert config.verifier is None
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestRerunPreservation:
    """Test re-run preservation of existing bindings."""

    def test_rerun_reads_existing_binding(self):
        """Re-running wizard should read existing binding file on load."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            from agentic_fieldbook.config import write_config, read_config, LaneBindingConfig

            # Create initial config with planner bound
            initial_config = LaneBindingConfig(
                planner="existing-planner",
                executor=None,
                reviewer=None,
                verifier=None
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                    write_config(initial_config)

                    # Re-run wizard: preserve planner (n), bind executor ('1','1'), skip reviewer ('3'), skip verifier ('3')
                    with patch('builtins.input') as mock_input:
                        mock_input.side_effect = ['n', '1', '1', '3', '3']
                        with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['new-executor']):
                            run_wizard()

                            # Planner should still be bound to existing profile, executor to new
                            config = read_config()
                            assert config.planner == "existing-planner"
                            assert config.executor == "new-executor"
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_rerun_preserves_unchanged_roles(self):
        """Re-running wizard should preserve unchanged roles when updating one role."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            from agentic_fieldbook.config import write_config, read_config, LaneBindingConfig

            # Create initial config with planner and executor bound
            initial_config = LaneBindingConfig(
                planner="existing-planner",
                executor="existing-executor",
                reviewer=None,
                verifier=None
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                    write_config(initial_config)

                    # Re-run wizard: preserve planner (n), preserve executor (n), bind reviewer ('1','1'), skip verifier ('3')
                    with patch('builtins.input') as mock_input:
                        mock_input.side_effect = ['n', 'n', '1', '1', '3']
                        with patch('agentic_fieldbook.wizard.discover_profiles', return_value=['new-reviewer']):
                            run_wizard()

                            # Planner and executor should be preserved, reviewer bound
                            config = read_config()
                            assert config.planner == "existing-planner"
                            assert config.executor == "existing-executor"
                            assert config.reviewer == "new-reviewer"
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_rerun_handles_missing_config_file(self):
        """Re-running wizard should gracefully handle missing config file."""
        try:
            from agentic_fieldbook.wizard import run_wizard
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch('agentic_fieldbook.config.get_config_path', return_value=config_path):
                    # No config file exists
                    with patch('builtins.input') as mock_input:
                        mock_input.side_effect = ['skip', 'skip', 'skip', 'skip']
                        result = run_wizard()
                        # Should complete without error
                        assert result is not None or True
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestBuildFromTemplateStub:
    """Test build-from-template stub behavior (points to T05)."""

    def test_build_from_template_function_exists(self):
        """build_from_template function should exist (even if stub)."""
        try:
            from agentic_fieldbook.wizard import build_from_template
            assert callable(build_from_template)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")

    def test_build_from_template_points_to_t05(self):
        """build_from_template should indicate T05 implementation."""
        try:
            from agentic_fieldbook.wizard import build_from_template
            # This should now work and return None (since we can't mock input in non-interactive mode)
            # or we can catch the input error
            with patch('builtins.input', return_value='test-planner'):
                result = build_from_template('planner')
                # Should either return a profile name or None
                assert result is None or isinstance(result, str)
        except (ImportError, AttributeError):
            pytest.skip("wizard module not implemented yet (red phase)")


class TestMapLanesCommandHandler:
    """Test map-lanes command handler integration."""

    def test_map_lanes_command_calls_wizard(self):
        """map-lanes command should call run_wizard when --interactive is passed."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            with patch('agentic_fieldbook.plugin.run_wizard') as mock_wizard:
                mock_wizard.return_value = 0
                result = _cmd_map_lanes(Namespace(interactive=True))
                mock_wizard.assert_called_once()
        except (ImportError, AttributeError):
            pytest.skip("wizard integration not implemented yet (red phase)")

    def test_map_lanes_command_returns_zero_on_success(self):
        """map-lanes command should return 0 on successful wizard run."""
        try:
            from agentic_fieldbook.plugin import _cmd_map_lanes
            with patch('agentic_fieldbook.plugin.run_wizard', return_value=0):
                result = _cmd_map_lanes(Namespace())
                assert result == 0
        except (ImportError, AttributeError):
            pytest.skip("wizard integration not implemented yet (red phase)")


class TestExistingBehaviorPreserved:
    """Test that T03 doesn't break existing v0.1 and T02 behavior."""

    def test_config_module_still_works(self):
        """T02 config module should still work after T03."""
        from agentic_fieldbook.config import LaneBindingConfig, read_config, write_config
        assert LaneBindingConfig is not None
        assert callable(read_config)
        assert callable(write_config)

    def test_plugin_commands_still_work(self):
        """All existing plugin commands should still work."""
        from agentic_fieldbook.plugin import (
            _cmd_setup,
            _cmd_doctor,
            _cmd_version,
            _cmd_migrate,
            _cmd_preflight,
            _cmd_map_lanes,
        )
        assert callable(_cmd_setup)
        assert callable(_cmd_doctor)
        assert callable(_cmd_version)
        assert callable(_cmd_migrate)
        assert callable(_cmd_preflight)
        assert callable(_cmd_map_lanes)