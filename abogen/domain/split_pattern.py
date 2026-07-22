from __future__ import annotations

"""Unified split pattern logic extracted from 3 copies."""
import re

from abogen.domain.enums import Language, SubtitleMode

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
    try:
        lang = Language.from_str(language) if not isinstance(language, Language) else language
    except ValueError:
        lang = None  # unknown language — treat as non-English, non-CJK
    try:
        mode = SubtitleMode.from_str(subtitle_mode) if not isinstance(subtitle_mode, SubtitleMode) else subtitle_mode
    except ValueError:
        mode = SubtitleMode.DISABLED

    # For English, always use newline splitting only
    if lang in (Language.EN_US, Language.EN_GB):
        return "\n"

    # Determine spacing pattern based on language
    spacing = r"\s*" if lang and lang.is_cjk else r"\s+"

    # For CJK languages, when subtitle mode is Disabled or Line, prefer
    # punctuation-based splitting instead of plain newline splitting.
    if mode in (SubtitleMode.DISABLED, SubtitleMode.LINE) and lang and lang.is_cjk:
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"

    if mode == SubtitleMode.LINE:
        return "\n"
    elif mode == SubtitleMode.SENTENCE:
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"
    elif mode == SubtitleMode.SENTENCE_COMMA:
        return rf"(?<=[{PUNCTUATION_SENTENCE_COMMA}]){spacing}|\n+"
    else:
        return r"\n+"
