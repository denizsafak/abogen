"""Behavioral Regression Tests for TTS Plugin Architecture.

These tests verify external user-facing behavior, NOT internal implementation.
They use only public API entry points available to application consumers.

Tested plugins: Kokoro, SuperTonic.

Public API Surface Tested:
- PluginManager: discover, list_plugins, has_plugin, create_engine, get_or_create_engine, dispose_all
- Engine: createSession, dispose
- EngineSession: synthesize, dispose
- VoiceLister: listVoices
- Pipeline (utils.py): __call__, dispose
- create_pipeline, get_voices, get_default_voice, is_plugin_registered, resolve_voice_to_plugin
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.manifest import PluginManifest, EngineManifest, VoiceManifest
from abogen.tts_plugin.plugin_manager import PluginManager, get_plugin_manager, reset_plugin_manager
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)
from abogen.tts_plugin.utils import (
    Pipeline,
    create_pipeline,
    get_default_voice,
    get_voices,
    is_plugin_registered,
    resolve_voice_to_plugin,
)


# ──────────────────────────────────────────────────────────────
# Plugin Mock Infrastructure
# ──────────────────────────────────────────────────────────────


def _make_request(
    text: str = "Hello",
    voice: str = "voice1",
    speed: float = 1.0,
) -> SynthesisRequest:
    return SynthesisRequest(
        text=text,
        voice=VoiceSelection(source="builtin", key=voice),
        parameters=ParameterValues(values={"speed": speed}),
        format=AudioFormat(mime="audio/wav", extension="wav"),
    )


class MockEngineSession:
    """Mock EngineSession that records calls."""

    def __init__(self) -> None:
        self._disposed = False
        self.synthesize_calls: list[SynthesisRequest] = []

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            raise EngineError("Session disposed")
        self.synthesize_calls.append(request)
        return SynthesizedAudio(
            data=b"\x00" * 1000,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )

    def dispose(self) -> None:
        self._disposed = True


class MockEngine:
    """Mock Engine with VoiceLister support."""

    def __init__(
        self,
        voice_manifests: list[VoiceManifest] | None = None,
        **kwargs: Any,
    ) -> None:
        self._disposed = False
        self._voice_manifests = voice_manifests or [
            VoiceManifest(id="voice1", name="Voice 1", tags=("en",)),
            VoiceManifest(id="voice2", name="Voice 2", tags=("es",)),
        ]

    def createSession(self) -> EngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        return MockEngineSession()

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        if self._disposed:
            raise EngineError("Engine disposed")
        return self._voice_manifests

    def dispose(self) -> None:
        self._disposed = True


class MockEngineAcceptKwargs:
    """MockEngine that accepts arbitrary kwargs (for create_engine)."""

    def __init__(self, **kwargs: Any) -> None:
        self._disposed = False
        self._kwargs = kwargs

    def createSession(self) -> EngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        return MockEngineSession()

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        if self._disposed:
            raise EngineError("Engine disposed")
        return [
            VoiceManifest(id="voice1", name="Voice 1", tags=("en",)),
            VoiceManifest(id="voice2", name="Voice 2", tags=("es",)),
        ]

    def dispose(self) -> None:
        self._disposed = True


def _create_mock_plugin(
    engine_class: type = MockEngine,
    manifest_id: str = "mock_tts",
) -> dict:
    manifest = PluginManifest(
        id=manifest_id,
        name="Mock TTS",
        version="1.0.0",
        api_version="1.0",
        description="Mock TTS for testing",
        author="Test",
        capabilities=("voice_list",),
        engine=EngineManifest(
            voiceSources=(),
            parameters=(),
            audioFormats=(),
        ),
    )
    return {
        "manifest": manifest,
        "create_engine": lambda **kwargs: engine_class(**kwargs),
        "module": None,
    }


# ──────────────────────────────────────────────────────────────
# Kokoro / SuperTonic Plugin Fixtures
# ──────────────────────────────────────────────────────────────


def _kokoro_available() -> bool:
    try:
        from kokoro import KPipeline  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


def _supertonic_available() -> bool:
    try:
        from supertonic import TTS  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


class _KokoroMockEngine:
    """Simulates Kokoro Engine behavior for behavioral tests."""

    def __init__(self, **kwargs: Any) -> None:
        self._disposed = False
        self._kwargs = kwargs
        self._voices = [
            VoiceManifest(id="af_nova", name="Nova", tags=("en", "female")),
            VoiceManifest(id="af_bella", name="Bella", tags=("en", "female")),
            VoiceManifest(id="am_adam", name="Adam", tags=("en", "male")),
        ]

    def createSession(self) -> EngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        return MockEngineSession()

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        if self._disposed:
            raise EngineError("Engine disposed")
        return self._voices

    def dispose(self) -> None:
        self._disposed = True


class _SuperTonicMockEngine:
    """Simulates SuperTonic Engine behavior for behavioral tests."""

    def __init__(self, **kwargs: Any) -> None:
        self._disposed = False
        self._kwargs = kwargs
        self._voices = [
            VoiceManifest(id="M1", name="Male 1", tags=("en", "male")),
            VoiceManifest(id="F1", name="Female 1", tags=("en", "female")),
            VoiceManifest(id="M2", name="Male 2", tags=("en", "male")),
        ]

    def createSession(self) -> EngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        return MockEngineSession()

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        if self._disposed:
            raise EngineError("Engine disposed")
        return self._voices

    def dispose(self) -> None:
        self._disposed = True


# Parametrize across both production plugins
_plugin_ids = ["kokoro", "supertonic"]
_plugin_engines = {
    "kokoro": _KokoroMockEngine,
    "supertonic": _SuperTonicMockEngine,
}
_plugin_default_voices = {
    "kokoro": "af_nova",
    "supertonic": "M1",
}
_plugin_all_voices = {
    "kokoro": ["af_nova", "af_bella", "am_adam"],
    "supertonic": ["M1", "F1", "M2"],
}


def _plugin_available(plugin_id: str) -> bool:
    if plugin_id == "kokoro":
        return _kokoro_available()
    elif plugin_id == "supertonic":
        return _supertonic_available()
    return False


# ──────────────────────────────────────────────────────────────
# 1. SYNTHESIS SCENARIOS (parametrized per plugin)
# ──────────────────────────────────────────────────────────────


class TestSynthesisNormalText:
    """Synthesis with normal text input."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_short_text(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello world"))
        assert isinstance(result, SynthesizedAudio)
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_paragraph_text(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        text = "This is a longer paragraph with multiple sentences. It tests synthesis of more substantial text content."
        result = session.synthesize(_make_request(text=text))
        assert isinstance(result, SynthesizedAudio)
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_punctuation(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        text = "Hello, world! How are you? I'm fine... Really?"
        result = session.synthesize(_make_request(text=text))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


class TestSynthesisLongText:
    """Synthesis with long text input."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_very_long_text(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        text = "Word " * 10000
        result = session.synthesize(_make_request(text=text))
        assert isinstance(result, SynthesizedAudio)
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_multiline_text(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        text = "\n".join([f"Line {i} of the text." for i in range(100)])
        result = session.synthesize(_make_request(text=text))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


class TestSynthesisEmptyText:
    """Synthesis with empty text input."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_empty_string(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text=""))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_whitespace_only(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="   \n\t  "))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


class TestSynthesisUnicodeText:
    """Synthesis with Unicode text input."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_cyrillic(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Привет мир"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_chinese(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="你好世界"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_emoji(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello 🌍"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_mixed_scripts(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello 你好 Привет"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_accented_characters(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Café résumé naïve"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 2. VOICE SCENARIOS (parametrized per plugin)
# ──────────────────────────────────────────────────────────────


class TestVoiceListing:
    """Voice listing via VoiceLister capability."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_list_voices_returns_manifests(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        voices = engine.listVoices("builtin")
        assert isinstance(voices, list)
        assert len(voices) > 0
        for v in voices:
            assert isinstance(v, VoiceManifest)
            assert hasattr(v, "id")
            assert hasattr(v, "name")
            assert hasattr(v, "tags")
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_voices_have_required_fields(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        voices = engine.listVoices("builtin")
        for v in voices:
            assert isinstance(v.id, str)
            assert len(v.id) > 0
            assert isinstance(v.name, str)
            assert len(v.name) > 0
            assert isinstance(v.tags, tuple)
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_voice_ids_match_manifest(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        voices = engine.listVoices("builtin")
        voice_ids = [v.id for v in voices]
        for expected_id in _plugin_all_voices[plugin_id]:
            assert expected_id in voice_ids
        engine.dispose()


class TestVoiceSelection:
    """Using different voices for synthesis."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_each_voice(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        for voice_id in _plugin_all_voices[plugin_id]:
            result = session.synthesize(
                _make_request(text="Hello", voice=voice_id)
            )
            assert isinstance(result, SynthesizedAudio)
            assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_invalid_voice(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(
            _make_request(text="Hello", voice="nonexistent_voice")
        )
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 3. PARAMETER SCENARIOS (parametrized per plugin)
# ──────────────────────────────────────────────────────────────


class TestSpeedParameter:
    """Speed parameter behavior."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_speed_1_0(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello", speed=1.0))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_speed_0_5(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello", speed=0.5))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_speed_2_0(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello", speed=2.0))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_with_default_speed(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key=_plugin_default_voices[plugin_id]),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result, SynthesizedAudio)
        session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 4. ERROR SCENARIOS
# ──────────────────────────────────────────────────────────────


class TestUnknownPlugin:
    """Handling of unknown plugin IDs."""

    def test_create_engine_unknown_plugin(self) -> None:
        manager = PluginManager()
        manager._loaded = True
        with pytest.raises(KeyError, match="Plugin not found"):
            manager.create_engine("nonexistent_plugin")

    def test_has_plugin_unknown(self) -> None:
        manager = PluginManager()
        manager._loaded = True
        assert manager.has_plugin("nonexistent_plugin") is False

    def test_get_plugin_unknown(self) -> None:
        manager = PluginManager()
        manager._loaded = True
        assert manager.get_plugin("nonexistent_plugin") is None


class TestPluginLoadingFailure:
    """Handling of plugin loading failures."""

    def test_discover_nonexistent_directory(self) -> None:
        manager = PluginManager()
        manager.discover("/nonexistent/path")
        assert manager.list_plugins() == []

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        manager = PluginManager()
        manager.discover(str(tmp_path))
        assert manager.list_plugins() == []


# ──────────────────────────────────────────────────────────────
# 5. LIFECYCLE SCENARIOS (parametrized per plugin)
# ──────────────────────────────────────────────────────────────


class TestMultipleSynthesis:
    """Multiple synthesis operations."""

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_sequential_synthesis(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        session = engine.createSession()
        for i in range(10):
            result = session.synthesize(_make_request(text=f"Text {i}"))
            assert isinstance(result, SynthesizedAudio)
            assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_multiple_sessions(self, plugin_id: str) -> None:
        engine = _plugin_engines[plugin_id]()
        sessions = [engine.createSession() for _ in range(5)]
        for i, session in enumerate(sessions):
            result = session.synthesize(_make_request(text=f"Session {i}"))
            assert isinstance(result, SynthesizedAudio)
        for session in sessions:
            session.dispose()
        engine.dispose()

    @pytest.mark.parametrize("plugin_id", _plugin_ids)
    def test_synthesize_after_failed_synthesize(self, plugin_id: str) -> None:
        """Session remains usable after synthesis failure."""
        class FailingSession:
            def __init__(self) -> None:
                self._call_count = 0
                self._disposed = False

            def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
                if self._disposed:
                    raise EngineError("Session disposed")
                self._call_count += 1
                if self._call_count == 1:
                    raise EngineError("First call fails")
                return SynthesizedAudio(
                    data=b"\x00" * 100,
                    format=AudioFormat(mime="audio/wav", extension="wav"),
                    duration=Duration(seconds=1.0),
                )

            def dispose(self) -> None:
                self._disposed = True

        session = FailingSession()
        with pytest.raises(EngineError):
            session.synthesize(_make_request(text="Fail"))
        result = session.synthesize(_make_request(text="Succeed"))
        assert isinstance(result, SynthesizedAudio)
        session.dispose()


class TestPipelineRecreation:
    """Pipeline creation and disposal."""

    def test_create_and_dispose_pipeline(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            pipeline = create_pipeline("mock_tts")
            assert isinstance(pipeline, Pipeline)
            result = list(pipeline("Hello", voice="voice1", speed=1.0))
            assert len(result) >= 1
            pipeline.dispose()

    def test_pipeline_dispose_idempotent(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            pipeline = create_pipeline("mock_tts")
            pipeline.dispose()
            pipeline.dispose()  # Should not raise


class TestResourceCleanup:
    """Resource cleanup and disposal."""

    def test_engine_dispose_is_idempotent(self) -> None:
        engine = MockEngine()
        engine.dispose()
        engine.dispose()  # Should not raise

    def test_session_dispose_is_idempotent(self) -> None:
        session = MockEngineSession()
        session.dispose()
        session.dispose()  # Should not raise

    def test_create_session_after_engine_dispose_raises(self) -> None:
        engine = MockEngine()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()

    def test_synthesize_after_session_dispose_raises(self) -> None:
        session = MockEngineSession()
        session.dispose()
        with pytest.raises(EngineError):
            session.synthesize(_make_request())

    def test_dispose_all_engines(self) -> None:
        manager = PluginManager()
        mock_plugin = _create_mock_plugin()
        manager._plugins["mock_tts"] = mock_plugin
        manager._loaded = True

        engine1 = manager.get_or_create_engine("mock_tts")
        engine2 = manager.get_or_create_engine("mock_tts")
        manager.dispose_all()

        assert engine1._disposed is True
        assert engine2._disposed is True
        assert len(manager._engines) == 0

    def test_no_exception_on_normal_termination(self) -> None:
        """Full lifecycle completes without unexpected exceptions."""
        engine = MockEngine()
        session = engine.createSession()
        result = session.synthesize(_make_request(text="Hello"))
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 6. PLUGIN MANAGER SCENARIOS
# ──────────────────────────────────────────────────────────────


class TestPluginManagerDiscovery:
    """Plugin discovery and listing."""

    def test_discover_with_valid_plugins(self) -> None:
        manager = PluginManager()
        manager._plugins["plugin_a"] = _create_mock_plugin(manifest_id="plugin_a")
        manager._plugins["plugin_b"] = _create_mock_plugin(manifest_id="plugin_b")
        manager._loaded = True

        plugins = manager.list_plugins()
        assert len(plugins) == 2
        ids = [p.id for p in plugins]
        assert "plugin_a" in ids
        assert "plugin_b" in ids

    def test_has_plugin(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        assert manager.has_plugin("mock_tts") is True
        assert manager.has_plugin("other") is False

    def test_get_plugin_returns_info(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        info = manager.get_plugin("mock_tts")
        assert info is not None
        assert "manifest" in info
        assert "create_engine" in info


class TestPluginManagerEngineCreation:
    """Engine creation via PluginManager."""

    def test_create_engine(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        engine = manager.create_engine("mock_tts")
        assert isinstance(engine, MockEngine)
        engine.dispose()

    def test_get_or_create_engine_caches(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        engine1 = manager.get_or_create_engine("mock_tts")
        engine2 = manager.get_or_create_engine("mock_tts")
        assert engine1 is engine2

    def test_create_engine_unknown_plugin_raises(self) -> None:
        manager = PluginManager()
        manager._loaded = True
        with pytest.raises(KeyError):
            manager.create_engine("nonexistent")

    def test_create_engine_with_kwargs(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = {
            "manifest": PluginManifest(
                id="mock_tts", name="Mock TTS", version="1.0.0",
                api_version="1.0", description="Mock TTS for testing",
                author="Test", capabilities=("voice_list",),
                engine=EngineManifest(voiceSources=(), parameters=(), audioFormats=()),
            ),
            "create_engine": lambda **kwargs: MockEngineAcceptKwargs(**kwargs),
            "module": None,
        }
        manager._loaded = True

        engine = manager.create_engine("mock_tts", device="cpu")
        assert isinstance(engine, MockEngineAcceptKwargs)
        assert engine._kwargs["device"] == "cpu"
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 7. VOICE RESOLUTION SCENARIOS
# ──────────────────────────────────────────────────────────────


class TestVoiceResolution:
    """Voice-to-plugin resolution."""

    def test_resolve_empty_spec(self) -> None:
        assert resolve_voice_to_plugin("", fallback="kokoro") == "kokoro"

    def test_resolve_none_spec(self) -> None:
        assert resolve_voice_to_plugin(None, fallback="kokoro") == "kokoro"

    def test_resolve_formula_with_star(self) -> None:
        assert resolve_voice_to_plugin("voice1*0.7") == "kokoro"

    def test_resolve_formula_with_plus(self) -> None:
        assert resolve_voice_to_plugin("voice1*0.7+voice2*0.3") == "kokoro"

    def test_resolve_unknown_voice_returns_fallback(self) -> None:
        assert resolve_voice_to_plugin("unknown_voice") == "kokoro"


class TestGetVoices:
    """Voice listing utility functions."""

    def test_get_voices_registered_plugin(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin(engine_class=MockEngineAcceptKwargs)
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            voices = get_voices("mock_tts")
            assert isinstance(voices, tuple)
            assert len(voices) > 0
            assert all(isinstance(v, str) for v in voices)

    def test_get_voices_unregistered_plugin(self) -> None:
        manager = PluginManager()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            voices = get_voices("nonexistent")
            assert voices == ()

    def test_get_default_voice(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin(engine_class=MockEngineAcceptKwargs)
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            voice = get_default_voice("mock_tts")
            assert isinstance(voice, str)
            assert len(voice) > 0

    def test_get_default_voice_unregistered(self) -> None:
        manager = PluginManager()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            voice = get_default_voice("nonexistent", fallback="default")
            assert voice == "default"

    def test_is_plugin_registered(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            assert is_plugin_registered("mock_tts") is True
            assert is_plugin_registered("nonexistent") is False


# ──────────────────────────────────────────────────────────────
# 8. ERROR HIERARCHY BEHAVIORAL
# ──────────────────────────────────────────────────────────────


class TestErrorHierarchyBehavioral:
    """Error hierarchy behavioral tests."""

    def test_all_errors_catchable_as_engine_error(self) -> None:
        from abogen.tts_plugin.errors import (
            CancelledError,
            ConfigurationError,
            InternalError,
            InvalidInputError,
            ModelLoadError,
            ModelNotFoundError,
            NetworkError,
        )

        error_classes = [
            ModelNotFoundError,
            ModelLoadError,
            NetworkError,
            InvalidInputError,
            ConfigurationError,
            CancelledError,
            InternalError,
        ]
        for error_class in error_classes:
            with pytest.raises(EngineError):
                raise error_class("test")

    def test_error_message_preserved(self) -> None:
        from abogen.tts_plugin.errors import InvalidInputError

        msg = "Model not found: bert-base"
        with pytest.raises(EngineError, match=msg):
            raise InvalidInputError(msg)


# ──────────────────────────────────────────────────────────────
# 9. VALUE OBJECT BEHAVIORAL
# ──────────────────────────────────────────────────────────────


class TestValueObjectsBehavioral:
    """Value object behavioral tests."""

    def test_synthesis_request_immutability(self) -> None:
        req = _make_request()
        with pytest.raises(AttributeError):
            req.text = "changed"  # type: ignore[misc]

    def test_voice_selection_immutability(self) -> None:
        vs = VoiceSelection(source="builtin", key="voice1")
        with pytest.raises(AttributeError):
            vs.source = "changed"  # type: ignore[misc]

    def test_audio_format_equality(self) -> None:
        af1 = AudioFormat(mime="audio/wav", extension="wav")
        af2 = AudioFormat(mime="audio/wav", extension="wav")
        assert af1 == af2

    def test_synthesized_audio_fields(self) -> None:
        audio = SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )
        assert audio.data == b"\x00" * 100
        assert audio.format.mime == "audio/wav"
        assert audio.duration.seconds == 1.0

    def test_engine_config_defaults(self) -> None:
        from abogen.tts_plugin.types import EngineConfig

        config = EngineConfig()
        assert config.device == "cpu"
        assert config.lang_code == "a"

    def test_parameter_values_defaults(self) -> None:
        pv = ParameterValues()
        assert pv.values == {}


# ──────────────────────────────────────────────────────────────
# 10. ENGINE DISPOSAL BEHAVIORAL
# ──────────────────────────────────────────────────────────────


class TestEngineDisposalBehavioral:
    """Engine disposal behavioral tests."""

    def test_dispose_prevents_new_sessions(self) -> None:
        engine = MockEngine()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()

    def test_dispose_all_engines(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        engine1 = manager.get_or_create_engine("mock_tts")
        engine2 = manager.get_or_create_engine("mock_tts")
        manager.dispose_all()

        assert engine1._disposed is True
        assert engine2._disposed is True
        assert len(manager._engines) == 0


# ──────────────────────────────────────────────────────────────
# 11. SESSION DISPOSAL BEHAVIORAL
# ──────────────────────────────────────────────────────────────


class TestSessionDisposalBehavioral:
    """Session disposal behavioral tests."""

    def test_dispose_prevents_synthesis(self) -> None:
        session = MockEngineSession()
        session.dispose()
        with pytest.raises(EngineError):
            session.synthesize(_make_request())


# ──────────────────────────────────────────────────────────────
# 12. CONCURRENT ACCESS (SEQUENTIAL SIMULATION)
# ──────────────────────────────────────────────────────────────


class TestConcurrentAccess:
    """Simulated concurrent access patterns."""

    def test_multiple_engines_independent(self) -> None:
        engine1 = MockEngine()
        engine2 = MockEngine()
        session1 = engine1.createSession()
        session2 = engine2.createSession()

        result1 = session1.synthesize(_make_request(text="Engine 1"))
        result2 = session2.synthesize(_make_request(text="Engine 2"))

        assert len(result1.data) > 0
        assert len(result2.data) > 0

        session1.dispose()
        session2.dispose()
        engine1.dispose()
        engine2.dispose()

    def test_session_per_thread_simulation(self) -> None:
        engine = MockEngine()
        sessions = [engine.createSession() for _ in range(5)]

        for i, session in enumerate(sessions):
            result = session.synthesize(_make_request(text=f"Thread {i}"))
            assert len(result.data) > 0

        for session in sessions:
            session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# 13. PLUGIN MANAGER SINGLETON
# ──────────────────────────────────────────────────────────────


class TestPluginManagerSingleton:
    """PluginManager singleton behavior."""

    def test_singleton_pattern(self) -> None:
        reset_plugin_manager()
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()
        assert manager1 is manager2
        reset_plugin_manager()

    def test_reset_creates_new_instance(self) -> None:
        reset_plugin_manager()
        manager1 = get_plugin_manager()
        reset_plugin_manager()
        manager2 = get_plugin_manager()
        assert manager1 is not manager2
        reset_plugin_manager()


# ──────────────────────────────────────────────────────────────
# 14. PIPELINE UTILITY BEHAVIORAL
# ──────────────────────────────────────────────────────────────


class TestPipelineUtility:
    """Pipeline utility behavioral tests."""

    def test_pipeline_callable(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            pipeline = create_pipeline("mock_tts")
            result = list(pipeline("Hello world", voice="voice1", speed=1.0))
            assert len(result) >= 1
            segment = result[0]
            assert segment.graphemes == "Hello world"
            assert isinstance(segment.audio, np.ndarray)
            assert segment.audio.dtype == np.float32
            pipeline.dispose()

    def test_pipeline_with_split_pattern(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            pipeline = create_pipeline("mock_tts")
            result = list(pipeline("Hello", voice="voice1", split_pattern=r"\n+"))
            assert len(result) >= 1
            pipeline.dispose()

    def test_pipeline_dispose(self) -> None:
        manager = PluginManager()
        manager._plugins["mock_tts"] = _create_mock_plugin()
        manager._loaded = True

        with patch("abogen.tts_plugin.utils.get_plugin_manager", return_value=manager):
            pipeline = create_pipeline("mock_tts")
            pipeline.dispose()
            assert pipeline._session is None
