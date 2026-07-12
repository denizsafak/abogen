"""Kokoro Engine adapter for the TTS Plugin Architecture.

This module adapts the existing Kokoro backend to the new Engine/EngineSession
protocol. It wraps the KokoroBackend without modifying it.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from abogen.tts_plugin.capabilities import VoiceLister
from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.manifest import VoiceManifest
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    SynthesisRequest,
    SynthesizedAudio,
)

logger = logging.getLogger(__name__)

# Sample rate for Kokoro audio
_KOKORO_SAMPLE_RATE = 24000


class KokoroSession:
    """EngineSession implementation for Kokoro.

    Owns mutable execution state for synthesis.
    NOT thread-safe.
    """

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline
        self._disposed = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        """Synthesize audio from text using Kokoro."""
        if self._disposed:
            raise EngineError("Session disposed")

        try:
            voice = request.voice.key
            speed = request.parameters.values.get("speed", 1.0)
            split_pattern = request.parameters.values.get("split_pattern", None)

            audio_parts: list[np.ndarray] = []
            for segment in self._pipeline(
                request.text,
                voice=voice,
                speed=speed,
                split_pattern=split_pattern,
            ):
                audio = segment.audio
                if hasattr(audio, "numpy"):
                    audio = audio.numpy()
                audio_parts.append(np.asarray(audio, dtype="float32"))

            if not audio_parts:
                return SynthesizedAudio(
                    data=b"",
                    format=AudioFormat(mime="audio/wav", extension="wav"),
                    duration=Duration(seconds=0.0),
                )

            combined = np.concatenate(audio_parts).astype("float32", copy=False)
            audio_bytes = combined.tobytes()
            duration_seconds = len(combined) / _KOKORO_SAMPLE_RATE

            return SynthesizedAudio(
                data=audio_bytes,
                format=AudioFormat(mime="audio/wav", extension="wav"),
                duration=Duration(seconds=duration_seconds),
            )
        except EngineError:
            raise
        except Exception as e:
            raise EngineError(f"Synthesis failed: {e}") from e

    def dispose(self) -> None:
        """Release session resources. Idempotent."""
        self._disposed = True


class KokoroEngine:
    """Engine implementation for Kokoro.

    Factory for KokoroSession instances. Stateless and thread-safe.
    """

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline
        self._disposed = False

    def createSession(self) -> KokoroSession:
        """Create a new KokoroSession."""
        if self._disposed:
            raise EngineError("Engine disposed")
        return KokoroSession(self._pipeline)

    def dispose(self) -> None:
        """Release engine resources. Idempotent."""
        self._disposed = True

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        """List available Kokoro voices. Implements VoiceLister capability.

        Note: Static voices are declared in the plugin manifest.
        This method is a fallback for dynamic plugins.
        """
        if self._disposed:
            raise EngineError("Engine disposed")
        return []
