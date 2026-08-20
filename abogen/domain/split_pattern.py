from __future__ import annotations

"""Unified split pattern logic extracted from 3 copies."""

from abogen.domain.enums import Language, SubtitleMode

# Canonical punctuation sets covering all supported scripts:
# ASCII (. ! ?), Arabic ؟, CJK (。！？), Devanagari ।
PUNCTUATION_SENTENCE = r".!?؟。！？।"
# Commas: ASCII , CJK fullwidth ，CJK ideographic 、
PUNCTUATION_SENTENCE_COMMA = r".!?,？。！？،，、।"
PUNCTUATION_COMMAS = ",，、"


def get_split_pattern(language: Language, subtitle_mode: str) -> str:
    """Get the appropriate split pattern based on language and subtitle mode.

    Args:
        language: Language enum value, ISO code, or kokoro letter code.
        subtitle_mode: Subtitle mode ("Sentence", "Sentence + Comma", "Line", etc.)

    Returns:
        Split pattern string
    """
    try:
        mode = SubtitleMode.from_str(subtitle_mode) if not isinstance(subtitle_mode, SubtitleMode) else subtitle_mode
    except ValueError:
        mode = SubtitleMode.DISABLED

    # For English, always use newline splitting only
    if language in (Language.EN_US, Language.EN_GB):
        return "\n"

    # Determine spacing pattern based on language
    spacing = r"\s*" if language.is_cjk else r"\s+"

    # For CJK languages, when subtitle mode is Disabled or Line, prefer
    # punctuation-based splitting instead of plain newline splitting.
    if mode in (SubtitleMode.DISABLED, SubtitleMode.LINE) and language.is_cjk:
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"

    if mode == SubtitleMode.LINE:
        return "\n"
    elif mode == SubtitleMode.SENTENCE:
        return rf"(?<=[{PUNCTUATION_SENTENCE}]){spacing}|\n+"
    elif mode == SubtitleMode.SENTENCE_COMMA:
        return rf"(?<=[{PUNCTUATION_SENTENCE_COMMA}]){spacing}|\n+"
    else:
        return r"\n+"
