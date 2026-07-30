"""Text utility functions for the domain layer."""

from __future__ import annotations

import re

# Pre-compiled patterns for calculate_text_length
_METADATA_TAG_PATTERN = re.compile(r"<<METADATA_[^:]+:[^>]*>>")
_CHAPTER_MARKER_PATTERN = re.compile(r"<<CHAPTER_MARKER:[^>]*>>")
_VOICE_MARKER_PATTERN = re.compile(r"<<VOICE:[^>]*>>")


def calculate_text_length(text: str) -> int:
    """Calculate character count, ignoring internal markers and newlines.

    Strips chapter markers, voice markers, and metadata tags before counting.
    """
    text = _CHAPTER_MARKER_PATTERN.sub("", text)
    text = _VOICE_MARKER_PATTERN.sub("", text)
    text = _METADATA_TAG_PATTERN.sub("", text)
    text = text.replace("\n", "").strip()
    return len(text)
