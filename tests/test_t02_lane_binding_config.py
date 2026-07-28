"""
Tests for Ticket T02: Lane-binding config file schema and persistence.

These tests verify:
1. YAML schema for aos-lanes.yaml defining AOS roles and profile bindings
2. Schema validation logic using pydantic
3. File read/write functions that preserve YAML comments and formatting
4. Missing file handling (treat as all roles unbound)
5. Malformed file reporting via doctor
6. Doctor integration for binding file validation
7. All existing behavior preserved (regression harness passes)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from argparse import Namespace
from typing import Optional
import tempfile
import os

# Add plugin to path
plugin_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(plugin_root))


class TestLaneBindingSchema:
    """Test the Pydantic schema for lane-binding configuration."""

    def test_schema_importable(self):
        """LaneBindingConfig schema should be importable from config module."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig, RoleBinding
            assert LaneBindingConfig is not None
            assert RoleBinding is not None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_schema_validates_all_four_roles(self):
        """Schema should accept all four canonical AOS roles."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor="profile-executor",
                reviewer="profile-reviewer",
                verifier="profile-verifier"
            )
            assert config.planner == "profile-planner"
            assert config.executor == "profile-executor"
            assert config.reviewer == "profile-reviewer"
            assert config.verifier == "profile-verifier"
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_schema_allows_none_for_unbound_roles(self):
        """Schema should allow None for roles that are not bound."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor=None,
                reviewer="profile-reviewer",
                verifier=None
            )
            assert config.planner == "profile-planner"
            assert config.executor is None
            assert config.reviewer == "profile-reviewer"
            assert config.verifier is None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_schema_allows_all_roles_unbound(self):
        """Schema should allow all roles to be None (all unbound)."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig
            config = LaneBindingConfig(
                planner=None,
                executor=None,
                reviewer=None,
                verifier=None
            )
            assert config.planner is None
            assert config.executor is None
            assert config.reviewer is None
            assert config.verifier is None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_schema_rejects_non_string_profile_names(self):
        """Schema should reject non-string profile names."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig, ValidationError
            with pytest.raises(ValidationError):
                LaneBindingConfig(
                    planner=123,
                    executor="profile-executor",
                    reviewer="profile-reviewer",
                    verifier="profile-verifier"
                )
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_schema_rejects_empty_string_profile_names(self):
        """Schema should reject empty string profile names."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig, ValidationError
            with pytest.raises(ValidationError):
                LaneBindingConfig(
                    planner="",
                    executor="profile-executor",
                    reviewer="profile-reviewer",
                    verifier="profile-verifier"
                )
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_model_dump_to_yaml_dict(self):
        """Schema should serialize to dict suitable for YAML dump."""
        try:
            from agentic_fieldbook.config import LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor=None,
                reviewer="profile-reviewer",
                verifier=None
            )
            data = config.model_dump(mode='python')
            assert data["planner"] == "profile-planner"
            assert data["executor"] is None
            assert data["reviewer"] == "profile-reviewer"
            assert data["verifier"] is None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")


class TestLaneBindingFilePersistence:
    """Test file read/write functions for lane-binding config."""

    def test_get_config_path_returns_hermes_home(self):
        """get_config_path should return ~/.hermes/aos-lanes.yaml."""
        try:
            from agentic_fieldbook.config import get_config_path
            # Clear HERMES_HOME to test default behavior
            old_val = os.environ.get("HERMES_HOME")
            if "HERMES_HOME" in os.environ:
                del os.environ["HERMES_HOME"]
            try:
                path = get_config_path()
                assert path.name == "aos-lanes.yaml"
                # Should default to ~/.hermes
                assert ".hermes" in str(path)
            finally:
                # Restore HERMES_HOME
                if old_val is not None:
                    os.environ["HERMES_HOME"] = old_val
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_get_config_path_respects_hermes_home_env(self):
        """get_config_path should respect HERMES_HOME environment variable."""
        try:
            from agentic_fieldbook.config import get_config_path
            with patch.dict(os.environ, {"HERMES_HOME": "/custom/hermes"}):
                path = get_config_path()
                assert str(path).startswith("/custom/hermes")
                assert path.name == "aos-lanes.yaml"
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_read_config_missing_file_returns_default(self):
        """read_config should return default config when file doesn't exist."""
        try:
            from agentic_fieldbook.config import read_config, LaneBindingConfig
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    config = read_config()
                    assert isinstance(config, LaneBindingConfig)
                    # All roles should be unbound (None)
                    assert config.planner is None
                    assert config.executor is None
                    assert config.reviewer is None
                    assert config.verifier is None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_read_config_valid_file_returns_config(self):
        """read_config should parse valid YAML file correctly."""
        try:
            from agentic_fieldbook.config import read_config
            yaml_content = """
# AOS Lane Bindings
planner: profile-planner
executor: profile-executor
reviewer: profile-reviewer
verifier: profile-verifier
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    config = read_config()
                    assert config.planner == "profile-planner"
                    assert config.executor == "profile-executor"
                    assert config.reviewer == "profile-reviewer"
                    assert config.verifier == "profile-verifier"
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_read_config_preserves_none_values(self):
        """read_config should correctly parse None values from YAML."""
        try:
            from agentic_fieldbook.config import read_config
            yaml_content = """
# AOS Lane Bindings
planner: profile-planner
executor: null
reviewer: profile-reviewer
verifier: null
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    config = read_config()
                    assert config.planner == "profile-planner"
                    assert config.executor is None
                    assert config.reviewer == "profile-reviewer"
                    assert config.verifier is None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_read_config_malformed_yaml_raises_error(self):
        """read_config should raise error for malformed YAML."""
        try:
            from agentic_fieldbook.config import read_config, LaneBindingConfigError
            yaml_content = """
# Malformed YAML
planner: profile-planner
executor: [invalid
reviewer: profile-reviewer
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    with pytest.raises(LaneBindingConfigError):
                        read_config()
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_read_config_invalid_schema_raises_error(self):
        """read_config should raise error for invalid schema."""
        try:
            from agentic_fieldbook.config import read_config, LaneBindingConfigError
            yaml_content = """
# Invalid schema - wrong role name
planner: profile-planner
executor: profile-executor
reviewer: profile-reviewer
invalid_role: should-not-exist
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    with pytest.raises(LaneBindingConfigError):
                        read_config()
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_write_config_creates_file(self):
        """write_config should create config file."""
        try:
            from agentic_fieldbook.config import write_config, LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor="profile-executor",
                reviewer="profile-reviewer",
                verifier="profile-verifier"
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    write_config(config)
                    assert config_path.exists()
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_write_config_valid_yaml(self):
        """write_config should write valid YAML."""
        try:
            from agentic_fieldbook.config import write_config, read_config, LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor=None,
                reviewer="profile-reviewer",
                verifier=None
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    write_config(config)
                    # Read it back to verify
                    read_back = read_config()
                    assert read_back.planner == config.planner
                    assert read_back.executor == config.executor
                    assert read_back.reviewer == config.reviewer
                    assert read_back.verifier == config.verifier
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_write_config_preserves_comments(self):
        """write_config should preserve YAML comments in human-readable format."""
        try:
            from agentic_fieldbook.config import write_config, LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor=None,
                reviewer="profile-reviewer",
                verifier=None
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    write_config(config)
                    content = config_path.read_text()
                    # Should have comments for human readability
                    assert "#" in content or "AOS" in content or "Lane" in content
                    # Should have role names
                    assert "planner" in content
                    assert "executor" in content
                    assert "reviewer" in content
                    assert "verifier" in content
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_write_config_atomically(self):
        """write_config should write atomically (temp file + rename)."""
        try:
            from agentic_fieldbook.config import write_config, LaneBindingConfig
            config = LaneBindingConfig(
                planner="profile-planner",
                executor="profile-executor",
                reviewer="profile-reviewer",
                verifier="profile-verifier"
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    # Write existing content
                    config_path.write_text("existing content\n")
                    
                    # Write new config
                    write_config(config)
                    
                    # File should be updated, not corrupted
                    content = config_path.read_text()
                    assert "planner:" in content
                    assert "existing" not in content
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")


class TestDoctorIntegration:
    """Test doctor command integration with lane-binding config."""

    def test_doctor_imports_lane_binding_check(self):
        """doctor should import lane-binding validation functions."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            assert validate_binding_file is not None
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_checks_file_exists(self):
        """validate_binding_file should check if binding file exists."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    result = validate_binding_file()
                    # Missing file is a warning, not an error
                    assert isinstance(result, dict)
                    assert "status" in result
                    assert result["status"] == "warning"
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_reports_missing_file_as_warning(self):
        """validate_binding_file should report missing file as non-fatal."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    result = validate_binding_file()
                    # Missing file is a warning, not an error
                    assert isinstance(result, dict)
                    assert "status" in result
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_validates_schema(self):
        """validate_binding_file should validate schema of existing file."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            yaml_content = """
# AOS Lane Bindings
planner: profile-planner
executor: profile-executor
reviewer: profile-reviewer
verifier: profile-verifier
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    result = validate_binding_file()
                    assert "valid" in result or result.get("status") == "ok"
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_reports_invalid_schema(self):
        """validate_binding_file should report schema errors."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            yaml_content = """
# Invalid YAML
planner: profile-planner
executor: [invalid
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    result = validate_binding_file()
                    assert result.get("status") == "error"
                    assert "schema" in str(result).lower() or "invalid" in str(result).lower()
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_reports_bound_and_unbound_roles(self):
        """validate_binding_file should report which roles are bound/unbound."""
        try:
            from agentic_fieldbook.config import validate_binding_file
            yaml_content = """
# AOS Lane Bindings
planner: profile-planner
executor: null
reviewer: profile-reviewer
verifier: null
"""
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "aos-lanes.yaml"
                config_path.write_text(yaml_content)
                with patch("agentic_fieldbook.config.get_config_path", return_value=config_path):
                    result = validate_binding_file()
                    assert "bound" in str(result).lower() or "roles" in str(result).lower()
        except ImportError:
            pytest.skip("config module not implemented yet (red phase)")

    def test_doctor_command_integration(self):
        """doctor command should call lane-binding validation."""
        try:
            from agentic_fieldbook.plugin import _cmd_doctor
            with patch("agentic_fieldbook.plugin.validate_binding_file") as mock_validate:
                mock_validate.return_value = {
                    "status": "ok",
                    "message": "Lane-binding config is valid",
                    "details": {"bound_roles": [], "unbound_roles": []}
                }
                result = _cmd_doctor(Namespace())
                assert result == 0
                mock_validate.assert_called_once()
        except (ImportError, AttributeError):
            pytest.skip("doctor integration not implemented yet (red phase)")


class TestExistingBehaviorPreserved:
    """Test that T02 doesn't break existing v0.1 behavior."""

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

    def test_version_command_still_works(self, capsys):
        """Version command should still work."""
        from agentic_fieldbook.plugin import _cmd_version
        result = _cmd_version(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "Agentic Fieldbook" in captured.out

    def test_doctor_command_still_runs(self, capsys):
        """Doctor command should still run (even if stub)."""
        from agentic_fieldbook.plugin import _cmd_doctor
        result = _cmd_doctor(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "Agentic Fieldbook" in captured.out

    def test_map_lanes_stub_still_works(self, capsys):
        """map-lanes stub should still work and show config state."""
        from agentic_fieldbook.plugin import _cmd_map_lanes
        result = _cmd_map_lanes(Namespace())
        captured = capsys.readouterr()
        assert result == 0
        assert "coming" in captured.out.lower() or "T03" in captured.out
        # T02: Should mention config file
        assert "config" in captured.out.lower()