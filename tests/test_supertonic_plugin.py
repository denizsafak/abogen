"""Tests for the SuperTonic TTS Plugin.

These tests verify that the SuperTonic plugin:
- Loads correctly through the Plugin Loader
- Has a valid manifest
- Creates a valid Engine
- Satisfies the Engine/EngineSession contract
- Implements VoiceLister capability
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.loader import load_plugin_from_dir
from abogen.tts_plugin.manifest import PluginManifest
from abogen.tts_plugin.types import (
    AudioFormat,
    EngineConfig,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)


# ──────────────────────────────────────────────────────────────
# Path fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def supertonic_plugin_dir() -> Path:
    return Path(__file__).parent.parent / "plugins" / "supertonic"


def _supertonic_available() -> bool:
    """Check if SuperTonic is available."""
    try:
        from supertonic import TTS  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


@pytest.fixture
def host_context(tmp_path: Path) -> HostContext:
    class FakeHttpClient:
        def get(self, url: str, **kwargs: object) -> object:
            return None
        def post(self, url: str, **kwargs: object) -> object:
            return None

    return HostContext(
        config_dir=tmp_path,
        logger=logging.getLogger("test"),
        http_client=FakeHttpClient(),
    )


# ──────────────────────────────────────────────────────────────
# Plugin Loading Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicPluginLoading:
    """Test that SuperTonic plugin loads correctly through the Loader."""

    def test_plugin_loads_successfully(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        assert result.manifest is not None
        assert result.create_engine is not None

    def test_plugin_has_valid_manifest(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        manifest = result.manifest
        assert isinstance(manifest, PluginManifest)
        assert manifest.id == "supertonic"
        assert manifest.name == "SuperTonic"
        assert manifest.api_version == "1.0"

    def test_plugin_has_model_requirements(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        assert result.model_requirements is not None
        assert isinstance(result.model_requirements, tuple)

    def test_plugin_manifest_capabilities(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        manifest = result.manifest
        assert "voice_list" in manifest.capabilities

    def test_plugin_manifest_engine(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        engine_manifest = result.manifest.engine
        assert len(engine_manifest.voiceSources) > 0
        assert len(engine_manifest.audioFormats) > 0
        assert len(engine_manifest.parameters) > 0


# ──────────────────────────────────────────────────────────────
# Engine Creation Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicEngineCreation:
    """Test that SuperTonic Engine can be created."""

    @pytest.mark.skipif(
        not _supertonic_available(),
        reason="SuperTonic not installed"
    )
    def test_create_engine(self, supertonic_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True

        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    @pytest.mark.skipif(
        not _supertonic_available(),
        reason="SuperTonic not installed"
    )
    def test_engine_satisfies_protocol(self, supertonic_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True

        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# Engine Protocol Tests (using mock pipeline)
# ──────────────────────────────────────────────────────────────

class TestSuperTonicEngineProtocol:
    """Test SuperTonic Engine protocol compliance using mock pipeline."""

    def _create_engine_with_mock(self) -> Any:
        """Create engine with mock pipeline for testing."""
        from plugins.supertonic.engine import SuperTonicEngine

        class MockSegment:
            def __init__(self):
                import numpy as np
                self.audio = np.zeros(24000, dtype="float32")

        class MockPipeline:
            sample_rate = 24000

            def __call__(self, text, voice, speed, split_pattern=None, total_steps=None):
                return [MockSegment()]

        return SuperTonicEngine(MockPipeline())

    def test_create_session(self) -> None:
        engine = self._create_engine_with_mock()
        session = engine.createSession()
        assert isinstance(session, EngineSession)
        engine.dispose()

    def test_dispose_idempotent(self) -> None:
        engine = self._create_engine_with_mock()
        engine.dispose()
        engine.dispose()  # Should not raise

    def test_create_session_after_dispose_raises(self) -> None:
        from abogen.tts_plugin.errors import EngineError
        engine = self._create_engine_with_mock()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()

    def test_session_synthesize(self) -> None:
        engine = self._create_engine_with_mock()
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert result.data is not None
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    def test_session_dispose_idempotent(self) -> None:
        engine = self._create_engine_with_mock()
        session = engine.createSession()
        session.dispose()
        session.dispose()  # Should not raise
        engine.dispose()

    def test_session_synthesize_after_dispose_raises(self) -> None:
        from abogen.tts_plugin.errors import EngineError
        engine = self._create_engine_with_mock()
        session = engine.createSession()
        session.dispose()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        with pytest.raises(EngineError):
            session.synthesize(request)
        engine.dispose()

    def test_session_multiple_synthesize(self) -> None:
        engine = self._create_engine_with_mock()
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result1 = session.synthesize(request)
        result2 = session.synthesize(request)
        assert isinstance(result1.data, bytes)
        assert isinstance(result2.data, bytes)
        session.dispose()
        engine.dispose()

    def test_full_lifecycle(self) -> None:
        engine = self._create_engine_with_mock()

        # Create sessions
        session1 = engine.createSession()
        session2 = engine.createSession()

        # Use sessions
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        assert isinstance(session1.synthesize(request), SynthesizedAudio)
        assert isinstance(session2.synthesize(request), SynthesizedAudio)

        # Dispose sessions
        session1.dispose()
        session2.dispose()

        # Dispose engine
        engine.dispose()

    def test_engine_returns_new_session_instances(self) -> None:
        engine = self._create_engine_with_mock()
        session1 = engine.createSession()
        session2 = engine.createSession()
        assert session1 is not session2
        session1.dispose()
        session2.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# VoiceLister Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicVoiceLister:
    """Test SuperTonic VoiceLister capability."""

    def test_list_voices(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        assert len(voices) > 0
        assert all(hasattr(v, "id") for v in voices)
        assert all(hasattr(v, "name") for v in voices)
        engine.dispose()

    def test_voices_have_tags(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        for voice in voices:
            assert isinstance(voice.tags, tuple)
            assert len(voice.tags) > 0
        engine.dispose()

    def test_voices_are_correct_count(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        assert len(voices) == 10  # M1-M5, F1-F5
        engine.dispose()

    def test_voice_ids_match_expected(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        voice_ids = [v.id for v in voices]
        expected = ["M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"]
        assert voice_ids == expected
        engine.dispose()

    def test_male_voices_have_male_tag(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        male_voices = [v for v in voices if v.id.startswith("M")]
        for voice in male_voices:
            assert "male" in voice.tags
        engine.dispose()

    def test_female_voices_have_female_tag(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        voices = engine.listVoices("builtin")
        female_voices = [v for v in voices if v.id.startswith("F")]
        for voice in female_voices:
            assert "female" in voice.tags
        engine.dispose()

    def test_list_voices_after_dispose_raises(self) -> None:
        from abogen.tts_plugin.errors import EngineError
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        engine.dispose()
        with pytest.raises(EngineError):
            engine.listVoices("builtin")


# ──────────────────────────────────────────────────────────────
# Parameter Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicParameters:
    """Test SuperTonic parameter handling."""

    def test_speed_parameter(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={"speed": 1.5}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result.data, bytes)
        session.dispose()
        engine.dispose()

    def test_total_steps_parameter(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={"total_steps": 10}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result.data, bytes)
        session.dispose()
        engine.dispose()

    def test_default_parameters(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        session = engine.createSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result.data, bytes)
        session.dispose()
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# Error Handling Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicErrorHandling:
    """Test SuperTonic error handling."""

    def test_synthesize_empty_text(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        session = engine.createSession()
        request = SynthesisRequest(
            text="",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        # Empty text should return empty audio
        assert isinstance(result.data, bytes)
        session.dispose()
        engine.dispose()

    def test_synthesize_whitespace_text(self) -> None:
        engine = TestSuperTonicEngineProtocol._create_engine_with_mock(TestSuperTonicEngineProtocol)
        session = engine.createSession()
        request = SynthesisRequest(
            text="   ",
            voice=VoiceSelection(source="builtin", key="M1"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result.data, bytes)
        session.dispose()
        engine.dispose()
