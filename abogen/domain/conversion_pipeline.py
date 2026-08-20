"""Shared TTS emission pipeline.

Provides the core TTS emission loop used by both WebUI and PyQt conversion runners.
The caller handles audio I/O, progress reporting, and subtitle writing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from abogen.domain.enums import Language, SubtitleMode
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np

from abogen.domain.audio_helpers import to_float32
from abogen.domain.normalization import prepare_text_for_tts
from abogen.domain.tokens import FakeToken
from abogen.domain.audio_buffer import SAMPLE_RATE

logger = logging.getLogger(__name__)

# Languages where spaCy is used for pre-TTS segmentation
# English ("a", "b") is excluded — spaCy only used for post-TTS subtitles
_SPACY_EXCLUDED_LANGS = {Language.EN_US, Language.EN_GB}

# CJK languages — different spacing pattern
_CJK_LANGS = {Language.ZH, Language.JA}


def spacy_pre_tts_segmentation(
    text: str,
    lang_code: Any,
    subtitle_mode: Any,
    *,
    is_subtitle_input: bool = False,
    use_spacy_segmentation: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[str], str]:
    """Segment text using spaCy before TTS, with split_pattern override.

    For non-English languages, spaCy sentence segmentation produces better
    sentence boundaries than regex. This function:
    1. Checks if spaCy should be used (toggle on, not disabled mode, not subtitle input)
    2. For non-English: runs spaCy segmentation, computes split_pattern override
    3. For English: returns single segment with default pattern (spaCy only for subtitles)
    4. If spaCy fails: falls back to default pattern

    Args:
        text: Text to segment.
        lang_code: Language code (Language enum or string like "a", "de", "fr").
        subtitle_mode: SubtitleMode enum or string.
        is_subtitle_input: True if source is .srt/.ass/.vtt file.
        use_spacy_segmentation: User toggle for spaCy segmentation.
        log_callback: Optional logging function.

    Returns:
        Tuple of (text_segments, active_split_pattern).
        text_segments is a list of sentences (always at least one element).
        active_split_pattern is the regex to use for TTS backend splitting.
    """
    from abogen.domain.split_pattern import PUNCTUATION_COMMAS, get_split_pattern

    def _log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    # Normalize language
    lang_enum = _to_language_enum(lang_code)

    # Default split pattern
    default_split = get_split_pattern(lang_code, subtitle_mode)

    # Check conditions
    if not use_spacy_segmentation:
        return [text], default_split

    subtitle_mode_str = _to_subtitle_mode_str(subtitle_mode)
    if subtitle_mode_str in ("Disabled", "Line"):
        return [text], default_split

    if is_subtitle_input:
        return [text], default_split

    # English: spaCy only for post-TTS subtitles, not pre-TTS
    if lang_enum in _SPACY_EXCLUDED_LANGS:
        return [text], default_split

    # Non-English: run spaCy pre-TTS segmentation
    from abogen.spacy_utils import segment_sentences

    _log("Using spaCy for sentence segmentation (pre-TTS)...")
    spacy_sentences = segment_sentences(text, lang_code, log_callback=log_callback)

    if not spacy_sentences:
        _log("spaCy: Fallback to default segmentation...")
        return [text], default_split

    _log(f"spaCy: Text segmented into {len(spacy_sentences)} sentences...")

    # Compute split_pattern override based on subtitle mode
    spacing_pattern = r"\s*" if lang_enum in _CJK_LANGS else r"\s+"

    if subtitle_mode_str == "Sentence + Comma":
        active_split = r"(?<=[{}]){}|\n+".format(PUNCTUATION_COMMAS, spacing_pattern)
    else:
        # Sentence mode: spaCy already split, only split on newlines
        active_split = "\n"

    return spacy_sentences, active_split


def _to_language_enum(lang_code: Any) -> Language:
    """Convert lang_code to Language enum (ISO code or Language enum)."""
    try:
        return Language.from_str(str(lang_code))
    except ValueError:
        return Language.EN_US


def _to_subtitle_mode_str(subtitle_mode: Any) -> str:
    """Convert subtitle_mode to string."""
    if isinstance(subtitle_mode, SubtitleMode):
        return subtitle_mode.value
    return str(subtitle_mode)


@dataclass
class SegmentResult:
    """One TTS segment emitted by the pipeline."""
    graphemes: str
    audio: np.ndarray
    duration: float
    chunk_start: float
    tokens: List[Dict[str, Any]] = field(default_factory=list)


def tts_segments(
    text: str,
    *,
    backend: Any,
    voice: Any,
    speed: float,
    split_pattern: str,
    current_time: float = 0.0,
    total_steps: Optional[int] = None,
) -> Iterator[SegmentResult]:
    """Invoke TTS backend on (already normalized) text and yield SegmentResults.

    Use this when you've already normalized the text yourself (e.g. after
    spaCy sentence segmentation). For raw text, use emit_text_segments() instead.

    Args:
        text: Already-normalized text to synthesize.
        backend: TTS pipeline callable.
        voice: Resolved voice.
        speed: TTS speed multiplier.
        split_pattern: Regex pattern for sentence splitting.
        current_time: Current position in the audio timeline (seconds).
        total_steps: Inference quality steps (Supertonic only, ignored by Kokoro).

    Yields:
        SegmentResult for each non-empty TTS segment.
    """
    kwargs: dict[str, Any] = dict(
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
    )
    if total_steps is not None:
        kwargs["total_steps"] = total_steps

    segment_iter = backend(text, **kwargs)

    chunk_start = current_time

    for segment in segment_iter:
        graphemes_raw = getattr(segment, "graphemes", "") or ""
        graphemes = graphemes_raw.strip()

        audio = to_float32(getattr(segment, "audio", None))
        if audio.size == 0:
            continue

        duration = len(audio) / SAMPLE_RATE

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


def emit_text_segments(
    text: str,
    *,
    backend: Any,
    voice: Any,
    speed: float,
    split_pattern: str,
    current_time: float = 0.0,
    total_steps: Optional[int] = None,
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

    yield from tts_segments(
        normalized,
        backend=backend,
        voice=voice,
        speed=speed,
        split_pattern=split_pattern,
        current_time=current_time,
        total_steps=total_steps,
    )


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
    subtitle_lang: Language = Language.EN_US,
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
        _use_spacy = subtitle_mode not in (SubtitleMode.DISABLED, SubtitleMode.LINE)
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
