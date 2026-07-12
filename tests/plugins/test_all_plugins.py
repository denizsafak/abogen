"""Auto-discovery tests for all TTS plugins.

These tests automatically run for every plugin in the plugins/ directory.
Tests are grouped into three categories:

1. TestAllPluginsManifest - Validates manifest structure
   - Required fields (id, name, version, api_version, etc.)
   - API version format (semver MAJOR.MINOR)
   - Voices field (optional)

2. TestAllPluginsEngine - Validates engine lifecycle
   - create_engine returns valid Engine
   - dispose is idempotent
   - dispose → createSession raises EngineError

3. TestAllPluginsCapabilities - Validates capability implementation
   - Declared capabilities are implemented
   - voice_list → VoiceLister interface
"""

from __future__ import annotations

import re

import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import EngineConfig, VoiceSelection, AudioFormat, ParameterValues, SynthesisRequest


class TestAllPluginsManifest:
    """Test that all plugins have valid manifest structure."""

    def test_manifest_has_required_fields(self, loaded_plugin):
        """Verify manifest has all required fields."""
        manifest = loaded_plugin.manifest
        assert manifest is not None
        
        # Required fields
        assert manifest.id, "Plugin id must not be empty"
        assert manifest.name, "Plugin name must not be empty"
        assert manifest.version, "Plugin version must not be empty"
        assert manifest.api_version, "Plugin api_version must not be empty"
        assert manifest.description, "Plugin description must not be empty"
        assert manifest.author, "Plugin author must not be empty"

    def test_manifest_id_matches_directory(self, loaded_plugin, plugin_dir):
        """Verify manifest id matches the plugin directory name."""
        manifest = loaded_plugin.manifest
        assert manifest.id == plugin_dir.name, \
            f"Manifest id '{manifest.id}' must match directory name '{plugin_dir.name}'"

    def test_api_version_format(self, loaded_plugin):
        """Verify api_version follows semver format (MAJOR.MINOR)."""
        manifest = loaded_plugin.manifest
        api_version = manifest.api_version
        
        # Must match MAJOR.MINOR format
        pattern = r"^\d+\.\d+$"
        assert re.match(pattern, api_version), \
            f"api_version '{api_version}' must be in format MAJOR.MINOR (e.g., 1.0)"

    def test_api_version_compatibility(self, loaded_plugin):
        """Verify api_version major version matches host API version."""
        from abogen.tts_plugin.loader import HOST_API_VERSION
        
        manifest = loaded_plugin.manifest
        plugin_ver = manifest.api_version
        host_ver = HOST_API_VERSION
        
        # Extract major versions
        plugin_major = int(plugin_ver.split(".")[0])
        host_major = int(host_ver.split(".")[0])
        
        assert plugin_major == host_major, \
            f"API version major mismatch: plugin={plugin_major}, host={host_major}"

    def test_voices_field_is_optional(self, loaded_plugin):
        """Verify voices field is optional (can be None or tuple)."""
        manifest = loaded_plugin.manifest
        voices = manifest.voices
        
        # voices can be None (not declared) or tuple (empty or with voices)
        assert voices is None or isinstance(voices, tuple), \
            f"voices must be None or tuple, got {type(voices).__name__}"

    def test_capabilities_is_tuple(self, loaded_plugin):
        """Verify capabilities is a tuple."""
        manifest = loaded_plugin.manifest
        assert isinstance(manifest.capabilities, tuple), \
            f"capabilities must be a tuple, got {type(manifest.capabilities).__name__}"

    def test_engine_manifest_exists(self, loaded_plugin):
        """Verify engine manifest exists and has required fields."""
        manifest = loaded_plugin.manifest
        engine_manifest = manifest.engine
        
        assert engine_manifest is not None
        assert isinstance(engine_manifest.voiceSources, tuple)
        assert isinstance(engine_manifest.parameters, tuple)
        assert isinstance(engine_manifest.audioFormats, tuple)


class TestAllPluginsEngine:
    """Test that all plugins satisfy the Engine contract."""

    def test_create_engine_returns_engine(self, loaded_plugin, host_context, engine_config):
        """Verify create_engine returns an Engine instance."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        assert isinstance(engine, Engine), \
            f"create_engine must return Engine instance, got {type(engine).__name__}"
        engine.dispose()

    def test_dispose_is_idempotent(self, loaded_plugin, host_context, engine_config):
        """Verify dispose can be called multiple times without error."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        
        # First dispose
        engine.dispose()
        
        # Second dispose should not raise
        engine.dispose()

    def test_create_session_after_dispose_raises(self, loaded_plugin, host_context, engine_config):
        """Verify createSession raises EngineError after dispose."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        engine.dispose()
        
        with pytest.raises(EngineError):
            engine.createSession()

    def test_dispose_after_dispose_raises(self, loaded_plugin, host_context, engine_config):
        """Verify dispose after dispose does not raise (idempotent)."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        engine.dispose()
        
        # Should not raise
        engine.dispose()

    def test_create_session_returns_valid_session(self, loaded_plugin, host_context, engine_config):
        """Verify createSession returns an EngineSession instance."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        session = engine.createSession()
        
        assert isinstance(session, EngineSession), \
            f"createSession must return EngineSession instance, got {type(session).__name__}"
        session.dispose()
        engine.dispose()

    def test_session_dispose_is_idempotent(self, loaded_plugin, host_context, engine_config):
        """Verify session dispose can be called multiple times."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        session = engine.createSession()
        
        # First dispose
        session.dispose()
        
        # Second dispose should not raise
        session.dispose()
        engine.dispose()

    def test_session_synthesize_after_dispose_raises(self, loaded_plugin, host_context, engine_config):
        """Verify session.synthesize raises EngineError after dispose."""
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        session = engine.createSession()
        session.dispose()
        
        # Create a minimal request (won't actually synthesize, just test error)
        request = SynthesisRequest(
            text="test",
            voice=VoiceSelection(source="test", key="test"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        
        with pytest.raises(EngineError):
            session.synthesize(request)
        engine.dispose()


class TestAllPluginsCapabilities:
    """Test that all plugins implement their declared capabilities."""

    def test_voice_list_capability(self, loaded_plugin, host_context, engine_config):
        """Verify plugins with 'voice_list' capability implement VoiceLister."""
        manifest = loaded_plugin.manifest
        
        if "voice_list" not in manifest.capabilities:
            pytest.skip("Plugin does not declare 'voice_list' capability")
        
        engine = loaded_plugin.create_engine(host_context, None, engine_config)
        
        # Check if listVoices method exists
        assert hasattr(engine, "listVoices"), \
            "Plugin with 'voice_list' capability must have listVoices method"
        
        # listVoices should be callable
        assert callable(engine.listVoices), "listVoices must be callable"
        
        # listVoices should return a list/tuple of voices
        # Get first voice source from manifest
        if manifest.engine.voiceSources:
            source_id = manifest.engine.voiceSources[0].id
            voices = engine.listVoices(source_id)
            
            assert isinstance(voices, (list, tuple)), \
                f"listVoices must return list or tuple, got {type(voices).__name__}"
            
            # Each voice should have id, name, tags
            for voice in voices:
                assert hasattr(voice, "id"), "Voice must have 'id' attribute"
                assert hasattr(voice, "name"), "Voice must have 'name' attribute"
                assert hasattr(voice, "tags"), "Voice must have 'tags' attribute"
                assert isinstance(voice.tags, tuple), "Voice tags must be a tuple"
        
        engine.dispose()

    def test_known_capabilities_are_valid(self, loaded_plugin):
        """Verify all declared capabilities are known."""
        manifest = loaded_plugin.manifest
        
        known_capabilities = frozenset({
            "voice_list",
            "preview",
            "voice_clone",
            "voice_blend",
            "streaming",
            "cancel",
        })
        
        for cap in manifest.capabilities:
            assert cap in known_capabilities, \
                f"Unknown capability: '{cap}'. Known capabilities: {known_capabilities}"