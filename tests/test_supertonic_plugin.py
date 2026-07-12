"""Tests for the SuperTonic TTS Plugin.

These tests verify that the SuperTonic plugin:
- Loads correctly through the Plugin Loader
- Has a valid manifest
- Creates a valid Engine
- Satisfies the Engine/EngineSession contract (via EngineContractMixin)
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
    VoiceSelection,
)

from tests.contracts.engine_contract import EngineContractMixin


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _supertonic_available() -> bool:
    try:
        from supertonic import TTS  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


def _make_mock_engine() -> Any:
    from plugins.supertonic.engine import SuperTonicEngine

    class MockSegment:
        def __init__(self):
            import numpy as np
            self.audio = np.zeros(24000, dtype="float32")

    class MockPipeline:
        sample_rate = 24000

        def __call__(self, text, voice, speed, split_pattern=None, total_steps=None):
            return [MockSegment()]

    engine = SuperTonicEngine(MockPipeline())

    # Override listVoices for testing (real engine reads from manifest)
    from abogen.tts_plugin.manifest import VoiceManifest
    original_list_voices = engine.listVoices
    
    def mock_list_voices(source_id):
        if engine._disposed:
            from abogen.tts_plugin.errors import EngineError
            raise EngineError("Engine disposed")
        return [
            VoiceManifest(id="M1", name="Male 1", tags=("male",)),
            VoiceManifest(id="M2", name="Male 2", tags=("male",)),
            VoiceManifest(id="M3", name="Male 3", tags=("male",)),
            VoiceManifest(id="M4", name="Male 4", tags=("male",)),
            VoiceManifest(id="M5", name="Male 5", tags=("male",)),
            VoiceManifest(id="F1", name="Female 1", tags=("female",)),
            VoiceManifest(id="F2", name="Female 2", tags=("female",)),
            VoiceManifest(id="F3", name="Female 3", tags=("female",)),
            VoiceManifest(id="F4", name="Female 4", tags=("female",)),
            VoiceManifest(id="F5", name="Female 5", tags=("female",)),
        ]
    
    engine.listVoices = mock_list_voices
    return engine


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def supertonic_plugin_dir() -> Path:
    return Path(__file__).parent.parent / "plugins" / "supertonic"


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


@pytest.fixture
def engine() -> Engine:
    return _make_mock_engine()


# ──────────────────────────────────────────────────────────────
# Plugin Loading Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicPluginLoading:

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
        assert "voice_list" in result.manifest.capabilities

    def test_plugin_manifest_engine(self, supertonic_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        engine_manifest = result.manifest.engine
        assert len(engine_manifest.voiceSources) > 0
        assert len(engine_manifest.audioFormats) > 0
        assert len(engine_manifest.parameters) > 0


# ──────────────────────────────────────────────────────────────
# Engine Creation (real backend, skipped if not installed)
# ──────────────────────────────────────────────────────────────

class TestSuperTonicEngineCreation:

    @pytest.mark.skipif(not _supertonic_available(), reason="SuperTonic not installed")
    def test_create_engine(self, supertonic_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    @pytest.mark.skipif(not _supertonic_available(), reason="SuperTonic not installed")
    def test_engine_satisfies_protocol(self, supertonic_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(supertonic_plugin_dir)
        assert result.success is True
        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# Engine / Session Contract (inherited from base)
# ──────────────────────────────────────────────────────────────

class TestSuperTonicEngineContract(EngineContractMixin):
    """Every test from EngineContractMixin runs against SuperTonicEngine."""

    @pytest.fixture
    def default_voice(self) -> str:
        return "M1"


# ──────────────────────────────────────────────────────────────
# VoiceLister Tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicVoiceLister:

    def test_list_voices(self) -> None:
        engine = _make_mock_engine()
        voices = engine.listVoices("builtin")
        assert len(voices) == 10
        assert all(hasattr(v, "id") for v in voices)
        assert all(hasattr(v, "name") for v in voices)
        engine.dispose()

    def test_voices_have_tags(self) -> None:
        engine = _make_mock_engine()
        for voice in engine.listVoices("builtin"):
            assert isinstance(voice.tags, tuple)
            assert len(voice.tags) > 0
        engine.dispose()

    def test_male_voices_have_male_tag(self) -> None:
        engine = _make_mock_engine()
        for v in engine.listVoices("builtin"):
            if v.id.startswith("M"):
                assert "male" in v.tags
        engine.dispose()

    def test_female_voices_have_female_tag(self) -> None:
        engine = _make_mock_engine()
        for v in engine.listVoices("builtin"):
            if v.id.startswith("F"):
                assert "female" in v.tags
        engine.dispose()

    def test_list_voices_after_dispose_raises(self) -> None:
        from abogen.tts_plugin.errors import EngineError
        engine = _make_mock_engine()
        engine.dispose()
        with pytest.raises(EngineError):
            engine.listVoices("builtin")


# ──────────────────────────────────────────────────────────────
# SuperTonic-specific parameter tests
# ──────────────────────────────────────────────────────────────

class TestSuperTonicParameters:

    def test_speed_parameter(self) -> None:
        engine = _make_mock_engine()
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
        engine = _make_mock_engine()
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
        engine = _make_mock_engine()
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
