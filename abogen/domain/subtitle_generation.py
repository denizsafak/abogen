"""Subtitle generation utilities for audiobook generation.

This module provides functions for processing TTS tokens into subtitle entries
according to various subtitle modes (Line, Sentence, Sentence + Comma,
Sentence + Highlighting).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from abogen.domain.enums import Language, SubtitleMode
from abogen.domain.split_pattern import PUNCTUATION_SENTENCE, PUNCTUATION_SENTENCE_COMMA

_CLOSING_DELIMS = "\"'”’»›)]}」』"
# Comma characters that trigger a boundary in "Sentence + Comma" mode,
# covering ASCII, Arabic, CJK fullwidth and ideographic variants.
_COMMA_CHARS = ",،，、"


def _extend_past_closing(text: str, pos: int) -> int:
    """Advance *pos* past trailing closing quotes/brackets.

    Punctuation boundaries (commas, ellipsis runs) are detected at the
    punctuation character itself, but the closing delimiters that follow
    it (e.g. the `"` in `Test,"`) belong to the same subtitle entry.
    Without this, splits land between the punctuation and its closing
    quote, producing entries like `" test likes.` and lone `"` entries.
    """
    end = len(text)
    while pos < end and text[pos] in _CLOSING_DELIMS:
        pos += 1
    return pos


def _merge_lone_closing_entries(
    subtitle_entries: List[Tuple[float, float, str]],
) -> None:
    """Merge entries holding only closing delimiters into the previous entry.

    Safety net for any boundary (spaCy or regex) that lands before a
    closing quote/bracket: an entry such as `"` or `")` carries no
    content of its own and must not appear as a standalone subtitle.
    Merged in-place; the previous entry keeps its start and takes the
    lone entry's end time.
    """
    merged: List[Tuple[float, float, str]] = []
    for start, end, text in subtitle_entries:
        stripped = text.strip()
        if (
            stripped
            and all(c in _CLOSING_DELIMS for c in stripped)
            and merged
        ):
            prev_start, _, prev_text = merged[-1]
            merged[-1] = (prev_start, end, prev_text + stripped)
        else:
            merged.append((start, end, text))
    subtitle_entries[:] = merged


def _is_sentence_boundary(
    token: dict,
    current_sentence: List[dict],
    separator: str,
) -> bool:
    """Check whether token ends a sentence, considering closing quotes and brackets."""
    ws = token.get("whitespace", "") or ""
    if not ws:
        return False

    # For Line mode, a newline in whitespace or text marks line boundary
    if separator == r"\n":
        return "\n" in ws or "\n" in str(token.get("text", ""))

    text = str(token.get("text", ""))
    if re.search(rf"{separator}[{re.escape(_CLOSING_DELIMS)}]*$", text):
        return True

    if len(current_sentence) >= 2 and text and all(c in _CLOSING_DELIMS for c in text):
        prev_text = str(current_sentence[-2].get("text", ""))
        if re.search(rf"{separator}$", prev_text):
            return True

    return False


def process_subtitle_tokens(
    tokens_with_timestamps: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    language: Language,
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
        language: Language enum value for spaCy processing.
        use_spacy_segmentation: Whether to use spaCy for sentence boundary detection.
        fallback_end_time: Fallback end time for the last entry if none is available.
    """
    if not tokens_with_timestamps:
        return

    if not isinstance(language, Language):
        try:
            language = Language.from_str(str(language))
        except ValueError:
            language = Language.EN_US

    if isinstance(subtitle_mode, SubtitleMode):
        subtitle_mode_str = subtitle_mode.value
    else:
        subtitle_mode_str = str(subtitle_mode)

    processed_tokens = tokens_with_timestamps

    # For English with spaCy enabled and sentence-based modes, use spaCy for sentence boundaries
    # spaCy is disabled when subtitle mode is "Disabled" or "Line"
    use_spacy_for_english = (
        use_spacy_segmentation
        and subtitle_mode_str not in [SubtitleMode.DISABLED.value, SubtitleMode.LINE.value, "Disabled", "Line"]
        and language in [Language.EN_US, Language.EN_GB]
        and subtitle_mode_str in [SubtitleMode.SENTENCE.value, SubtitleMode.SENTENCE_COMMA.value, "Sentence", "Sentence + Comma"]
    )

    if subtitle_mode_str in (SubtitleMode.SENTENCE_HIGHLIGHT.value, "Sentence + Highlighting"):
        _process_karaoke_highlighting(
            processed_tokens, subtitle_entries, max_subtitle_words, fallback_end_time
        )
    elif subtitle_mode_str in [
        SubtitleMode.SENTENCE.value,
        SubtitleMode.SENTENCE_COMMA.value,
        SubtitleMode.LINE.value,
        "Sentence",
        "Sentence + Comma",
        "Line",
    ]:
        if use_spacy_for_english and subtitle_mode_str not in (SubtitleMode.LINE.value, "Line"):
            _process_spacy_sentences(
                processed_tokens, subtitle_entries, max_subtitle_words,
                subtitle_mode_str, language, fallback_end_time
            )
        else:
            _process_regex_sentences(
                processed_tokens, subtitle_entries, max_subtitle_words,
                subtitle_mode_str, fallback_end_time
            )
    else:
        # Word count-based grouping (e.g., "5" for 5-word groups)
        _process_word_count(
            processed_tokens, subtitle_entries, max_subtitle_words,
            subtitle_mode_str, fallback_end_time
        )


def _process_karaoke_highlighting(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    fallback_end_time: Optional[float],
) -> None:
    """Process tokens for Sentence + Highlighting mode (karaoke effect)."""
    separator = rf"[{PUNCTUATION_SENTENCE}]"
    current_sentence = []
    word_count = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1

        is_boundary = _is_sentence_boundary(token, current_sentence, separator)
        if is_boundary or word_count >= max_subtitle_words:
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
                    try:
                        duration_cs = int(duration * 100)
                    except (ValueError, OverflowError, TypeError):
                        duration_cs = 50
                    # Add karaoke effect
                    karaoke_text += f"{{\\kf{duration_cs}}}{t.get('text', '')}{t.get('whitespace', '') or ''}"

                text_stripped = karaoke_text.strip()
                if text_stripped:
                    subtitle_entries.append(
                        (start_time, end_time, text_stripped)
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
            try:
                duration_cs = int(duration * 100)
            except (ValueError, OverflowError, TypeError):
                duration_cs = 50
            karaoke_text += f"{{\\kf{duration_cs}}}{t.get('text', '')}{t.get('whitespace', '') or ''}"
        text_stripped = karaoke_text.strip()
        if text_stripped:
            subtitle_entries.append((start_time, end_time, text_stripped))

    # Fallback for last entry
    _apply_fallback_end_time(subtitle_entries, fallback_end_time)


def _process_spacy_sentences(
    tokens: List[dict],
    subtitle_entries: List[Tuple[float, float, str]],
    max_subtitle_words: int,
    subtitle_mode: str,
    language: Language,
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

    nlp = get_spacy_model(language)
    if not nlp:
        _process_regex_sentences(
            tokens, subtitle_entries, max_subtitle_words,
            subtitle_mode, fallback_end_time
        )
        return

    # Build full text and track character positions to token indices
    full_text = ""
    for token in tokens:
        text_part = str(token.get("text", "")) + (token.get("whitespace") or "")
        full_text += text_part

    # Get sentence boundaries from spaCy
    doc = nlp(full_text)
    sentence_boundaries = [sent.end_char for sent in doc.sents]

    # For "Sentence + Comma" mode, also split on commas. The boundary
    # sits AFTER any closing quotes/brackets following the comma so that
    # e.g. `Test,"` stays together instead of stranding the `"` in the
    # next entry.
    if subtitle_mode in (SubtitleMode.SENTENCE_COMMA.value, "Sentence + Comma"):
        comma_positions = [
            _extend_past_closing(full_text, i + 1)
            for i, c in enumerate(full_text) if c in _COMMA_CHARS
        ]
        sentence_boundaries = sorted(
            set(sentence_boundaries + comma_positions)
        )

    # spaCy does not treat ellipsis ("...", "..", "…") as a sentence
    # boundary ("Lorem ipsum... Lorem..." stays one sentence), so ellipsis
    # runs followed by whitespace/end would merge into a single subtitle
    # entry. Add explicit boundaries after them (including any trailing
    # closing quotes/brackets, so `trip..."` stays together). Single dots
    # ("Mr.") stay spaCy's responsibility so abbreviations don't regress.
    for m in re.finditer(r"\.{2,}(?=[\s\"'”’»›)\]}」』]|$)|…(?=[\s\"'”’»›)\]}」』]|$)", full_text):
        sentence_boundaries.append(_extend_past_closing(full_text, m.end()))
    # Double newlines are paragraph breaks: always split, even when spaCy
    # sees no sentence boundary.
    for m in re.finditer(r"\n{2,}", full_text):
        sentence_boundaries.append(m.end())
    sentence_boundaries = sorted(set(sentence_boundaries))

    # Multi-sentence single FakeToken handling
    if len(tokens) == 1 and len(sentence_boundaries) > 1:
        single = tokens[0]
        start_time = single.get("start", 0.0) or 0.0
        end_time = single.get("end")
        duration = (end_time - start_time) if (end_time is not None and end_time > start_time) else 0.0

        prev_pos = 0
        cur_start = start_time
        total_chars = max(len(full_text), 1)

        for i, b_pos in enumerate(sentence_boundaries):
            piece = full_text[prev_pos:b_pos].strip()
            if not piece:
                prev_pos = b_pos
                continue
            if i == len(sentence_boundaries) - 1:
                cur_end = end_time if end_time is not None else (cur_start + 1.0)
            else:
                cur_end = cur_start + duration * len(piece) / total_chars
            subtitle_entries.append((cur_start, cur_end, piece))
            cur_start = cur_end
            prev_pos = b_pos

        if prev_pos < len(full_text):
            remainder = full_text[prev_pos:].strip()
            if remainder:
                remainder_end = end_time
                if remainder_end is None:
                    remainder_end = fallback_end_time
                if remainder_end is None:
                    remainder_end = cur_start
                subtitle_entries.append((cur_start, remainder_end, remainder))

        _merge_lone_closing_entries(subtitle_entries)
        _apply_fallback_end_time(subtitle_entries, fallback_end_time)
        return

    # Group tokens by sentence boundaries
    current_sentence = []
    word_count = 0
    current_char_pos = 0
    boundary_idx = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1
        text_len = len(str(token.get("text", ""))) + len(token.get("whitespace") or "")
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
                    str(t.get("text", "")) + (t.get("whitespace") or "")
                    for t in current_sentence
                ).strip()
                if sentence_text:
                    subtitle_entries.append(
                        (start_time, end_time, sentence_text)
                    )
                current_sentence = []
                word_count = 0
            while (
                boundary_idx < len(sentence_boundaries)
                and current_char_pos >= sentence_boundaries[boundary_idx]
            ):
                boundary_idx += 1

    # Add remaining tokens
    if current_sentence:
        start_time = current_sentence[0]["start"]
        end_time = current_sentence[-1]["end"]
        sentence_text = "".join(
            str(t.get("text", "")) + (t.get("whitespace") or "")
            for t in current_sentence
        ).strip()
        if sentence_text:
            subtitle_entries.append(
                (start_time, end_time, sentence_text)
            )

    _merge_lone_closing_entries(subtitle_entries)
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
    if subtitle_mode in (SubtitleMode.LINE.value, "Line"):
        separator = r"\n"
    elif subtitle_mode in (SubtitleMode.SENTENCE.value, "Sentence"):
        separator = rf"[{PUNCTUATION_SENTENCE}]"
    else:  # Sentence + Comma
        separator = rf"[{PUNCTUATION_SENTENCE_COMMA}]"

    current_sentence = []
    word_count = 0

    for token in tokens:
        current_sentence.append(token)
        word_count += 1

        # Split sentences based on separator or word count
        is_boundary = _is_sentence_boundary(token, current_sentence, separator)
        if is_boundary or word_count >= max_subtitle_words:
            if current_sentence:
                # Create subtitle entry for this sentence
                start_time = current_sentence[0]["start"]
                end_time = current_sentence[-1]["end"]

                sentence_text = "".join(
                    str(t.get("text", "")) + (t.get("whitespace") or "")
                    for t in current_sentence
                ).strip()

                if sentence_text:
                    subtitle_entries.append(
                        (start_time, end_time, sentence_text)
                    )
                current_sentence = []
                word_count = 0

    # Add any remaining tokens as a sentence (split multi-sentence FakeToken)
    if current_sentence:
        start_time = current_sentence[0]["start"]
        end_time = current_sentence[-1]["end"]

        sentence_text = "".join(
            str(t.get("text", "")) + (t.get("whitespace") or "")
            for t in current_sentence
        ).strip()

        if len(current_sentence) == 1:
            split_pat = (
                r"\n+"
                if separator == r"\n"
                else rf"(?<={separator})\s+|(?<={separator}[{re.escape(_CLOSING_DELIMS)}])\s+"
            )
            parts = [p.strip() for p in re.split(split_pat, sentence_text) if p.strip()]
            if len(parts) > 1:
                d = (end_time - start_time) if (end_time is not None and start_time is not None and end_time > start_time) else 0.0
                total_len = max(len(sentence_text), 1)
                cur_s = start_time if start_time is not None else 0.0
                for i, p in enumerate(parts):
                    if i == len(parts) - 1 and end_time is not None:
                        e = end_time
                    else:
                        e = cur_s + d * len(p) / total_len
                    subtitle_entries.append((cur_s, e, p))
                    cur_s = e
                current_sentence = []

        if current_sentence and sentence_text:
            safe_start = start_time if start_time is not None else 0.0
            safe_end = end_time
            if safe_end is None:
                safe_end = fallback_end_time
            if safe_end is None:
                safe_end = safe_start
            subtitle_entries.append((safe_start, safe_end, sentence_text))

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
                    str(t.get("text", "")) + (t.get("whitespace") or "")
                    for t in current_group
                ).strip()
                if text:
                    subtitle_entries.append(
                        (
                            current_group[0]["start"],
                            current_group[-1]["end"],
                            text,
                        )
                    )
                current_group = []
                space_count = 0

    # Add any remaining tokens
    if current_group:
        text = "".join(
            str(t.get("text", "")) + (t.get("whitespace") or "") for t in current_group
        ).strip()
        if text:
            subtitle_entries.append(
                (current_group[0]["start"], current_group[-1]["end"], text)
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
