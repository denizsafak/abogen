"""SuperTonic Engine adapter for the TTS Plugin Architecture.

This module adapts the existing SuperTonic backend to the new Engine/EngineSession
protocol. It wraps the SupertonicPipeline without modifying it.
"""

from __future__ import annotations

import io
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

# Sample rate for SuperTonic audio
_SUPERTONIC_SAMPLE_RATE = 24000


class SuperTonicSession:
    """EngineSession implementation for SuperTonic.

    Owns mutable execution state for synthesis.
    NOT thread-safe.
    """

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline
        self._disposed = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        """Synthesize audio from text using SuperTonic."""
        if self._disposed:
            raise EngineError("Session disposed")

        try:
            import soundfile as sf

            voice = request.voice.key
            speed = float(request.parameters.values.get("speed", 1.0))
            total_steps = request.parameters.values.get("total_steps", None)
            split_pattern = request.parameters.values.get("split_pattern", None)

            if total_steps is not None:
                total_steps = int(total_steps)

            audio_parts: list[np.ndarray] = []
            for segment in self._pipeline(
                request.text,
                voice=voice,
                speed=speed,
                split_pattern=split_pattern,
                total_steps=total_steps,
            ):
                audio_parts.append(segment.audio)

            if not audio_parts:
                return SynthesizedAudio(
                    data=b"",
                    format=AudioFormat(mime="audio/wav", extension="wav"),
                    duration=Duration(seconds=0.0),
                )

            combined = np.concatenate(audio_parts).astype("float32", copy=False)
            buf = io.BytesIO()
            sf.write(buf, combined, self._pipeline.sample_rate, format="WAV")
            audio_bytes = buf.getvalue()
            duration_seconds = len(combined) / self._pipeline.sample_rate

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


class SuperTonicEngine:
    """Engine implementation for SuperTonic.

    Factory for SuperTonicSession instances. Stateless and thread-safe.
    """

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline
        self._disposed = False

    def createSession(self) -> SuperTonicSession:
        """Create a new SuperTonicSession."""
        if self._disposed:
            raise EngineError("Engine disposed")
        return SuperTonicSession(self._pipeline)

    def dispose(self) -> None:
        """Release engine resources. Idempotent."""
        self._disposed = True

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        """List available SuperTonic voices. Implements VoiceLister capability.
        
        Note: Static voice catalog is declared in plugin manifest.
        This method is retained for VoiceLister interface compliance.
        """
        if self._disposed:
            raise EngineError("Engine disposed")
        return []
