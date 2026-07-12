"""Fake plugin for testing the plugin loader.

This is a minimal valid plugin that satisfies the Plugin API contract.
It does NOT perform any real TTS synthesis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.manifest import (
    AudioFormatManifest,
    EngineManifest,
    PluginManifest,
    VoiceSourceManifest,
)
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    EngineConfig,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
)


class FakeSession:
    """Minimal EngineSession implementation for testing."""

    def __init__(self) -> None:
        self._disposed = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            raise EngineError("Session disposed")
        return SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )

    def dispose(self) -> None:
        self._disposed = True


class FakeEngine:
    """Minimal Engine implementation for testing."""

    def __init__(self) -> None:
        self._disposed = False

    def createSession(self) -> EngineSession:
        if self._disposed:
            raise EngineError("Engine disposed")
        return FakeSession()

    def dispose(self) -> None:
        self._disposed = True


PLUGIN_MANIFEST = PluginManifest(
    id="fake_plugin",
    name="Fake Plugin",
    version="1.0.0",
    api_version="1.0",
    description="A fake plugin for testing",
    author="Test Author",
    capabilities=(),
    engine=EngineManifest(
        voiceSources=(
            VoiceSourceManifest(id="builtin", name="Builtin", type="list"),
        ),
        audioFormats=(
            AudioFormatManifest(mime="audio/wav", extension="wav"),
        ),
    ),
)

MODEL_REQUIREMENTS: list[Any] = []


def create_engine(
    context: HostContext,
    model_path: Path | None,
    config: EngineConfig,
) -> Engine:
    """Create a fake engine instance."""
    return FakeEngine()
