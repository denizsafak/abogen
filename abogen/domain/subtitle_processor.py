"""Subtitle-to-audio processing pipeline.

Converts subtitle files (SRT/ASS/VTT/timestamp text) into audio by
generating TTS for each entry and mixing into a buffer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

from abogen.domain.audio_buffer import (
    create_silence,
    fit_audio_to_duration,
    ffmpeg_time_stretch,
    mix_audio,
    normalize_audio,
    SAMPLE_RATE,
)
from abogen.domain.audio_helpers import to_float32
from abogen.domain.progress import calc_etr_str
from abogen.subtitle_utils import (
    parse_ass_file,
    parse_srt_file,
    parse_vtt_file,
    parse_timestamp_text_file,
)

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    """A single subtitle entry with timing."""
    start: float
    end: Optional[float]
    text: str


def parse_subtitle_file(
    file_path: str,
    is_timestamp_text: bool = False,
) -> List[Tuple[float, Optional[float], str]]:
    """Parse a subtitle file into (start, end, text) tuples.

    Args:
        file_path: Path to subtitle file.
        is_timestamp_text: Whether to treat as timestamp text file.

    Returns:
        List of (start_time, end_time, text) tuples.
    """
    if is_timestamp_text:
        return parse_timestamp_text_file(file_path)

    import os
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".srt":
        return parse_srt_file(file_path)
    elif ext == ".vtt":
        return parse_vtt_file(file_path)
    else:
        return parse_ass_file(file_path)


def format_time_range(
    start: float,
    end: Optional[float],
    is_auto_end: bool = False,
) -> str:
    """Format a time range for display in logs.

    Args:
        start: Start time in seconds.
        end: End time in seconds, or None.
        is_auto_end: Whether end time is auto-detected.

    Returns:
        Formatted string like "00:01:23,456 - 00:01:25,789" or "00:01:23 - AUTO".
    """
    def _fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int(seconds % 3600 // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        result = f"{h:02d}:{m:02d}:{s:02d}"
        if ms > 0:
            result += f",{ms:03d}"
        return result

    if is_auto_end or end is None:
        return f"{_fmt(start)} - AUTO"
    return f"{_fmt(start)} - {_fmt(end)}"


def speed_up_audio(
    audio: np.ndarray,
    speed_factor: float,
    method: str = "tts",
    *,
    backend: Any = None,
    text: str = "",
    voice: Any = None,
    base_speed: float = 1.0,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Speed up audio to fit a time window.

    Args:
        audio: Input audio buffer.
        speed_factor: Required speed multiplier.
        method: "ffmpeg" for time-stretch, "tts" for regeneration.
        backend: TTS backend (required if method="tts").
        text: Text to regenerate (required if method="tts").
        voice: Voice to use for regeneration.
        base_speed: Base speed for TTS.
        sample_rate: Sample rate.

    Returns:
        Speed-adjusted audio buffer.
    """
    if speed_factor <= 1.0:
        return audio

    if method == "ffmpeg":
        logger.info("FFmpeg time-stretch: %.2fx", speed_factor)
        return ffmpeg_time_stretch(audio, speed_factor, sample_rate)

    # TTS regeneration
    if backend is None:
        return audio
    new_speed = base_speed * speed_factor
    logger.info("Regenerating at %.2fx speed", new_speed)
    results = [
        r for r in backend(text, voice=voice, speed=new_speed, split_pattern=None)
    ]
    chunks = [r.audio for r in results]
    if not chunks:
        return audio
    return np.concatenate([to_float32(c) for c in chunks])


def process_subtitle_entries(
    subtitles: List[Tuple[float, Optional[float], str]],
    *,
    backend: Any,
    voice: Any,
    speed: float = 1.0,
    cancel_check: Callable[[], bool] = lambda: False,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    replace_newlines: bool = True,
    use_gaps: bool = False,
    is_timestamp_text: bool = False,
    subtitle_speed_method: str = "tts",
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Process subtitle entries: generate TTS for each and mix into buffer.

    This is the core domain logic for subtitle-to-audio conversion.
    UI-specific concerns (signals, widgets) are handled via callbacks.

    Args:
        subtitles: List of (start, end, text) tuples.
        backend: TTS pipeline callable.
        voice: Resolved voice for TTS.
        speed: TTS speed.
        cancel_check: Returns True if processing should stop.
        log_callback: Called with log messages.
        progress_callback: Called with (percent, etr_string).
        replace_newlines: Replace \\n with spaces in text.
        use_gaps: Whether to use silent gaps between subtitles.
        is_timestamp_text: Whether input is timestamp text.
        subtitle_speed_method: "ffmpeg" or "tts" for speed adjustment.
        sample_rate: Audio sample rate.

    Returns:
        Mixed audio buffer (float32).
    """
    if not subtitles:
        return np.array([], dtype="float32")

    max_end = max((end for _, end, _ in subtitles if end is not None), default=0)
    buffer_samples = int(max_end * sample_rate) + sample_rate
    audio_buffer = np.zeros(buffer_samples, dtype="float32")
    etr_start = time.time()
    total = len(subtitles)

    for idx, (start_time, end_time, text) in enumerate(subtitles, 1):
        if cancel_check():
            break

        processed_text = text.replace("\n", " ") if replace_newlines else text
        next_start = (
            subtitles[idx][0]
            if (use_gaps and idx < total)
            else float("inf")
        )
        subtitle_duration = None if end_time is None else end_time - start_time

        is_auto_end = is_timestamp_text or (use_gaps and idx == total) or end_time is None
        if log_callback:
            log_callback(
                f"\n[{idx}/{total}] {format_time_range(start_time, end_time, is_auto_end)}: {processed_text}"
            )

        # Generate TTS
        results = [
            r for r in backend(
                processed_text, voice=voice, speed=speed, split_pattern=None
            )
            if not cancel_check()
        ]
        if cancel_check():
            break

        audio_chunks = [r.audio for r in results]
        full_audio = (
            np.concatenate([to_float32(a) for a in audio_chunks])
            if audio_chunks
            else np.zeros(int((subtitle_duration or 0) * sample_rate), dtype="float32")
        )
        audio_duration = len(full_audio) / sample_rate

        # Timing adjustment
        if is_timestamp_text:
            end_time = start_time + audio_duration
            subtitle_duration = audio_duration
        elif use_gaps:
            end_time = min(start_time + audio_duration, next_start)
            subtitle_duration = end_time - start_time
        elif subtitle_duration is None:
            subtitle_duration = audio_duration
            end_time = start_time + audio_duration

        # Speed up if needed
        speedup_threshold = next_start - start_time if use_gaps else subtitle_duration
        if audio_duration > speedup_threshold and speedup_threshold > 0:
            speed_factor = audio_duration / speedup_threshold
            full_audio = speed_up_audio(
                full_audio, speed_factor,
                method=subtitle_speed_method,
                backend=backend, text=processed_text,
                voice=voice, base_speed=speed,
                sample_rate=sample_rate,
            )
            audio_duration = len(full_audio) / sample_rate

        # Adjust duration after speed change
        if use_gaps:
            end_time = min(start_time + audio_duration, next_start)
            subtitle_duration = end_time - start_time
        elif subtitle_duration is None:
            subtitle_duration = audio_duration
            end_time = start_time + audio_duration

        # Pad or trim to subtitle duration
        full_audio = fit_audio_to_duration(full_audio, subtitle_duration, sample_rate)

        # Mix into buffer
        start_sample = int(start_time * sample_rate)
        audio_buffer = mix_audio(audio_buffer, full_audio, start_sample)

        # Progress
        if progress_callback:
            percent = min(int(idx / total * 100), 99)
            etr = calc_etr_str(time.time() - etr_start, idx, total)
            progress_callback(percent, etr)

    # Normalize if needed
    if np.abs(audio_buffer).max() > 1.0:
        logger.info("Normalizing audio (peak: %.2f)", np.abs(audio_buffer).max())
        audio_buffer = normalize_audio(audio_buffer)

    return audio_buffer
