"""
Kokoro TTS Backend

Encapsulates the Kokoro KPipeline as a TTSBackend implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import numpy as np

from abogen.tts_backend import TTSBackendMetadata

# Internal voice list — source of truth for Kokoro voices.
# The rest of the project accesses voices via get_metadata("kokoro").voices.
_VOICES_INTERNAL = [
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "pf_dora",
    "pm_alex",
    "pm_santa",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
]

_KOKORO_METADATA = TTSBackendMetadata(
    id="kokoro",
    name="Kokoro",
    description="Kokoro TTS engine",
    voices=tuple(_VOICES_INTERNAL),
)


def _load_kpipeline():
    """Lazy-load Kokoro dependencies."""
    from kokoro import KPipeline  # type: ignore[import-not-found]

    return KPipeline


class KokoroBackend:
    """TTSBackend implementation wrapping the Kokoro KPipeline.

    All interaction with KPipeline is encapsulated here.
    The rest of the project depends only on this class.
    """

    def __init__(self, **kwargs: Any) -> None:
        lang_code = kwargs["lang_code"]
        repo_id = kwargs.get("repo_id", "hexgrad/Kokoro-82M")
        device = kwargs.get("device", "cpu")

        KPipeline = _load_kpipeline()
        self._pipeline = KPipeline(
            lang_code=lang_code,
            repo_id=repo_id,
            device=device,
        )
        self._lang_code = lang_code

    @property
    def metadata(self) -> TTSBackendMetadata:
        return _KOKORO_METADATA

    def __call__(
        self,
        text: str,
        *,
        voice: Any,
        speed: float = 1.0,
        split_pattern: Optional[str] = None,
    ) -> Iterator[Any]:
        """Delegate to KPipeline's __call__."""
        return self._pipeline(
            text,
            voice=voice,
            speed=speed,
            split_pattern=split_pattern,
        )

    def load_single_voice(self, voice_name: str) -> Any:
        """Load a single voice tensor. Used by voice formula system."""
        return self._pipeline.load_single_voice(voice_name)

    def synthesize(self, text: str, **kwargs: Any) -> bytes:
        """Synthesize speech from text. Returns raw audio bytes."""
        voice = kwargs.get("voice", "")
        speed = kwargs.get("speed", 1.0)
        split_pattern = kwargs.get("split_pattern", None)

        audio_parts: list[np.ndarray] = []
        for segment in self(text, voice=voice, speed=speed, split_pattern=split_pattern):
            audio = segment.audio
            if hasattr(audio, "numpy"):
                audio = audio.numpy()
            audio_parts.append(np.asarray(audio, dtype="float32"))

        if not audio_parts:
            return b""

        combined = np.concatenate(audio_parts).astype("float32", copy=False)
        return combined.tobytes()

    def get_available_voices(self) -> List[str]:
        """Return known Kokoro voice identifiers."""
        return list(self.metadata.voices)

    def get_supported_formats(self) -> List[str]:
        """Kokoro outputs raw PCM float32 audio."""
        return ["pcm_float32"]

    def get_info(self) -> Dict[str, Any]:
        return {
            "id": "kokoro",
            "name": "Kokoro",
            "lang_code": self._lang_code,
        }


def create_kokoro_backend(**kwargs: Any) -> KokoroBackend:
    """Factory callable registered with TTSBackendRegistry."""
    return KokoroBackend(**kwargs)


# --- Registration ---
from abogen.tts_backend_registry import register_backend  # noqa: E402

register_backend(
    metadata=_KOKORO_METADATA,
    factory=create_kokoro_backend,
)
