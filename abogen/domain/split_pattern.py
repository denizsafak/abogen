from __future__ import annotations

"""Unified split pattern logic extracted from 3 copies."""
import re


PUNCTUATION_SENTENCE = r".!?。！？"
PUNCTUATION_SENTENCE_COMMA = r".!?,。！？、，"


def get_split_pattern(language: str, subtitle_mode: str) -> str:
    """Get the appropriate split pattern based on language and subtitle mode.

    Args:
        language: Language code (a, b, e, f, etc.)
        subtitle_mode: Subtitle mode ("Sentence", "Sentence + Comma", "Line", etc.)

    Returns:
        Split pattern string
    """
    # For English, always use newline splitting only
    if language in ("a", "b"):
        return "\n"

    # Determine spacing pattern based on language
    spacing = r"\s*" if language in ("z", "j") else r"\s+"

    # For CJK languages, when subtitle mode is Disabled or Line, prefer
    # punctuation-based splitting instead of plain newline splitting.
    if subtitle_mode in ("Disabled", "Line") and language in ("z", "j"):
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"

    if subtitle_mode == "Line":
        return "\n"
    elif subtitle_mode == "Sentence":
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"
    elif subtitle_mode == "Sentence + Comma":
        return rf"(?<=[{PUNCTUATION_SENTENCE_COMMA}]){spacing}|\n+"
    else:
        return r"\n+"
