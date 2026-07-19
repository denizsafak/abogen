"""Shared TTS emission pipeline.

Provides the core TTS emission loop used by both WebUI and PyQt conversion runners.
The caller handles audio I/O, progress reporting, and subtitle writing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

import numpy as np

from abogen.domain.audio_helpers import to_float32
from abogen.domain.normalization import prepare_text_for_tts
from abogen.domain.tokens import FakeToken
from abogen.domain.audio_buffer import SAMPLE_RATE

logger = logging.getLogger(__name__)


@dataclass
class SegmentResult:
    """One TTS segment emitted by the pipeline."""
    graphemes: str
    audio: np.ndarray
    duration: float
    chunk_start: float
    tokens: List[Dict[str, Any]] = field(default_factory=list)


def emit_text_segments(
    text: str,
    *,
    backend: Any,
    voice: Any,
    speed: float,
    split_pattern: str,
    current_time: float = 0.0,
    # normalization
    heteronym_rules: Any = None,
    pronunciation_rules: Any = None,
    normalization_overrides: Any = None,
    usage_counter: Optional[Dict[str, int]] = None,
) -> Iterator[SegmentResult]:
    """Normalize text and yield SegmentResults from the TTS backend.

    This is the innermost TTS emission loop shared by both UIs. It handles:
    1. Text normalization (heteronym + pronunciation rules)
    2. TTS backend invocation
    3. Segment iteration with token extraction

    The caller is responsible for:
    - Writing audio to sinks
    - Accumulating tokens for subtitle processing
    - Progress tracking and cancellation
    - Error handling

    Args:
        text: Raw text to synthesize.
        backend: TTS pipeline callable (kokoro or supertonic).
        voice: Resolved voice for TTS.
        speed: TTS speed multiplier.
        split_pattern: Regex pattern for sentence splitting.
        current_time: Current position in the audio timeline (seconds).
        heteronym_rules: Compiled heteronym rules.
        pronunciation_rules: Compiled pronunciation rules.
        normalization_overrides: User normalization overrides.
        usage_counter: Counter for normalization statistics.

    Yields:
        SegmentResult for each non-empty TTS segment.
    """
    source_text = str(text or "")
    normalized = prepare_text_for_tts(
        source_text,
        heteronym_rules=heteronym_rules,
        pronunciation_rules=pronunciation_rules,
        normalization_overrides=normalization_overrides,
        usage_counter=usage_counter,
    )

    segment_iter = backend(
        normalized,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
    )

    chunk_start = current_time

    for segment in segment_iter:
        graphemes_raw = getattr(segment, "graphemes", "") or ""
        graphemes = graphemes_raw.strip()

        audio = to_float32(getattr(segment, "audio", None))
        if audio.size == 0:
            continue

        duration = len(audio) / SAMPLE_RATE

        # Extract tokens with timestamps
        tokens_list = getattr(segment, "tokens", [])
        if not tokens_list and graphemes:
            tokens_list = [FakeToken(graphemes, 0, duration)]

        tokens = [
            {
                "start": chunk_start + (tok.start_ts or 0),
                "end": chunk_start + (tok.end_ts or 0),
                "text": tok.text,
                "whitespace": tok.whitespace,
            }
            for tok in tokens_list
        ]

        yield SegmentResult(
            graphemes=graphemes,
            audio=audio,
            duration=duration,
            chunk_start=chunk_start,
            tokens=tokens,
        )

        chunk_start += duration


def emit_text_to_sinks(
    text: str,
    *,
    backend: Any,
    voice: Any,
    speed: float,
    split_pattern: str,
    current_time: float = 0.0,
    # sinks
    audio_sink: Any = None,
    chapter_sink: Any = None,
    # subtitle
    subtitle_writer: Any = None,
    subtitle_mode: str = "Disabled",
    subtitle_lang: str = "a",
    max_subtitle_words: int = 50,
    use_spacy_segmentation: bool = True,
    # normalization
    heteronym_rules: Any = None,
    pronunciation_rules: Any = None,
    normalization_overrides: Any = None,
    usage_counter: Optional[Dict[str, int]] = None,
) -> tuple[int, float, List[Dict[str, Any]]]:
    """Emit TTS audio for text, writing to sinks and collecting subtitle tokens.

    Convenience wrapper around emit_text_segments() that handles audio writing
    and token accumulation. Returns stats for the caller to update progress.

    Returns:
        Tuple of (segments_emitted, new_current_time, accumulated_tokens).
    """
    from abogen.domain.subtitle_generation import process_subtitle_tokens

    segments_emitted = 0
    accumulated_tokens: List[Dict[str, Any]] = []

    for seg in emit_text_segments(
        text,
        backend=backend,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
        current_time=current_time,
        heteronym_rules=heteronym_rules,
        pronunciation_rules=pronunciation_rules,
        normalization_overrides=normalization_overrides,
        usage_counter=usage_counter,
    ):
        segments_emitted += 1

        # Write audio
        if chapter_sink:
            chapter_sink.write(seg.audio)
        if audio_sink:
            audio_sink.write(seg.audio)

        # Collect tokens
        accumulated_tokens.extend(seg.tokens)

    # Flush subtitle tokens
    if subtitle_writer and accumulated_tokens:
        _use_spacy = subtitle_mode not in ("Disabled", "Line")
        new_entries: List[tuple] = []
        process_subtitle_tokens(
            accumulated_tokens,
            new_entries,
            max_subtitle_words,
            subtitle_mode,
            subtitle_lang,
            use_spacy_segmentation=_use_spacy,
            fallback_end_time=current_time + sum(t["end"] - t["start"] for t in accumulated_tokens if accumulated_tokens),
        )
        for start, end, text_entry in new_entries:
            subtitle_writer.write_entry(start=start, end=end, text=text_entry)

    new_time = current_time
    if accumulated_tokens:
        new_time = max(t["end"] for t in accumulated_tokens)

    return segments_emitted, new_time, accumulated_tokens
