"""Tests for the Kokoro TTS Plugin.

These tests verify that the Kokoro plugin:
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

def _kokoro_available() -> bool:
    try:
        from kokoro import KPipeline  # type: ignore[import-not-found]
        return True
    except ImportError:
        return False


def _make_mock_engine() -> Any:
    from plugins.kokoro.engine import KokoroEngine

    class MockPipeline:
        def __call__(self, text, voice, speed, split_pattern=None):
            class MockSegment:
                def __init__(self):
                    self.audio = MockAudio()
            class MockAudio:
                def numpy(self):
                    import numpy as np
                    return np.zeros(24000, dtype="float32")
            return [MockSegment()]

    engine = KokoroEngine(MockPipeline())

    # Override listVoices for testing (real engine reads from manifest)
    from abogen.tts_plugin.manifest import VoiceManifest
    engine.listVoices = lambda source_id: [
        VoiceManifest(id="test_voice_1", name="Test Voice 1", tags=("en",)),
        VoiceManifest(id="test_voice_2", name="Test Voice 2", tags=("es",)),
    ]
    return engine


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def kokoro_plugin_dir() -> Path:
    return Path(__file__).parent.parent / "plugins" / "kokoro"


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

class TestKokoroPluginLoading:

    def test_plugin_loads_successfully(self, kokoro_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        assert result.manifest is not None
        assert result.create_engine is not None

    def test_plugin_has_valid_manifest(self, kokoro_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        manifest = result.manifest
        assert isinstance(manifest, PluginManifest)
        assert manifest.id == "kokoro"
        assert manifest.name == "Kokoro"
        assert manifest.api_version == "1.0"

    def test_plugin_has_model_requirements(self, kokoro_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        assert result.model_requirements is not None
        assert isinstance(result.model_requirements, tuple)

    def test_plugin_manifest_capabilities(self, kokoro_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        assert "voice_list" in result.manifest.capabilities

    def test_plugin_manifest_engine(self, kokoro_plugin_dir: Path) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        engine_manifest = result.manifest.engine
        assert len(engine_manifest.voiceSources) > 0
        assert len(engine_manifest.audioFormats) > 0
        assert len(engine_manifest.parameters) > 0


# ──────────────────────────────────────────────────────────────
# Engine Creation (real backend, skipped if not installed)
# ──────────────────────────────────────────────────────────────

class TestKokoroEngineCreation:

    @pytest.mark.skipif(not _kokoro_available(), reason="Kokoro not installed")
    def test_create_engine(self, kokoro_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()

    @pytest.mark.skipif(not _kokoro_available(), reason="Kokoro not installed")
    def test_engine_satisfies_protocol(self, kokoro_plugin_dir: Path, host_context: HostContext) -> None:
        result = load_plugin_from_dir(kokoro_plugin_dir)
        assert result.success is True
        engine = result.create_engine(host_context, None, EngineConfig())
        assert isinstance(engine, Engine)
        engine.dispose()


# ──────────────────────────────────────────────────────────────
# Engine / Session Contract (inherited from base)
# ──────────────────────────────────────────────────────────────

class TestKokoroEngineContract(EngineContractMixin):
    """Every test from EngineContractMixin runs against KokoroEngine."""

    @pytest.fixture
    def default_voice(self) -> str:
        return "af_nova"


# ──────────────────────────────────────────────────────────────
# VoiceLister Tests
# ──────────────────────────────────────────────────────────────

class TestKokoroVoiceLister:

    def test_list_voices(self) -> None:
        engine = _make_mock_engine()
        voices = engine.listVoices("builtin")
        assert len(voices) > 0
        assert all(hasattr(v, "id") for v in voices)
        assert all(hasattr(v, "name") for v in voices)
        engine.dispose()

    def test_voices_have_tags(self) -> None:
        engine = _make_mock_engine()
        voices = engine.listVoices("builtin")
        for voice in voices:
            assert isinstance(voice.tags, tuple)
            assert len(voice.tags) > 0
        engine.dispose()
