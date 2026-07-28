"""Tests for version-gap detection and update prompt state."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Now load the module
plugin_root = Path(__file__).parent.parent
sys.path.insert(0, str(plugin_root))

import importlib.util
spec = importlib.util.spec_from_file_location("_root_init", plugin_root / "__init__.py")
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load root __init__.py from {plugin_root / '__init__.py'}")
_root_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_root_module)

_load_plugin_state = _root_module._load_plugin_state
_save_plugin_state = _root_module._save_plugin_state
_get_latest_github_version = _root_module._get_latest_github_version
_get_available_version = _root_module._get_available_version
_check_and_prompt_version_update = _root_module._check_and_prompt_version_update
PLUGIN_VERSION = _root_module.PLUGIN_VERSION
_plugin_state_dir = _root_module._plugin_state_dir


@pytest.fixture(autouse=True)
def isolate_state():
    """Ensure each test has a clean state directory."""
    # Create a fresh temp directory for each test
    test_tmpdir = tempfile.mkdtemp()
    os.environ["HERMES_HOME"] = test_tmpdir
    
    yield
    
    # Cleanup after test
    import shutil
    if Path(test_tmpdir).exists():
        shutil.rmtree(test_tmpdir)


class MockContextManager:
    """Mock for urllib.request.urlopen that works as a context manager."""
    def __init__(self, data):
        self.data = data
    
    def __enter__(self):
        class MockResponse:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
        return MockResponse(self.data)
    
    def __exit__(self, *args):
        pass


class TestPluginState:
    """Test plugin state persistence."""

    def test_load_empty_state(self):
        """Load should return empty dict when state file doesn't exist."""
        state = _load_plugin_state()
        assert state == {}

    def test_save_and_load_state(self):
        """Save should persist state and load should retrieve it."""
        test_state = {"version_decisions": {"0.3.0": "skipped", "0.1.5": "applied"}}
        _save_plugin_state(test_state)
        loaded = _load_plugin_state()
        assert loaded == test_state

    def test_load_corrupted_state_returns_empty(self):
        """Load corrupted state should return empty dict."""
        state_dir = _plugin_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text("{invalid json")
        loaded = _load_plugin_state()
        assert loaded == {}


class TestGitHubVersionFetch:
    """Test GitHub version fetching."""

    def test_get_latest_github_version_success(self):
        """Should fetch and parse version from GitHub releases."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            success, version = _get_latest_github_version()
            assert success is True
            assert version == "0.3.0"

    def test_get_latest_github_version_without_v_prefix(self):
        """Should handle tags without 'v' prefix."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "0.2.0"}')):
            success, version = _get_latest_github_version()
            assert success is False  # Only tags with 'v' prefix are valid
            assert version == ""

    def test_get_latest_github_version_network_failure(self):
        """Should return failure on network errors."""
        import urllib.error
        
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network error")):
            success, version = _get_latest_github_version()
            assert success is False
            assert version == ""

    def test_get_available_version_fallback_on_failure(self):
        """Should fall back to current version when GitHub fetch fails."""
        with patch("urllib.request.urlopen", side_effect=Exception("error")):
            version = _get_available_version()
            assert version == PLUGIN_VERSION


class TestVersionGapDetection:
    """Test version-gap detection logic."""

    def test_no_gap_when_versions_match(self):
        """Should not prompt when available version matches installed."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(f'{{"tag_name": "v{PLUGIN_VERSION}"}}'.encode())):
            with patch("sys.stdin.isatty", return_value=True):
                # Should not prompt (no input call)
                with patch("builtins.input") as mock_input:
                    _check_and_prompt_version_update()
                    mock_input.assert_not_called()

    def test_gap_detected_prompts_user(self, capsys):
        """Should prompt user when version gap exists."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n"):
                    _check_and_prompt_version_update()
                    captured = capsys.readouterr()
                    assert "Update available: Agentic Fieldbook v0.3.0" in captured.out
                    assert "Your choices:" in captured.out
                    assert "[y] Apply update" in captured.out
                    assert "[s] Skip this version" in captured.out
                    assert "[n] Remind later" in captured.out

    def test_non_interactive_mode_skips_prompt(self):
        """Should skip prompt in non-interactive mode."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("builtins.input") as mock_input:
                    _check_and_prompt_version_update()
                    mock_input.assert_not_called()


class TestUpdateChoices:
    """Test the three user choice options."""

    def test_apply_choice_saves_decision(self, capsys):
        """Choice 'y' should save 'applied' decision."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="y"):
                    _check_and_prompt_version_update()
                    
                    state = _load_plugin_state()
                    assert state["version_decisions"]["0.3.0"] == "applied"
                    
                    captured = capsys.readouterr()
                    assert "pip install --upgrade" in captured.out

    def test_skip_choice_saves_decision(self, capsys):
        """Choice 's' should save 'skipped' decision."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="s"):
                    _check_and_prompt_version_update()
                    
                    state = _load_plugin_state()
                    assert state["version_decisions"]["0.3.0"] == "skipped"
                    
                    captured = capsys.readouterr()
                    assert "Skipped v0.3.0" in captured.out

    def test_remind_choice_saves_decision(self, capsys):
        """Choice 'n' should save 'remind_later' decision."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n"):
                    _check_and_prompt_version_update()
                    
                    state = _load_plugin_state()
                    assert state["version_decisions"]["0.3.0"] == "remind_later"
                    
                    captured = capsys.readouterr()
                    assert "Reminder set" in captured.out


class TestDecisionPersistence:
    """Test that decisions persist and suppress re-prompts."""

    def test_skipped_version_does_not_reprompt(self):
        """A skipped version should not prompt again."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                # First run: skip
                with patch("builtins.input", return_value="s"):
                    _check_and_prompt_version_update()
                
                # Second run: should not prompt
                with patch("builtins.input") as mock_input:
                    _check_and_prompt_version_update()
                    # Input should not be called
                    mock_input.assert_not_called()

    def test_remind_later_version_does_not_reprompt(self):
        """A remind_later version should not prompt again."""
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                # First run: remind later
                with patch("builtins.input", return_value="n"):
                    _check_and_prompt_version_update()
                
                # Second run: should not prompt
                with patch("builtins.input") as mock_input:
                    _check_and_prompt_version_update()
                    # Input should not be called
                    mock_input.assert_not_called()


class TestNewerVersionRePrompt:
    """Test that a newer version prompts again even after skipping an old version."""

    def test_newer_version_prompts_after_skip(self, capsys):
        """After skipping v0.3.0, v0.3.0 should still prompt."""
        # Save a decision for v0.3.0
        _save_plugin_state({"version_decisions": {"0.2.0": "skipped"}})
        
        # Fetch returns v0.3.0
        with patch("urllib.request.urlopen", return_value=MockContextManager(b'{"tag_name": "v0.3.0"}')):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n") as mock_input:
                    _check_and_prompt_version_update()
                    # Should prompt for v0.3.0
                    mock_input.assert_called_once()
                    
                    captured = capsys.readouterr()
                    assert "v0.3.0" in captured.out