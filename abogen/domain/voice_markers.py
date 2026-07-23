"""Voice marker parsing and text splitting.

Handles <<VOICE:name>> markers in text, splitting text into voice-specific
segments. This is domain logic about text segmentation by voice, not subtitle
processing.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_VOICE_MARKER_PATTERN = re.compile(r"<<VOICE:[^>]*>>")
_VOICE_MARKER_SEARCH_PATTERN = re.compile(r"<<VOICE:(.*?)>>")


def validate_voice_name(voice_name: str) -> Tuple[bool, str | None]:
    """Validate voice name against available voices (case-insensitive).

    Handles both single voices and formulas like 'af_heart*0.5 + am_echo*0.5'.

    Returns:
        Tuple of (is_valid, invalid_voice_name):
            - is_valid: True if all voices in the name/formula are valid
            - invalid_voice_name: The first invalid voice found, or None if all valid
    """
    from abogen.tts_plugin.utils import get_voices

    voice_lookup_lower = {v.lower() for v in get_voices("kokoro")}
    voice_name = voice_name.strip()

    if "*" in voice_name:
        voices = voice_name.split("+")
        for term in voices:
            if "*" in term:
                base_voice = term.split("*")[0].strip()
                if base_voice.lower() not in voice_lookup_lower:
                    return False, base_voice
        return True, None
    else:
        if voice_name.lower() not in voice_lookup_lower:
            return False, voice_name
        return True, None


def split_text_by_voice_markers(
    text: str, default_voice: str
) -> Tuple[List[Tuple[str, str]], str, int, int]:
    """Split text by voice markers, returning list of (voice, text) tuples.

    Returns the last voice used so it can persist across chapters.
    Voice names are normalized to lowercase to match canonical voice names.

    Args:
        text: Text potentially containing <<VOICE:name>> markers
        default_voice: Voice to use if no markers found or before first marker

    Returns:
        Tuple of (segments_list, last_voice_used, valid_count, invalid_count):
            - segments_list: List of (voice_name, segment_text) tuples
            - last_voice_used: The voice that should continue into next chapter
            - valid_count: Number of valid voice markers processed
            - invalid_count: Number of invalid voice markers skipped
    """
    from abogen.tts_plugin.utils import get_voices

    voice_splits = list(_VOICE_MARKER_SEARCH_PATTERN.finditer(text))

    if not voice_splits:
        return [(default_voice, text)], default_voice, 0, 0

    segments: List[Tuple[str, str]] = []
    current_voice = default_voice
    valid_markers = 0
    invalid_markers = 0

    first_start = voice_splits[0].start()
    if first_start > 0:
        intro_text = text[:first_start].strip()
        if intro_text:
            segments.append((current_voice, intro_text))

    for idx, match in enumerate(voice_splits):
        voice_name = match.group(1).strip()
        start = match.end()
        end = voice_splits[idx + 1].start() if idx + 1 < len(voice_splits) else len(text)
        segment_text = text[start:end].strip()

        is_valid, invalid_voice = validate_voice_name(voice_name)
        if is_valid:
            if "*" in voice_name:
                normalized_parts = []
                for part in voice_name.split("+"):
                    part = part.strip()
                    if "*" in part:
                        voice_part, weight = part.split("*", 1)
                        voice_part_lower = voice_part.strip().lower()
                        canonical_voice = next(
                            (v for v in get_voices("kokoro") if v.lower() == voice_part_lower),
                            voice_part.strip()
                        )
                        normalized_parts.append(f"{canonical_voice}*{weight.strip()}")
                current_voice = " + ".join(normalized_parts)
            else:
                voice_name_lower = voice_name.lower()
                current_voice = next(
                    (v for v in get_voices("kokoro") if v.lower() == voice_name_lower),
                    voice_name
                )
            valid_markers += 1
        else:
            invalid_markers += 1

        if segment_text:
            segments.append((current_voice, segment_text))

    return segments, current_voice, valid_markers, invalid_markers
