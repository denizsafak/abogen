from __future__ import annotations

import ast
from dataclasses import dataclass
import logging
import math
import re
from typing import Any, Iterable, Iterator, Optional

import numpy as np


logger = logging.getLogger(__name__)


DEFAULT_SUPERTONIC_VOICES = ("M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5")


@dataclass
class SupertonicSegment:
    graphemes: str
    audio: np.ndarray


def _ensure_float32_mono(wav: Any) -> np.ndarray:
    arr = np.asarray(wav, dtype="float32")
    if arr.ndim == 2:
        # (n, 1) or (1, n) or (n, channels)
        if arr.shape[0] == 1 and arr.shape[1] > 1:
            arr = arr.reshape(-1)
        else:
            arr = arr[:, 0]
    return arr.reshape(-1)


def _resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    if audio.size == 0:
        return audio
    ratio = dst_rate / float(src_rate)
    new_len = int(round(audio.size * ratio))
    if new_len <= 1:
        return np.zeros(0, dtype="float32")
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype("float32", copy=False)


def _split_text(text: str, *, split_pattern: Optional[str], max_chunk_length: int) -> list[str]:
    stripped = (text or "").strip()
    if not stripped:
        return []
    parts: list[str]
    if split_pattern:
        try:
            parts = [p.strip() for p in re.split(split_pattern, stripped) if p.strip()]
        except re.error:
            parts = [stripped]
    else:
        parts = [stripped]

    # Enforce max length by hard-splitting long parts.
    result: list[str] = []
    for part in parts:
        if len(part) <= max_chunk_length:
            result.append(part)
            continue
        start = 0
        while start < len(part):
            end = min(len(part), start + max_chunk_length)
            # Try to split at whitespace.
            if end < len(part):
                ws = part.rfind(" ", start, end)
                if ws > start + 40:
                    end = ws
            chunk = part[start:end].strip()
            if chunk:
                result.append(chunk)
            start = end
    return result


_UNSUPPORTED_CHARS_RE = re.compile(r"unsupported character\(s\):\s*(\[[^\]]*\])", re.IGNORECASE)


def _parse_unsupported_characters(error: BaseException) -> list[str]:
    """Best-effort extraction of unsupported characters from SuperTonic errors."""

    message = " ".join(str(part) for part in getattr(error, "args", ()) if part is not None) or str(error)
    match = _UNSUPPORTED_CHARS_RE.search(message)
    if not match:
        return []

    raw = match.group(1)
    try:
        value = ast.literal_eval(raw)
    except Exception:
        return []

    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item)
            if s:
                out.append(s)
        return out

    if isinstance(value, str) and value:
        return [value]

    return []


def _remove_unsupported_characters(text: str, unsupported: Iterable[str]) -> str:
    result = text
    for item in unsupported:
        if not item:
            continue
        result = result.replace(item, "")
    return result


def _configure_supertonic_gpu() -> None:
    """Patch supertonic's config to enable GPU acceleration if available."""
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        
        # Use CUDA if available, skip TensorRT (requires extra libs not always present)
        # TensorrtExecutionProvider may be listed as available but fail at runtime
        # if TensorRT libraries (libnvinfer.so) are not installed
        providers = []
        if "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        
        # Patch supertonic's config and loader before TTS import
        # We must patch both because loader imports the value at module load time
        import supertonic.config as supertonic_config
        import supertonic.loader as supertonic_loader
        supertonic_config.DEFAULT_ONNX_PROVIDERS = providers
        supertonic_loader.DEFAULT_ONNX_PROVIDERS = providers
        logger.info("Supertonic ONNX providers configured: %s", providers)
    except Exception as exc:
        logger.warning("Could not configure supertonic GPU providers: %s", exc)


class SupertonicPipeline:
    """Minimal adapter that mimics Kokoro's pipeline iteration interface."""

    def __init__(
        self,
        *,
        sample_rate: int,
        auto_download: bool = True,
        total_steps: int = 5,
        max_chunk_length: int = 300,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.total_steps = int(total_steps)
        self.max_chunk_length = int(max_chunk_length)

        # Configure GPU providers before importing TTS
        _configure_supertonic_gpu()

        try:
            from supertonic import TTS  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Supertonic is not installed. Install it with `pip install supertonic`."
            ) from exc

        self._tts = TTS(auto_download=auto_download)

    def __call__(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        split_pattern: Optional[str] = None,
        total_steps: Optional[int] = None,
    ) -> Iterator[SupertonicSegment]:
        voice_name = (voice or "").strip() or "M1"
        steps = int(total_steps) if total_steps is not None else self.total_steps
        steps = max(2, min(15, steps))
        speed_value = float(speed) if speed is not None else 1.0
        speed_value = max(0.7, min(2.0, speed_value))

        style = self._tts.get_voice_style(voice_name=voice_name)
        chunks = _split_text(text, split_pattern=split_pattern, max_chunk_length=self.max_chunk_length)
        for chunk in chunks:
            chunk_to_speak = chunk
            removed: set[str] = set()
            last_exc: Exception | None = None

            # SuperTonic can raise ValueError for unsupported characters; strip and retry.
            for attempt in range(3):
                try:
                    wav, duration = self._tts.synthesize(
                        text=chunk_to_speak,
                        voice_style=style,
                        total_steps=steps,
                        speed=speed_value,
                        max_chunk_length=self.max_chunk_length,
                        silence_duration=0.0,
                        verbose=False,
                    )
                    break
                except ValueError as exc:
                    last_exc = exc
                    unsupported = _parse_unsupported_characters(exc)
                    if not unsupported:
                        raise

                    removed.update(unsupported)
                    sanitized = _remove_unsupported_characters(chunk_to_speak, unsupported).strip()

                    # If we didn't change anything, don't loop forever.
                    if sanitized == chunk_to_speak.strip():
                        raise

                    chunk_to_speak = sanitized
                    if not chunk_to_speak:
                        logger.warning(
                            "SuperTonic: dropped a chunk after removing unsupported characters: %s",
                            sorted(removed),
                        )
                        break

                    if attempt == 0:
                        logger.warning(
                            "SuperTonic: removed unsupported characters %s and retried.",
                            sorted(removed),
                        )
            else:
                # Exhausted retries.
                assert last_exc is not None
                raise last_exc

            if not chunk_to_speak:
                continue

            audio = _ensure_float32_mono(wav)

            # If duration is present, infer the source sample rate and resample if needed.
            src_rate = self.sample_rate
            try:
                dur = float(duration)
                if dur > 0 and audio.size > 0:
                    inferred = int(round(audio.size / dur))
                    if 8000 <= inferred <= 96000:
                        src_rate = inferred
            except Exception:
                pass

            if src_rate != self.sample_rate:
                audio = _resample_linear(audio, src_rate, self.sample_rate)

            yield SupertonicSegment(graphemes=chunk_to_speak, audio=audio)
