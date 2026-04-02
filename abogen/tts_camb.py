from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import numpy as np

from abogen.tts_supertonic import _ensure_float32_mono, _split_text


logger = logging.getLogger(__name__)


DEFAULT_CAMB_MODELS = ("mars-flash", "mars-pro", "mars-instruct")
DEFAULT_CAMB_VOICE_ID = 147320
DEFAULT_CAMB_LANGUAGE = "en-us"


@dataclass
class CambSegment:
    graphemes: str
    audio: np.ndarray


class CambPipeline:
    """Adapter that mimics Kokoro/SuperTonic's pipeline iteration interface for Camb AI."""

    def __init__(
        self,
        *,
        sample_rate: int,
        api_key: Optional[str] = None,
        model: str = "mars-flash",
        voice_id: int = DEFAULT_CAMB_VOICE_ID,
        language: str = DEFAULT_CAMB_LANGUAGE,
        max_chunk_length: int = 500,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.model = model if model in DEFAULT_CAMB_MODELS else "mars-flash"
        self.voice_id = int(voice_id)
        self.language = language or DEFAULT_CAMB_LANGUAGE
        self.max_chunk_length = int(max_chunk_length)

        resolved_key = api_key or os.environ.get("CAMB_API_KEY") or ""
        if not resolved_key:
            raise RuntimeError(
                "Camb AI API key is required. Set the CAMB_API_KEY environment variable "
                "or provide an API key in the settings."
            )

        try:
            from camb.client import CambAI  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError(
                "camb-sdk is not installed. Install it with `pip install camb-sdk`."
            ) from exc

        self._client = CambAI(api_key=resolved_key)

    def __call__(
        self,
        text: str,
        *,
        voice: Any,
        speed: float,
        split_pattern: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Iterator[CambSegment]:
        from camb.types.stream_tts_output_configuration import StreamTtsOutputConfiguration  # type: ignore[import-not-found]
        from camb.types.stream_tts_voice_settings import StreamTtsVoiceSettings  # type: ignore[import-not-found]

        voice_id = self.voice_id
        if isinstance(voice, int):
            voice_id = voice
        elif isinstance(voice, str):
            try:
                voice_id = int(voice)
            except (TypeError, ValueError):
                pass

        speech_model = model or self.model
        if speech_model not in DEFAULT_CAMB_MODELS:
            speech_model = "mars-flash"

        lang = language or self.language
        speed_value = float(speed) if speed is not None else 1.0
        speed_value = max(0.5, min(2.0, speed_value))

        chunks = _split_text(
            text, split_pattern=split_pattern, max_chunk_length=self.max_chunk_length
        )

        for chunk in chunks:
            try:
                stream = self._client.text_to_speech.tts(
                    text=chunk,
                    voice_id=voice_id,
                    language=lang,
                    speech_model=speech_model,
                    output_configuration=StreamTtsOutputConfiguration(
                        format="pcm_f32le",
                        sample_rate=self.sample_rate,
                    ),
                    voice_settings=StreamTtsVoiceSettings(
                        speaking_rate=speed_value,
                    ),
                )

                # Collect all streamed bytes for this chunk.
                raw_bytes = b"".join(stream)
                if not raw_bytes:
                    logger.warning("Camb AI returned empty audio for chunk: %s", chunk[:60])
                    continue

                audio = np.frombuffer(raw_bytes, dtype="<f4").astype("float32", copy=False)
                audio = _ensure_float32_mono(audio)

                if audio.size == 0:
                    continue

                yield CambSegment(graphemes=chunk, audio=audio)

            except Exception as exc:
                logger.error("Camb AI synthesis failed for chunk: %s — %s", chunk[:60], exc)
                raise
