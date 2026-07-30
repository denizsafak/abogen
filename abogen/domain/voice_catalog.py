"""Voice catalog — shared voice metadata for all UIs.

Builds a unified catalog of available voices with metadata (language,
gender, display name). Used by both WebUI and PyQt for voice selection UIs.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from abogen.constants import LANGUAGE_DESCRIPTIONS
from abogen.tts_plugin.utils import get_voices


def build_voice_catalog() -> List[Dict[str, str]]:
    """Build voice catalog with metadata for all available voices.

    Returns a list of dicts, each containing:
        - id: voice ID (e.g. "af_heart")
        - language: language code (e.g. "a", "e")
        - language_label: human-readable language name
        - gender: "Female", "Male", or "Unknown"
        - gender_code: "f", "m", or ""
        - display_name: human-readable voice name
    """
    from plugins.kokoro.engine import language_for_voice_id

    catalog: List[Dict[str, str]] = []
    gender_map = {"f": "Female", "m": "Male"}
    for voice_id in get_voices("kokoro"):
        prefix, _, rest = voice_id.partition("_")
        gender_code = prefix[1] if len(prefix) > 1 else ""
        lang = language_for_voice_id(voice_id)
        catalog.append(
            {
                "id": voice_id,
                "language": lang.value,
                "language_label": LANGUAGE_DESCRIPTIONS.get(lang, lang.value.upper()),
                "gender": gender_map.get(gender_code, "Unknown"),
                "gender_code": gender_code,
                "display_name": rest.replace("_", " ").title() if rest else voice_id,
            }
        )
    return catalog


def filter_voice_catalog(
    catalog: Iterable[Mapping[str, Any]],
    *,
    gender: str,
    allowed_languages: Optional[Iterable[str]] = None,
) -> List[str]:
    """Filter voice catalog by gender and language.

    Returns voice IDs that match the criteria. Falls back to broader
    matches if no exact matches are found.

    Args:
        catalog: Voice catalog entries (from build_voice_catalog).
        gender: Gender filter ("male", "female", or "unknown").
        allowed_languages: Optional list of allowed language codes.

    Returns:
        List of matching voice IDs.
    """
    allowed_set = {code.lower() for code in (allowed_languages or []) if isinstance(code, str) and code}
    gender_normalized = (gender or "unknown").lower()
    gender_code = ""
    if gender_normalized == "male":
        gender_code = "m"
    elif gender_normalized == "female":
        gender_code = "f"

    matches: List[str] = []
    seen: set[str] = set()

    def _consider(entry: Mapping[str, Any]) -> None:
        voice_id = entry.get("id")
        if not isinstance(voice_id, str) or not voice_id:
            return
        if voice_id in seen:
            return
        seen.add(voice_id)
        matches.append(voice_id)

    primary: List[Mapping[str, Any]] = []
    fallback: List[Mapping[str, Any]] = []
    for entry in catalog:
        if not isinstance(entry, Mapping):
            continue
        voice_lang = str(entry.get("language", "")).lower()
        voice_gender_code = str(entry.get("gender_code", "")).lower()
        if allowed_set and voice_lang not in allowed_set:
            continue
        if gender_code and voice_gender_code != gender_code:
            fallback.append(entry)
            continue
        primary.append(entry)

    for entry in primary:
        _consider(entry)

    if not matches:
        for entry in fallback:
            _consider(entry)

    if not matches:
        for entry in catalog:
            if isinstance(entry, Mapping):
                _consider(entry)

    return matches
