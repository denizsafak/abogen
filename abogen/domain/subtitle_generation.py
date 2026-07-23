"""Subtitle generation utilities for audiobook generation.

This module provides functions for processing TTS tokens into subtitle entries
according to various subtitle modes (Line, Sentence, Sentence + Comma,
Sentence + Highlighting).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from abogen.domain.enums import Language, SubtitleMode


# Punctuation constants for sentence splitting
PUNCTUATION_SENTENCE = ".!?\u061f\u3002\uff01\uff1f"  # .!? .?. ??
PUNCTUATION_SENTENCE_COMMA = ".!?,\u3001\u061f\u3002\uff01\uff0c\uff1f"  # .!?, ,. ??


def process_subtitle_tokens(
    tokens_with_timestamps: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    lang_code: str,
    use_spacy_segmentation: bool = False,
    fallback_end_time: Optional[float] = None,
) -> None:
    """Process TTS tokens into subtitle entries according to the subtitle mode.
    
    This function modifies subtitle_entries in-place by appending new entries.
    
    Args:
        tokens_with_timestamps: List of token dictionaries with 'start', 'end', 'text',
            and 'whitespace' keys.
        subtitle_entries: List to append subtitle entries to (modified in-place).
            Each entry is a tuple of (start_time, end_time, text).
        max_subtitle_words: Maximum number of words per subtitle entry.
        subtitle_mode: One of "Disabled", "Line", "Sentence", "Sentence + Comma",
            "Sentence + Highlighting", or a string like "5" for word-count mode.
        lang_code: Language code for spaCy processing (e.g., "a" for English).
        use_spacy_segmentation: Whether to use spaCy for sentence boundary detection.
        fallback_end_time: Fallback end time for the last entry if none is available.
    """
    if not tokens_with_timestamps:
        return

    processed_tokens = tokens_with_timestamps

    # For English with spaCy enabled and sentence-based modes, use spaCy for sentence boundaries
    # spaCy is disabled when subtitle mode is "Disabled" or "Line"
    use_spacy_for_english = (
        use_spacy_segmentation
        and subtitle_mode not in [SubtitleMode.DISABLED, SubtitleMode.LINE]
        and lang_code in [Language.EN_US, Language.EN_GB]
        and subtitle_mode in [SubtitleMode.SENTENCE, SubtitleMode.SENTENCE_COMMA]
    )

    if subtitle_mode == SubtitleMode.SENTENCE_HIGHLIGHT:
        _process_karaoke_highlighting(
            processed_tokens, subtitle_entries, max_subtitle_words, fallback_end_time
        )
    elif subtitle_mode in [SubtitleMode.SENTENCE, SubtitleMode.SENTENCE_COMMA, SubtitleMode.LINE]:
        if use_spacy_for_english and subtitle_mode != SubtitleMode.LINE:
            _process_spacy_sentences(
                processed_tokens, subtitle_entries, max_subtitle_words,
                subtitle_mode, lang_code, fallback_end_time
            )
        else:
            _process_regex_sentences(
                processed_tokens, subtitle_entries, max_subtitle_words,
                subtitle_mode, fallback_end_time
            )
    else:
        # Word count-based grouping (e.g., "5" for 5-word groups)
        _process_word_count(
            processed_tokens, subtitle_entries, max_subtitle_words,
            subtitle_mode, fallback_end_time
        )


def _process_karaoke_highlighting(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    fallback_end_time: Optional[float],
) -> None:
    """Process tokens for Sentence + Highlighting mode (karaoke effect)."""
    separator = rf"[{re.escape(PUNCTUATION_SENTENCE)}]"
    current_sentence = []
    word_count = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1

        # Split sentences based on separator or word count
        if (
            re.search(separator, token["text"]) and token.get("whitespace") == " "
        ) or word_count >= max_subtitle_words:
            if current_sentence:
                # Create karaoke subtitle entry for this sentence
                start_time = current_sentence[0]["start"]
                end_time = current_sentence[-1]["end"]

                # Generate karaoke text with timing
                karaoke_text = ""
                for t in current_sentence:
                    # Calculate duration in centiseconds
                    duration = (
                        t["end"] - t["start"]
                        if t.get("end") is not None and t.get("start") is not None
                        else 0.5
                    )
                    duration_cs = int(duration * 100)
                    # Add karaoke effect
                    karaoke_text += f"{{\\kf{duration_cs}}}{t['text']}{t.get('whitespace', '') or ''}"

                subtitle_entries.append(
                    (start_time, end_time, karaoke_text.strip())
                )
                current_sentence = []
                word_count = 0

    # Add any remaining tokens as a sentence
    if current_sentence:
        start_time = current_sentence[0]["start"]
        end_time = current_sentence[-1]["end"]

        # Generate karaoke text for remaining tokens
        karaoke_text = ""
        for t in current_sentence:
            duration = t["end"] - t["start"] if t.get("end") and t.get("start") else 0.5
            duration_cs = int(duration * 100)
            karaoke_text += f"{{\\kf{duration_cs}}}{t['text']}{t.get('whitespace', '') or ''}"
        subtitle_entries.append((start_time, end_time, karaoke_text.strip()))

    # Fallback for last entry
    _apply_fallback_end_time(subtitle_entries, fallback_end_time)


def _process_spacy_sentences(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    lang_code: str,
    fallback_end_time: Optional[float],
) -> None:
    """Process tokens using spaCy for sentence boundary detection."""
    try:
        from abogen.spacy_utils import get_spacy_model
    except ImportError:
        # Fall back to regex if spaCy is not available
        _process_regex_sentences(
            tokens, subtitle_entries, max_subtitle_words,
            subtitle_mode, fallback_end_time
        )
        return

    nlp = get_spacy_model(lang_code)
    if not nlp:
        _process_regex_sentences(
            tokens, subtitle_entries, max_subtitle_words,
            subtitle_mode, fallback_end_time
        )
        return

    # Build full text and track character positions to token indices
    full_text = ""
    for token in tokens:
        text_part = token["text"] + (token.get("whitespace") or "")
        full_text += text_part

    # Get sentence boundaries from spaCy
    doc = nlp(full_text)
    sentence_boundaries = [sent.end_char for sent in doc.sents]

    # For "Sentence + Comma" mode, also split on commas
    if subtitle_mode == SubtitleMode.SENTENCE_COMMA:
        comma_positions = [
            i + 1 for i, c in enumerate(full_text) if c == ","
        ]
        sentence_boundaries = sorted(
            set(sentence_boundaries + comma_positions)
        )

    # Group tokens by sentence boundaries
    current_sentence = []
    word_count = 0
    current_char_pos = 0
    boundary_idx = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1
        text_len = len(token["text"]) + len(token.get("whitespace") or "")
        current_char_pos += text_len

        # Check if we've hit a sentence boundary or max words
        at_boundary = (
            boundary_idx < len(sentence_boundaries)
            and current_char_pos >= sentence_boundaries[boundary_idx]
        )
        if at_boundary or word_count >= max_subtitle_words:
            if current_sentence:
                start_time = current_sentence[0]["start"]
                end_time = current_sentence[-1]["end"]
                sentence_text = "".join(
                    t["text"] + (t.get("whitespace") or "")
                    for t in current_sentence
                )
                subtitle_entries.append(
                    (start_time, end_time, sentence_text.strip())
                )
                current_sentence = []
                word_count = 0
            if at_boundary:
                boundary_idx += 1

    # Add remaining tokens
    if current_sentence:
        start_time = current_sentence[0]["start"]
        end_time = current_sentence[-1]["end"]
        sentence_text = "".join(
            t["text"] + (t.get("whitespace") or "")
            for t in current_sentence
        )
        subtitle_entries.append(
            (start_time, end_time, sentence_text.strip())
        )

    # Fallback for last entry
    _apply_fallback_end_time(subtitle_entries, fallback_end_time)


def _process_regex_sentences(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    fallback_end_time: Optional[float],
) -> None:
    """Process tokens using regex for sentence boundary detection."""
    # Define separator pattern based on mode
    if subtitle_mode == SubtitleMode.LINE:
        separator = r"\n"
    elif subtitle_mode == SubtitleMode.SENTENCE:
        # Use punctuation without comma
        separator = rf"[{re.escape(PUNCTUATION_SENTENCE)}]"
    else:  # Sentence + Comma
        # Use punctuation with comma
        separator = rf"[{re.escape(PUNCTUATION_SENTENCE_COMMA)}]"

    current_sentence = []
    word_count = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1

        # Split sentences based on separator or word count
        if (
            re.search(separator, token["text"]) and token.get("whitespace") == " "
        ) or word_count >= max_subtitle_words:
            if current_sentence:
                # Create subtitle entry for this sentence
                start_time = current_sentence[0]["start"]
                end_time = current_sentence[-1]["end"]

                # Simplified text joining logic
                sentence_text = ""
                for t in current_sentence:
                    sentence_text += t["text"] + (t.get("whitespace") or "")

                subtitle_entries.append(
                    (start_time, end_time, sentence_text.strip())
                )
                current_sentence = []
                word_count = 0

    # Add any remaining tokens as a sentence (split multi-sentence FakeToken)
    if current_sentence:
        start_time = current_sentence[0]["start"]
        end_time = current_sentence[-1]["end"]

        sentence_text = ""
        for t in current_sentence:
            sentence_text += t["text"] + (t.get("whitespace") or "")
        sentence_text = sentence_text.strip()

        if len(current_sentence) == 1:
            parts = re.split(rf"(?<={separator})\s+", sentence_text)
            if len(parts) > 1:
                d = end_time - start_time
                for i, p in enumerate(parts):
                    e = end_time if i == len(parts) - 1 else start_time + d * len(p) / len(sentence_text)
                    subtitle_entries.append((start_time, e, p.strip()))
                    start_time = e
                current_sentence = []

        if current_sentence:
            subtitle_entries.append((start_time, end_time, sentence_text))

    # Fallback for last entry
    _apply_fallback_end_time(subtitle_entries, fallback_end_time)


def _process_word_count(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    fallback_end_time: Optional[float],
) -> None:
    """Process tokens by counting spaces (word count mode)."""
    try:
        word_count = int(subtitle_mode.split()[0])
        word_count = min(word_count, max_subtitle_words)
    except (ValueError, IndexError):
        word_count = 1

    current_group = []
    space_count = 0

    for token in tokens:
        current_group.append(token)

        # Count spaces after tokens (in the whitespace field)
        if token.get("whitespace", "") == " ":
            space_count += 1

            # Split after counting N spaces
            if space_count >= word_count:
                text = "".join(
                    t["text"] + (t.get("whitespace") or "")
                    for t in current_group
                )
                subtitle_entries.append(
                    (
                        current_group[0]["start"],
                        current_group[-1]["end"],
                        text.strip(),
                    )
                )
                current_group = []
                space_count = 0

    # Add any remaining tokens
    if current_group:
        text = "".join(
            t["text"] + (t.get("whitespace") or "") for t in current_group
        )
        subtitle_entries.append(
            (current_group[0]["start"], current_group[-1]["end"], text.strip())
        )

    # Fallback for last entry
    _apply_fallback_end_time(subtitle_entries, fallback_end_time)


def _apply_fallback_end_time(
    subtitle_entries: List[Tuple[float, float, str]],
    fallback_end_time: Optional[float],
) -> None:
    """Apply fallback end time to the last entry if needed."""
    if subtitle_entries and fallback_end_time is not None:
        last_entry = subtitle_entries[-1]
        start, end, text = last_entry
        if end is None or end <= start or end <= 0:
            subtitle_entries[-1] = (start, fallback_end_time, text)
