"""
Tests for AI Tool Definitions and Handlers.
"""
import pytest
import os
import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))


class TestToolDefinitions:
    """Test tool definition schemas."""

    def test_run_web_agent_tool_schema(self):
        """Test run_web_agent tool has correct schema."""
        from ada import run_web_agent

        assert run_web_agent['name'] == 'run_web_agent'
        assert 'description' in run_web_agent
        assert 'parameters' in run_web_agent
        assert 'prompt' in run_web_agent['parameters']['properties']
        print(f"run_web_agent tool: {run_web_agent['name']}")

    def test_list_projects_tool_schema(self):
        """Test list_projects tool has correct schema."""
        from ada import list_projects_tool

        assert list_projects_tool['name'] == 'list_projects'
        print(f"list_projects tool: {list_projects_tool['name']}")


class TestAudioLoopClass:
    """Test AudioLoop class structure."""

    def test_audioloop_class_exists(self):
        """Test AudioLoop class can be imported."""
        from ada import AudioLoop
        assert AudioLoop is not None
        print("AudioLoop class imported successfully")

    def test_audioloop_methods(self):
        """Test AudioLoop has required methods."""
        from ada import AudioLoop

        required_methods = [
            'run',
            'stop',
            'send_frame',
            'listen_audio',
            'receive_audio',
            'play_audio',
            'handle_web_agent_request',
            'resolve_tool_confirmation',
            'update_permissions',
            'set_paused',
            'clear_audio_queue',
        ]

        for method in required_methods:
            assert hasattr(AudioLoop, method), f"Missing method: {method}"
            print(f"  ✓ {method}")


class TestFileOperations:
    """Test file operation handlers."""

    def test_read_directory_method_exists(self):
        """Test handle_read_directory exists."""
        from ada import AudioLoop
        assert hasattr(AudioLoop, 'handle_read_directory')

    def test_read_file_method_exists(self):
        """Test handle_read_file exists."""
        from ada import AudioLoop
        assert hasattr(AudioLoop, 'handle_read_file')

    def test_write_file_method_exists(self):
        """Test handle_write_file exists."""
        from ada import AudioLoop
        assert hasattr(AudioLoop, 'handle_write_file')


class TestLiveConnectConfig:
    """Test Gemini Live Connect configuration."""

    def test_config_exists(self):
        """Test config is defined."""
        from ada import config
        assert config is not None
        print("LiveConnectConfig exists")

    def test_config_has_audio_modality(self):
        """Test config includes audio modality."""
        from ada import config
        assert 'AUDIO' in config.response_modalities
        print("Audio modality configured")


class TestToolPermissions:
    """Test tool permission handling."""

    def test_update_permissions_method(self):
        """Test update_permissions method exists."""
        from ada import AudioLoop
        assert hasattr(AudioLoop, 'update_permissions')
        print("update_permissions method exists")


class TestAgentImports:
    """Test agent module imports in ada.py."""

    def test_web_agent_import(self):
        """Test WebAgent is imported."""
        from ada import WebAgent
        assert WebAgent is not None
        print("WebAgent imported")


class TestToolConfirmation:
    """Test tool confirmation handling."""

    def test_resolve_tool_confirmation_method(self):
        """Test resolve_tool_confirmation exists."""
        from ada import AudioLoop
        assert hasattr(AudioLoop, 'resolve_tool_confirmation')
        print("resolve_tool_confirmation method exists")