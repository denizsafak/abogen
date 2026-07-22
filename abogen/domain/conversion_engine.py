"""Shared TTS iteration loop used by both WebUI and PyQt conversion runners.

The core pattern is identical across both UIs:

    for seg in tts_segments(text, backend, voice, speed, split_pattern, current_time):
        check_cancel()
        update_progress(seg)
        write_audio(seg, sink)
        accumulate_subtitles(seg)

After the loop, the caller processes accumulated subtitle tokens.

This module provides ``run_tts_segment_loop`` which encapsulates that
iteration, and ``synthesize_text`` which adds normalization on top —
the single entry point both UIs should call for text-to-speech.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol

from abogen.domain.audio_sink import AudioSink
from abogen.domain.conversion_pipeline import tts_segments
from abogen.domain.normalization import TTSContext
from abogen.domain.progress import calc_etr_str
from abogen.domain.subtitle_generation import process_subtitle_tokens


class CancelChecker(Protocol):
    """Returns True if conversion has been cancelled."""
    def __call__(self) -> bool: ...


@dataclass
class SegmentStats:
    """Running statistics updated per TTS segment."""
    processed_chars: int = 0
    current_time: float = 0.0
    etr_start_time: float = field(default_factory=time.time)
    total_characters: int = 0


@dataclass
class SegmentInfo:
    """Read-only info about a TTS segment, passed to on_segment callback."""
    graphemes: str
    audio: Any
    tokens: list
    duration: float
    chunk_start: float


def run_tts_segment_loop(
    *,
    text: str,
    backend: Any,
    voice: Any,
    speed: float,
    split_pattern: str,
    stats: SegmentStats,
    check_cancel: CancelChecker,
    on_progress: Callable[[int, str], None],
    chapter_sink: Optional[AudioSink] = None,
    audio_sink: Optional[AudioSink] = None,
    preview_callback: Optional[Callable[[str], None]] = None,
    on_segment: Optional[Callable[[SegmentInfo], None]] = None,
    subtitle_mode: str = "Disabled",
    max_subtitle_words: int = 50,
    lang_code: str = "a",
    use_spacy_segmentation: bool = False,
) -> tuple[int, list]:
    """Run the core TTS segment iteration loop.

    Args:
        text: Normalized text to synthesize.
        backend: TTS pipeline instance (Kokoro or Supertonic).
        voice: Voice name/id for the backend.
        speed: Speech speed multiplier.
        split_pattern: Regex pattern used by the TTS engine for sentence splitting.
        stats: Running character/timing stats (mutated in place).
        check_cancel: Called each segment; if it returns True, iteration stops.
        on_progress: Called with (percent, etr_str) after each segment.
        chapter_sink: Optional audio sink for the current chapter.
        audio_sink: Optional audio sink for the merged output.
        preview_callback: Called with a short preview string per segment.
        on_segment: Called with a SegmentInfo for each segment *before*
            audio is written.  Useful for callers that need per-segment
            subtitle processing (e.g. PyQt dual-writer pattern).
            When provided, the default subtitle accumulation is skipped.
        subtitle_mode: Subtitle mode string (e.g. "Disabled", "Sentence").
        max_subtitle_words: Max words per subtitle entry.
        lang_code: Language code for subtitle processing.
        use_spacy_segmentation: Whether spaCy sentence boundaries are active.

    Returns:
        Tuple of (segment_count, accumulated_subtitle_tokens).
        The caller is responsible for processing subtitle tokens via
        ``process_subtitle_tokens`` and writing entries to subtitle writers.
    """
    local_segments = 0
    accumulated_tokens: list[dict] = []

    for seg in tts_segments(
        text,
        backend=backend,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
        current_time=stats.current_time,
    ):
        if check_cancel():
            break

        local_segments += 1
        stats.processed_chars += len(seg.graphemes)

        # Progress
        if stats.total_characters:
            percent = min(int(stats.processed_chars / stats.total_characters * 100), 99)
        else:
            percent = 0 if stats.processed_chars == 0 else 99

        etr_str = calc_etr_str(
            time.time() - stats.etr_start_time,
            stats.processed_chars,
            stats.total_characters,
        )
        on_progress(percent, etr_str)

        # Preview / log
        if preview_callback:
            preview_callback(seg.graphemes or "[silence]")

        # Per-segment callback (for callers needing segment-level access)
        if on_segment:
            info = SegmentInfo(
                graphemes=seg.graphemes,
                audio=seg.audio,
                tokens=list(seg.tokens) if seg.tokens else [],
                duration=seg.duration,
                chunk_start=getattr(seg, "chunk_start", stats.current_time),
            )
            on_segment(info)

        # Write audio
        if chapter_sink:
            chapter_sink.write(seg.audio)
        if audio_sink:
            audio_sink.write(seg.audio)

        # Accumulate subtitle tokens (default path; skipped if on_segment handles it)
        if not on_segment and subtitle_mode != "Disabled" and seg.tokens:
            accumulated_tokens.extend(seg.tokens)

        # Update timing
        if audio_sink:
            stats.current_time += seg.duration

    return local_segments, accumulated_tokens


def process_and_write_subtitles(
    accumulated_tokens: list[dict],
    subtitle_writer: Any,
    *,
    subtitle_mode: str,
    max_subtitle_words: int,
    lang_code: str,
    use_spacy_segmentation: bool,
    fallback_end_time: float,
) -> None:
    """Process accumulated subtitle tokens and write entries to a subtitle writer.

    This is the standard subtitle post-processing step shared by both UIs.
    """
    if not accumulated_tokens or not subtitle_writer:
        return
    new_entries: list[tuple] = []
    process_subtitle_tokens(
        accumulated_tokens,
        new_entries,
        max_subtitle_words,
        subtitle_mode,
        lang_code,
        use_spacy_segmentation=use_spacy_segmentation,
        fallback_end_time=fallback_end_time,
    )
    for start, end, text in new_entries:
        subtitle_writer.write_entry(start=start, end=end, text=text)


@dataclass(frozen=True)
class SynthParams:
    """Common parameters for synthesize_text calls.

    Packed once by the executor to avoid repeating identical kwargs.
    When adding new common params, change only this dataclass.
    """
    tts_context: TTSContext
    stats: SegmentStats
    check_cancel: CancelChecker
    on_progress: Callable[[int, str], None]
    audio_sink: Optional[AudioSink] = None
    subtitle_mode: str = "Disabled"
    max_subtitle_words: int = 50
    lang_code: str = "a"
    use_spacy_segmentation: bool = False


def synthesize_text(
    *,
    text: str,
    params: SynthParams,
    backend: Any,
    voice: Any,
    speed: float,
    chapter_sink: Optional[AudioSink] = None,
    preview_callback: Optional[Callable[[str], None]] = None,
    on_segment: Optional[Callable[[SegmentInfo], None]] = None,
    split_pattern_override: Optional[str] = None,
) -> tuple[int, list]:
    """Normalize text and run TTS — the single entry point for both UIs.

    Combines TTSContext.normalize() + run_tts_segment_loop() into one call.
    UI-specific concerns (provider resolution, progress display) stay in the UI.
    """
    normalized = params.tts_context.normalize(text)
    return run_tts_segment_loop(
        text=normalized,
        backend=backend,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern_override or params.tts_context.split_pattern,
        stats=params.stats,
        check_cancel=params.check_cancel,
        on_progress=params.on_progress,
        chapter_sink=chapter_sink,
        audio_sink=params.audio_sink,
        preview_callback=preview_callback,
        on_segment=on_segment,
        subtitle_mode=params.subtitle_mode,
        max_subtitle_words=params.max_subtitle_words,
        lang_code=params.lang_code,
        use_spacy_segmentation=params.use_spacy_segmentation,
    )
