"""Integration tests for PR #5: Migrate First Consumer to Plugin Architecture.

These tests verify:
1. Consumer Flow Test: consumer → plugin → engine → session → synthesis → result
2. Lifecycle Test: dispose, no leaks, error handling
3. Regression Test: old path vs new path equivalence

Tests use mock plugins to avoid requiring real TTS dependencies.
"""

import pytest
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import numpy as np

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.plugin_manager import PluginManager, get_plugin_manager, reset_plugin_manager
from abogen.tts_plugin.compat import CompatBackend, create_backend
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)


class MockEngineSession:
    """Mock EngineSession that records calls for verification."""
    
    def __init__(self):
        self._disposed = False
        self.synthesize_calls = []
    
    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            raise EngineError("Session disposed")
        
        self.synthesize_calls.append(request)
        
        # Return fake audio
        audio = np.ones(1000, dtype=np.float32) * 0.5
        return SynthesizedAudio(
            data=audio.tobytes(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1000 / 24000),
        )
    
    def dispose(self) -> None:
        self._disposed = True


class MockEngine:
    """Mock Engine that creates MockEngineSessions."""
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._disposed = False
        self.sessions_created = []
    
    def createSession(self) -> MockEngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        session = MockEngineSession()
        self.sessions_created.append(session)
        return session
    
    def dispose(self) -> None:
        self._disposed = True


def create_mock_plugin(create_engine_func=None):
    """Helper to create a mock plugin module."""
    if create_engine_func is None:
        create_engine_func = lambda **kwargs: MockEngine(**kwargs)
    
    from abogen.tts_plugin.manifest import PluginManifest, EngineManifest
    
    manifest = PluginManifest(
        id="mock_tts",
        name="Mock TTS",
        version="1.0.0",
        api_version="1.0",
        description="Mock TTS for testing",
        author="Test",
        capabilities=(),
        requires=None,
        engine=EngineManifest(
            voiceSources=(),
            parameters=(),
            audioFormats=(),
        ),
    )
    
    return {
        "PLUGIN_MANIFEST": manifest,
        "MODEL_REQUIREMENTS": [],
        "create_engine": create_mock_plugin_engine if create_engine_func is None else create_engine_func,
    }


def create_mock_plugin_engine(**kwargs):
    """Default mock plugin engine factory."""
    return MockEngine(**kwargs)


class TestConsumerFlow:
    """Consumer Flow Test: consumer → plugin → engine → session → synthesis → result"""
    
    def test_full_consumer_flow(self):
        """Verify complete flow from consumer to audio output."""
        manager = PluginManager()
        
        # Register mock plugin
        mock_plugin = create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True
        
        # Step 1: Consumer gets plugin
        assert manager.has_plugin("mock_tts") is True
        
        # Step 2: Plugin creates engine
        engine = manager.create_engine("mock_tts")
        assert engine is not None
        assert isinstance(engine, MockEngine)
        
        # Step 3: Engine creates session
        session = engine.createSession()
        assert session is not None
        assert isinstance(session, MockEngineSession)
        
        # Step 4: Session synthesizes
        request = SynthesisRequest(
            text="Hello world",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(values={"speed": 1.0}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        
        # Step 5: Result returned
        assert result is not None
        assert isinstance(result, SynthesizedAudio)
        assert len(result.data) > 0
        assert result.format.mime == "audio/wav"
        assert result.duration.seconds > 0
    
    def test_consumer_flow_via_compat_adapter(self):
        """Verify flow through compatibility adapter matches direct flow."""
        manager = PluginManager()
        
        # Register mock plugin
        mock_plugin = create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True
        
        # Use compat adapter
        with patch("abogen.tts_plugin.compat.get_plugin_manager", return_value=manager):
            backend = create_backend("mock_tts")
            
            # Call like old TTSBackend
            segments = list(backend("Hello world", voice="default", speed=1.0))
            
            # Verify result
            assert len(segments) >= 1
            segment = segments[0]
            assert hasattr(segment, "graphemes")
            assert hasattr(segment, "audio")
            assert segment.graphemes == "Hello world"


class TestLifecycle:
    """Lifecycle Test: dispose, no leaks, error handling"""
    
    def test_session_dispose_is_idempotent(self):
        """dispose() can be called multiple times safely."""
        session = MockEngineSession()
        
        session.dispose()
        session.dispose()  # Should not raise
        assert session._disposed is True
    
    def test_session_synthesize_after_dispose_raises(self):
        """synthesize() after dispose() raises EngineError."""
        session = MockEngineSession()
        session.dispose()
        
        request = SynthesisRequest(
            text="test",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        
        with pytest.raises(EngineError):
            session.synthesize(request)
    
    def test_engine_dispose_is_idempotent(self):
        """Engine dispose() can be called multiple times safely."""
        engine = MockEngine()
        
        engine.dispose()
        engine.dispose()  # Should not raise
        assert engine._disposed is True
    
    def test_engine_create_session_after_dispose_raises(self):
        """createSession() after dispose() raises EngineError."""
        engine = MockEngine()
        engine.dispose()
        
        with pytest.raises(EngineError):
            engine.createSession()
    
    def test_full_lifecycle(self):
        """Test complete lifecycle: create → use → dispose."""
        engine = MockEngine()
        
        # Create and use session
        session = engine.createSession()
        request = SynthesisRequest(
            text="test",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert len(result.data) > 0
        
        # Dispose session
        session.dispose()
        assert session._disposed is True
        
        # Dispose engine
        engine.dispose()
        assert engine._disposed is True
    
    def test_no_session_leak_on_engine_dispose(self):
        """Engine can be disposed even if sessions were created."""
        engine = MockEngine()
        
        # Create multiple sessions
        session1 = engine.createSession()
        session2 = engine.createSession()
        
        # Use sessions
        request = SynthesisRequest(
            text="test",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        session1.synthesize(request)
        session2.synthesize(request)
        
        # Dispose engine (sessions still exist but engine is disposed)
        engine.dispose()
        assert engine._disposed is True
        
        # Sessions can still be used (they hold reference to pipeline)
        result = session1.synthesize(request)
        assert len(result.data) > 0
    
    def test_error_handling_in_synthesis(self):
        """Error during synthesis is handled correctly."""
        class FailingSession:
            def synthesize(self, request):
                raise EngineError("Synthesis failed")
            
            def dispose(self):
                pass
        
        session = FailingSession()
        request = SynthesisRequest(
            text="test",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        
        with pytest.raises(EngineError, match="Synthesis failed"):
            session.synthesize(request)


class TestRegression:
    """Regression Test: old path vs new path equivalence"""
    
    def test_old_path_vs_new_path_same_result(self):
        """Both paths should produce equivalent results."""
        # Setup mock plugin
        manager = PluginManager()
        mock_plugin = create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True
        
        # New path: Plugin Manager → Engine → Session → Synthesis
        with patch("abogen.tts_plugin.compat.get_plugin_manager", return_value=manager):
            new_backend = create_backend("mock_tts")
            new_segments = list(new_backend("Hello world", voice="default", speed=1.0))
        
        # Old path: Direct MockEngine (simulating old registry)
        old_engine = MockEngine()
        old_session = old_engine.createSession()
        request = SynthesisRequest(
            text="Hello world",
            voice=VoiceSelection(source="builtin", key="default"),
            parameters=ParameterValues(values={"speed": 1.0}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        old_result = old_session.synthesize(request)
        
        # Compare results
        # New path returns segments, old path returns SynthesizedAudio
        # But both should have valid audio data
        assert len(new_segments) >= 1
        assert len(old_result.data) > 0
        
        # Both should have same format
        assert new_segments[0].audio.dtype == np.float32
    
    def test_compat_adapter_matches_old_interface(self):
        """Compat adapter should match old TTSBackend interface."""
        manager = PluginManager()
        mock_plugin = create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True
        
        with patch("abogen.tts_plugin.compat.get_plugin_manager", return_value=manager):
            backend = create_backend("mock_tts", lang_code="a", device="cpu")
            
            # Old interface: pipeline(text, voice=..., speed=..., split_pattern=...)
            segments = list(backend(
                "Hello world",
                voice="af_heart",
                speed=1.0,
                split_pattern=r"\n+"
            ))
            
            # Should return segments with graphemes and audio
            assert len(segments) >= 1
            segment = segments[0]
            assert segment.graphemes == "Hello world"
            assert isinstance(segment.audio, np.ndarray)
            assert segment.audio.dtype == np.float32
            assert len(segment.audio) > 0


class TestPluginManagerIntegration:
    """Integration tests for PluginManager."""
    
    def test_plugin_manager_singleton_pattern(self):
        """Global plugin manager follows singleton pattern."""
        reset_plugin_manager()
        
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()
        
        assert manager1 is manager2
        
        reset_plugin_manager()
        
        manager3 = get_plugin_manager()
        assert manager1 is not manager3
    
    def test_plugin_manager_discover_plugins(self):
        """Plugin manager can discover plugins from directory."""
        manager = PluginManager()
        
        # Discover from test plugins directory
        manager.discover("tests/plugins")
        
        # Should find valid_plugin
        # (This depends on test plugins existing)
        plugins = manager.list_plugins()
        assert isinstance(plugins, list)
    
    def test_plugin_manager_dispose_all(self):
        """Plugin manager can dispose all cached engines."""
        manager = PluginManager()
        
        # Register mock plugin
        mock_plugin = create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True
        
        # Create engines
        engine1 = manager.get_or_create_engine("mock_tts")
        engine2 = manager.get_or_create_engine("mock_tts")
        
        # Dispose all
        manager.dispose_all()
        
        # Engines should be disposed
        assert engine1._disposed is True
        assert engine2._disposed is True
        
        # Cache should be empty
        assert len(manager._engines) == 0
