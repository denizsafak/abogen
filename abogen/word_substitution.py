"""
Word substitution module for text-to-speech preprocessing.

This module provides functionality to:
- Replace words/phrases with custom text
- Convert ALL CAPS to lowercase
- Convert numerals to words
- Fix nonstandard punctuation for TTS compatibility

All substitutions preserve special markers (chapter, voice, metadata, timestamps).
"""

import re

from abogen.subtitle_utils import (
    _CHAPTER_MARKER_PATTERN,
    _VOICE_MARKER_PATTERN,
    _METADATA_TAG_PATTERN,
    _TIMESTAMP_ONLY_PATTERN,
)


def apply_word_substitutions(
    text,
    substitutions_list_str,
    case_sensitive=False,
    replace_all_caps=False,
    replace_numerals=False,
    fix_nonstandard_punctuation=False,
):
    """
    Apply word substitutions to text while preserving markers.

    Args:
        text: Input text
        substitutions_list_str: Newline-separated "Word|NewWord" pairs
        case_sensitive: If True, match words case-sensitively
        replace_all_caps: Convert ALL CAPS words to lowercase
        replace_numerals: Convert numbers to words
        fix_nonstandard_punctuation: Fix curly quotes, em/en dashes, etc.

    Returns:
        Modified text
    """
    # Apply nonstandard punctuation fixes FIRST (if enabled)
    if fix_nonstandard_punctuation:
        text = fix_punctuation(text)

    # Parse substitutions list
    substitutions = parse_substitutions_list(substitutions_list_str)

    # Split text into segments (markers vs content)
    segments = split_text_preserving_markers(text)

    # Process each segment
    processed_segments = []
    for segment_type, segment_text in segments:
        if segment_type == "marker":
            # Preserve markers unchanged
            processed_segments.append(segment_text)
        else:
            # Apply substitutions to content
            processed_text = segment_text

            # Apply word substitutions
            if substitutions:
                processed_text = apply_word_replacements(
                    processed_text, substitutions, case_sensitive
                )

            # Apply ALL CAPS conversion
            if replace_all_caps:
                processed_text = convert_all_caps_to_lowercase(processed_text)

            # Apply numeral conversion
            if replace_numerals:
                processed_text = convert_numerals_to_words(processed_text)

            processed_segments.append(processed_text)

    return "".join(processed_segments)


def parse_substitutions_list(substitutions_str):
    """
    Parse newline-separated "Word|NewWord" format.

    Args:
        substitutions_str: String with substitutions, one per line

    Returns:
        List of tuples: [(word, replacement), ...]
    """
    substitutions = []
    for line in substitutions_str.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue

        parts = line.split("|", 1)
        if len(parts) == 2:
            word = parts[0].strip()
            replacement = parts[1].strip()
            if word:  # Only add if word is not empty
                substitutions.append((word, replacement))

    return substitutions


def split_text_preserving_markers(text):
    """
    Split text into segments alternating between markers and content.

    Args:
        text: Input text with potential markers

    Returns:
        List of tuples: [("marker"|"content", text), ...]
    """
    # Combined pattern for all markers and timestamps
    marker_pattern = re.compile(
        r"(<<CHAPTER_MARKER:[^>]*>>|<<VOICE:[^>]*>>|<<METADATA_[^:]+:[^>]*>>|\d{1,2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)"
    )

    segments = []
    last_end = 0

    for match in marker_pattern.finditer(text):
        # Content before marker
        if match.start() > last_end:
            segments.append(("content", text[last_end : match.start()]))

        # Marker itself
        segments.append(("marker", match.group(0)))
        last_end = match.end()

    # Remaining content after last marker
    if last_end < len(text):
        segments.append(("content", text[last_end:]))

    return segments


def apply_word_replacements(text, substitutions, case_sensitive=False):
    """
    Apply word substitutions using whole-word matching.

    Args:
        text: Input text
        substitutions: List of (word, replacement) tuples
        case_sensitive: If True, match case-sensitively

    Returns:
        Text with substitutions applied
    """
    for word, replacement in substitutions:
        # Use word boundaries for exact matching
        # Escape special regex characters
        escaped_word = re.escape(word)
        pattern = re.compile(
            r"\b" + escaped_word + r"\b",
            0 if case_sensitive else re.IGNORECASE,
        )
        text = pattern.sub(replacement, text)

    return text


def convert_all_caps_to_lowercase(text):
    """
    Convert ALL CAPS words to lowercase.

    Args:
        text: Input text

    Returns:
        Text with ALL CAPS converted to lowercase
    """

    def replace_caps(match):
        word = match.group(0)
        # Convert to lowercase
        return word.lower()

    # Match words that are ALL CAPS (2+ letters)
    pattern = re.compile(r"\b[A-Z]{2,}\b")
    return pattern.sub(replace_caps, text)


def convert_numerals_to_words(text):
    """
    Convert numerals to words using num2words library.

    Args:
        text: Input text

    Returns:
        Text with numerals converted to words
    """
    try:
        from num2words import num2words
    except ImportError:
        # If num2words not available, return unchanged
        return text

    def replace_number(match):
        try:
            number = int(match.group(0))
            # Convert to words in English
            return num2words(number)
        except Exception:
            # If conversion fails, return original
            return match.group(0)

    # Match integers (but not timestamps or other patterns)
    # Negative lookbehind/ahead to avoid timestamps
    pattern = re.compile(r"(?<!\d:)\b\d+\b(?!:\d)")
    return pattern.sub(replace_number, text)


def fix_punctuation(text):
    """
    Convert nonstandard punctuation to standard equivalents.

    This helps TTS engines pronounce words correctly by converting:
    - Curly quotes to straight quotes
    - Ellipsis to three periods

    Args:
        text: Input text

    Returns:
        Text with nonstandard punctuation fixed
    """
    # Define replacements
    replacements = {
        # Curly double quotes
        "\u201c": '"',  # Left double quotation mark
        "\u201d": '"',  # Right double quotation mark
        "\u201e": '"',  # Double low-9 quotation mark
        # Curly single quotes
        "\u2018": "'",  # Left single quotation mark
        "\u2019": "'",  # Right single quotation mark
        "\u201a": "'",  # Single low-9 quotation mark
        "\u201b": "'",  # Single high-reversed-9 quotation mark
        # Other punctuation
        "\u2026": "...",  # Ellipsis
    }

    # Apply all replacements
    for old_char, new_char in replacements.items():
        text = text.replace(old_char, new_char)

    return text
