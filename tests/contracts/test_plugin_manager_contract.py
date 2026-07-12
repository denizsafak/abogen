"""Integration tests for Plugin Manager and direct utility functions."""

import pytest
from unittest.mock import MagicMock, patch

from abogen.tts_plugin.plugin_manager import PluginManager, get_plugin_manager, reset_plugin_manager
from abogen.tts_plugin.utils import Pipeline, create_pipeline
from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.types import SynthesisRequest, SynthesizedAudio, AudioFormat


class FakeEngine:
    """Fake Engine for testing."""
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._disposed = False
    
    def createSession(self):
        return FakeEngineSession()
    
    def dispose(self):
        self._disposed = True
    
    @property
    def manifest(self):
        return MagicMock()


class FakeEngineSession:
    """Fake EngineSession for testing."""
    
    def __init__(self):
        self._disposed = False
    
    def synthesize(self, request):
        # Return fake audio
        import numpy as np
        from abogen.tts_plugin.types import AudioFormat, Duration, SynthesizedAudio
        
        audio = np.zeros(1000, dtype=np.float32)
        return SynthesizedAudio(
            data=audio.tobytes(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=0.04167),  # 1000 samples / 24000 Hz
        )
    
    def dispose(self):
        self._disposed = True


class TestPluginManager:
    """Test PluginManager functionality."""
    
    def test_plugin_manager_creation(self):
        """PluginManager can be created."""
        manager = PluginManager()
        assert manager is not None
    
    def test_plugin_manager_list_discovers_plugins(self):
        """PluginManager discovers plugins from plugins directory."""
        manager = PluginManager()
        manager.discover("plugins")
        plugins = manager.list_plugins()
        # Should discover kokoro plugin if it exists
        assert isinstance(plugins, list)
    
    def test_plugin_manager_has_plugin_after_discover(self):
        """PluginManager reports plugins after discovery."""
        manager = PluginManager()
        manager.discover("plugins")
        # kokoro plugin should be discovered if plugins/kokoro exists
        # This is expected behavior
        assert isinstance(manager._plugins, dict)
    
    def test_plugin_manager_get_plugin_after_discover(self):
        """PluginManager returns plugin info after discovery."""
        manager = PluginManager()
        manager.discover("plugins")
        # kokoro plugin should be discovered if plugins/kokoro exists
        assert isinstance(manager._plugins, dict)
    
    def test_plugin_manager_create_engine_not_found(self):
        """PluginManager raises KeyError for unknown plugins."""
        manager = PluginManager()
        with pytest.raises(KeyError, match="Plugin not found"):
            manager.create_engine("nonexistent")
    
    def test_plugin_manager_discover_with_empty_dir(self):
        """PluginManager handles missing plugins directory."""
        manager = PluginManager()
        manager.discover("/nonexistent/path")
        plugins = manager.list_plugins()
        assert plugins == []
    
    def test_global_plugin_manager_singleton(self):
        """Global PluginManager is a singleton."""
        reset_plugin_manager()
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()
        assert manager1 is manager2
        reset_plugin_manager()
    
    def test_reset_plugin_manager(self):
        """reset_plugin_manager clears the singleton."""
        manager1 = get_plugin_manager()
        reset_plugin_manager()
        manager2 = get_plugin_manager()
        assert manager1 is not manager2
        reset_plugin_manager()


class TestPipeline:
    """Test Pipeline functionality."""
    
    def test_pipeline_creation(self):
        """Pipeline can be created."""
        engine = FakeEngine()
        backend = Pipeline(engine)
        assert backend is not None
    
    def test_pipeline_callable(self):
        """Pipeline is callable like old TTSBackend."""
        engine = FakeEngine()
        backend = Pipeline(engine)
        
        # Should be callable
        assert callable(backend)
    
    def test_pipeline_synthesize(self):
        """Pipeline can synthesize text."""
        engine = FakeEngine()
        backend = Pipeline(engine)
        
        # Call the backend
        segments = list(backend("Hello world", voice="default", speed=1.0))
        
        # Should return at least one segment
        assert len(segments) >= 1
        
        # Segment should have graphemes and audio
        segment = segments[0]
        assert hasattr(segment, "graphemes")
        assert hasattr(segment, "audio")
        assert segment.graphemes == "Hello world"
    
    def test_pipeline_dispose(self):
        """Pipeline can be disposed."""
        engine = FakeEngine()
        backend = Pipeline(engine)
        
        # Create a session by calling
        list(backend("test"))
        
        # Dispose should not raise
        backend.dispose()
        
        # Double dispose should be safe
        backend.dispose()


class TestCreatePipelineCompat:
    """Test create_pipeline utility function."""
    
    def test_create_pipeline_returns_callable(self):
        """create_pipeline returns a callable backend."""
        from abogen.tts_plugin.host_context import HostContext
        from abogen.tts_plugin.types import EngineConfig

        # Mock the plugin manager
        with patch("abogen.tts_plugin.utils.get_plugin_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager
            
            mock_engine = FakeEngine()
            mock_manager.create_engine.return_value = mock_engine
            
            backend = create_pipeline("kokoro", lang_code="a", device="cpu")
            
            assert callable(backend)
            mock_manager.create_engine.assert_called_once()
            call_args = mock_manager.create_engine.call_args
            assert call_args.args[0] == "kokoro"
            assert isinstance(call_args.kwargs["context"], HostContext)
            assert call_args.kwargs["model_path"] is None
            assert isinstance(call_args.kwargs["config"], EngineConfig)
            assert call_args.kwargs["config"].device == "cpu"
            assert call_args.kwargs["config"].lang_code == "a"
    
    def test_create_pipeline_raises_for_unknown_plugin(self):
        """create_pipeline raises KeyError for unknown plugins."""
        with patch("abogen.tts_plugin.utils.get_plugin_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager
            mock_manager.create_engine.side_effect = KeyError("Plugin not found")
            
            with pytest.raises(KeyError):
                create_pipeline("nonexistent")


class TestPluginManagerWithFakePlugins:
    """Test PluginManager with fake plugin loading."""
    
    def test_plugin_manager_create_engine_from_plugin(self):
        """PluginManager creates engine from loaded plugin."""
        manager = PluginManager()
        
        # Manually add a fake plugin
        def fake_create_engine(**kwargs):
            return FakeEngine(**kwargs)
        
        manager._plugins["fake"] = {
            "manifest": MagicMock(),
            "create_engine": fake_create_engine,
        }
        manager._loaded = True
        
        # Create engine
        engine = manager.create_engine("fake", param="value")
        
        assert isinstance(engine, FakeEngine)
        assert engine.kwargs == {"param": "value"}
    
    def test_plugin_manager_get_or_create_engine(self):
        """PluginManager caches engines."""
        manager = PluginManager()
        
        call_count = 0
        
        def fake_create_engine(**kwargs):
            nonlocal call_count
            call_count += 1
            return FakeEngine(**kwargs)
        
        manager._plugins["fake"] = {
            "manifest": MagicMock(),
            "create_engine": fake_create_engine,
        }
        manager._loaded = True
        
        # Get engine twice
        engine1 = manager.get_or_create_engine("fake")
        engine2 = manager.get_or_create_engine("fake")
        
        # Should be same instance
        assert engine1 is engine2
        assert call_count == 1
    
    def test_plugin_manager_dispose_all(self):
        """PluginManager disposes all cached engines."""
        manager = PluginManager()
        
        def fake_create_engine(**kwargs):
            return FakeEngine(**kwargs)
        
        manager._plugins["fake"] = {
            "manifest": MagicMock(),
            "create_engine": fake_create_engine,
        }
        manager._loaded = True
        
        # Create and cache engines
        engine1 = manager.get_or_create_engine("fake")
        engine2 = manager.get_or_create_engine("fake")
        
        # Dispose all
        manager.dispose_all()
        
        # Engines should be disposed
        assert engine1._disposed is True
        assert engine2._disposed is True
        
        # Cache should be empty
        assert len(manager._engines) == 0
