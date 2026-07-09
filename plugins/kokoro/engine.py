"""Kokoro Engine adapter for the TTS Plugin Architecture.

This module adapts the existing Kokoro backend to the new Engine/EngineSession
protocol. It wraps the KokoroBackend without modifying it.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import numpy as np

from abogen.tts_plugin.capabilities import VoiceLister
from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError, InvalidInputError
from abogen.tts_plugin.manifest import VoiceManifest
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)

logger = logging.getLogger(__name__)

# Kokoro voice list - source of truth
_KOKORO_VOICES = (
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah",
    "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
    "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "ef_dora", "em_alex", "em_santa",
    "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
)

# Voice display names mapping
_VOICE_DISPLAY_NAMES: dict[str, str] = {
    "af_alloy": "Alloy", "af_aoede": "Aoede", "af_bella": "Bella",
    "af_heart": "Heart", "af_jessica": "Jessica", "af_kore": "Kore",
    "af_nicole": "Nicole", "af_nova": "Nova", "af_river": "River",
    "af_sarah": "Sarah", "af_sky": "Sky", "am_adam": "Adam",
    "am_echo": "Echo", "am_eric": "Eric", "am_fenrir": "Fenrir",
    "am_liam": "Liam", "am_michael": "Michael", "am_onyx": "Onyx",
    "am_puck": "Puck", "am_santa": "Santa", "bf_alice": "Alice",
    "bf_emma": "Emma", "bf_isabella": "Isabella", "bf_lily": "Lily",
    "bm_daniel": "Daniel", "bm_fable": "Fable", "bm_george": "George",
    "bm_lewis": "Lewis", "ef_dora": "Dora", "em_alex": "Alex",
    "em_santa": "Santa", "ff_siwis": "Siwis", "hf_alpha": "Alpha",
    "hf_beta": "Beta", "hm_omega": "Omega", "hm_psi": "Psi",
    "if_sara": "Sara", "im_nicola": "Nicola",
    "jf_alpha": "Alpha", "jf_gongitsune": "Gongitsune",
    "jf_nezumi": "Nezumi", "jf_tebukuro": "Tebukuro", "jm_kumo": "Kumo",
    "pf_dora": "Dora", "pm_alex": "Alex", "pm_santa": "Santa",
    "zf_xiaobei": "Xiaobei", "zf_xiaoni": "Xiaoni",
    "zf_xiaoxiao": "Xiaoxiao", "zf_xiaoyi": "Xiaoyi",
    "zm_yunjian": "Yunjian", "zm_yunxi": "Yunxi",
    "zm_yunxia": "Yunxia", "zm_yunyang": "Yunyang",
}

# Sample rate for Kokoro audio
_KOKORO_SAMPLE_RATE = 24000


class KokoroSession:
    """EngineSession implementation for Kokoro.

    Owns mutable execution state for synthesis.
    NOT thread-safe.
    """

    def __init__(self, pipeline: Any, lang_code: str) -> None:
        self._pipeline = pipeline
        self._lang_code = lang_code
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

    def __init__(self, pipeline: Any, lang_code: str) -> None:
        self._pipeline = pipeline
        self._lang_code = lang_code
        self._disposed = False

    def createSession(self) -> KokoroSession:
        """Create a new KokoroSession."""
        if self._disposed:
            raise EngineError("Engine disposed")
        return KokoroSession(self._pipeline, self._lang_code)

    def dispose(self) -> None:
        """Release engine resources. Idempotent."""
        self._disposed = True

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        """List available Kokoro voices. Implements VoiceLister capability."""
        if self._disposed:
            raise EngineError("Engine disposed")
        return [
            VoiceManifest(
                id=voice_id,
                name=_VOICE_DISPLAY_NAMES.get(voice_id, voice_id),
                tags=(_get_language_tag(voice_id), _get_gender_tag(voice_id)),
            )
            for voice_id in _KOKORO_VOICES
        ]


def _get_language_tag(voice_id: str) -> str:
    """Extract language tag from voice ID."""
    prefix = voice_id.split("_")[0]
    lang_map = {
        "af": "en-us", "am": "en-us", "bf": "en-gb", "bm": "en-gb",
        "ef": "es", "em": "es", "ff": "fr", "hf": "hi", "hm": "hi",
        "if": "it", "im": "it", "jf": "ja", "jm": "ja",
        "pf": "pt", "pm": "pt", "zf": "zh", "zm": "zh",
    }
    return lang_map.get(prefix, "unknown")


def _get_gender_tag(voice_id: str) -> str:
    """Extract gender tag from voice ID."""
    prefix = voice_id.split("_")[0]
    if prefix.startswith("a") or prefix.startswith("b") or prefix.startswith("e"):
        return "female" if prefix[1] == "f" else "male"
    return "unknown"
