"""Kokoro Engine adapter for the TTS Plugin Architecture.

This module adapts the existing Kokoro backend to the new Engine/EngineSession
protocol. It wraps the KokoroBackend without modifying it.

Language mapping: this is the engine's responsibility. The engine knows
which languages it supports and converts Language enum → internal format.
Callers outside this module never see engine-specific codes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from abogen.domain.enums import Language
from abogen.tts_plugin.capabilities import VoiceLister
from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.manifest import VoiceManifest
from abogen.tts_plugin.types import (
    AudioFormat,
    AudioSegment,
    Duration,
    SynthesisRequest,
    SynthesizedAudio,
    TokenTiming,
)

logger = logging.getLogger(__name__)

# Sample rate for Kokoro audio
_KOKORO_SAMPLE_RATE = 24000

# Engine-internal language mapping: Language enum → kokoro code.
# ONLY visible inside this module — callers never see kokoro codes.
_KOKORO_LANG_MAP: dict[Language, str] = {
    Language.EN_US: "a",
    Language.EN_GB: "b",
    Language.ES: "e",
    Language.FR: "f",
    Language.HI: "h",
    Language.IT: "i",
    Language.JA: "j",
    Language.PT_BR: "p",
    Language.ZH: "z",
}

# Reverse mapping: engine-internal code → Language enum.
# Used by voice catalog and other places that need to convert
# engine codes back to Language enum (e.g. voice ID prefix extraction).
_CODE_TO_LANGUAGE: dict[str, Language] = {v: k for k, v in _KOKORO_LANG_MAP.items()}


def supported_languages() -> list[Language]:
    """Return the list of Language enum values this engine supports.

    This is the engine's responsibility — the engine knows which
    languages it supports and exposes them as Language enum values.
    UI layers query this to populate language selectors.
    """
    return list(_KOKORO_LANG_MAP.keys())


def engine_language(lang: Language) -> str:
    """Map a Language enum to the engine's internal code.

    This is the engine's responsibility — the engine owns the mapping
    between Language enum and its internal format. Callers pass Language
    enum; the engine converts internally. The returned string is ONLY
    used inside the engine implementation.
    """
    return _KOKORO_LANG_MAP.get(lang, "a")


def language_for_code(code: str | None) -> Language:
    """Map a kokoro engine language code (single letter) to a Language enum.

    Used to resolve legacy data such as old profile files that stored
    kokoro letter codes. This is kokoro-specific knowledge that stays
    inside the engine. Unparseable values fall back to EN_US.
    """
    letter = str(code or "").strip()[:1].lower()
    if letter in _CODE_TO_LANGUAGE:
        return _CODE_TO_LANGUAGE[letter]
    return Language.EN_US


def language_for_voice_id(voice_id: str | None) -> Language:
    """Determine which Language a voice belongs to from its voice ID.

    Kokoro voice IDs encode language as a prefix (e.g. "af_heart" → "a" → EN_US).
    This is kokoro-specific knowledge that stays inside the engine.
    Callers pass a voice ID string; the engine returns a Language enum.
    """
    return language_for_code(voice_id)


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

            sample_rate = _KOKORO_SAMPLE_RATE
            audio_parts: list[np.ndarray] = []
            segments: list[AudioSegment] = []
            for segment in self._pipeline(
                request.text,
                voice=voice,
                speed=speed,
                split_pattern=split_pattern,
            ):
                audio = segment.audio
                if hasattr(audio, "numpy"):
                    audio = audio.numpy()
                audio = np.asarray(audio, dtype="float32")
                if audio.size == 0:
                    continue
                audio_parts.append(audio)

                tokens = tuple(
                    TokenTiming(
                        text=str(tok.text),
                        whitespace=str(tok.whitespace or ""),
                        start=float(tok.start_ts or 0.0),
                        end=float(tok.end_ts or 0.0),
                    )
                    for tok in (getattr(segment, "tokens", None) or [])
                )
                segments.append(
                    AudioSegment(
                        graphemes=str(getattr(segment, "graphemes", "") or ""),
                        audio=audio.tobytes(),
                        sample_rate=sample_rate,
                        tokens=tokens,
                    )
                )

            if not audio_parts:
                return SynthesizedAudio(
                    data=b"",
                    format=AudioFormat(mime="audio/wav", extension="wav"),
                    duration=Duration(seconds=0.0),
                )

            combined = np.concatenate(audio_parts).astype("float32", copy=False)
            audio_bytes = combined.tobytes()
            duration_seconds = len(combined) / sample_rate

            return SynthesizedAudio(
                data=audio_bytes,
                format=AudioFormat(mime="audio/wav", extension="wav"),
                duration=Duration(seconds=duration_seconds),
                segments=tuple(segments),
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
