"""
Kokoro TTS Backend

Encapsulates the Kokoro KPipeline as a TTSBackend implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

import numpy as np


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
    def metadata(self):
        from abogen.tts_backend import TTSBackendMetadata

        return TTSBackendMetadata(
            id="kokoro",
            name="Kokoro",
            description="Kokoro TTS engine",
        )

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
        from abogen.constants import VOICES_INTERNAL

        return list(VOICES_INTERNAL)

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
from abogen.tts_backend import TTSBackendMetadata  # noqa: E402
from abogen.tts_backend_registry import register_backend  # noqa: E402

register_backend(
    metadata=TTSBackendMetadata(
        id="kokoro",
        name="Kokoro",
        description="Kokoro TTS engine",
    ),
    factory=create_kokoro_backend,
)
