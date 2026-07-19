"""Shared settings core.

Pure settings logic (defaults, coercion, normalization) used by both
Web UI and Desktop GUI. No Flask dependencies.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Mapping

from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    SUBTITLE_FORMATS,
    SUPPORTED_SOUND_FORMATS,
)
from abogen.tts_plugin.utils import get_default_voice
from abogen.normalization_settings import (
    DEFAULT_LLM_PROMPT,
    environment_llm_defaults,
)

# ── Constants ────────────────────────────────────────────────────────

SAVE_MODE_LABELS = {
    "save_next_to_input": "Save next to input file",
    "save_to_desktop": "Save to Desktop",
    "choose_output_folder": "Choose output folder",
    "default_output": "Use default save location",
}

LEGACY_SAVE_MODE_MAP = {label: key for key, label in SAVE_MODE_LABELS.items()}

CHUNK_LEVEL_OPTIONS = [
    {"value": "paragraph", "label": "Paragraphs"},
    {"value": "sentence", "label": "Sentences"},
]

CHUNK_LEVEL_VALUES = {option["value"] for option in CHUNK_LEVEL_OPTIONS}

DEFAULT_ANALYSIS_THRESHOLD = 3

BOOLEAN_SETTINGS = {
    "replace_single_newlines",
    "use_gpu",
    "save_chapters_separately",
    "merge_chapters_at_end",
    "save_as_project",
    "read_title_intro",
    "read_closing_outro",
    "normalize_chapter_opening_caps",
    "generate_epub3",
    "auto_prefix_chapter_titles",
    "enable_entity_recognition",
    "normalization_numbers",
    "normalization_titles",
    "normalization_terminal",
    "normalization_phoneme_hints",
    "normalization_caps_quotes",
    "normalization_currency",
    "normalization_footnotes",
    "normalization_internet_slang",
    "normalization_apostrophes_contractions",
    "normalization_apostrophes_plural_possessives",
    "normalization_apostrophes_sibilant_possessives",
    "normalization_apostrophes_decades",
    "normalization_apostrophes_leading_elisions",
    "normalization_contraction_aux_be",
    "normalization_contraction_aux_have",
    "normalization_contraction_modal_will",
    "normalization_contraction_modal_would",
    "normalization_contraction_negation_not",
    "normalization_contraction_let_us",
}

FLOAT_SETTINGS = {"silence_between_chapters", "chapter_intro_delay", "llm_timeout"}

INT_SETTINGS = {"max_subtitle_words", "speaker_analysis_threshold"}

_NORMALIZATION_BOOLEAN_KEYS = {
    "normalization_numbers",
    "normalization_titles",
    "normalization_terminal",
    "normalization_phoneme_hints",
    "normalization_caps_quotes",
    "normalization_currency",
    "normalization_footnotes",
    "normalization_internet_slang",
    "normalization_apostrophes_contractions",
    "normalization_apostrophes_plural_possessives",
    "normalization_apostrophes_sibilant_possessives",
    "normalization_apostrophes_decades",
    "normalization_apostrophes_leading_elisions",
    "normalization_contraction_aux_be",
    "normalization_contraction_aux_have",
    "normalization_contraction_modal_will",
    "normalization_contraction_modal_would",
    "normalization_contraction_negation_not",
    "normalization_contraction_let_us",
}

_NORMALIZATION_STRING_KEYS = {
    "normalization_apostrophe_mode",
    "normalization_numbers_year_style",
}


# ── Coercion helpers ─────────────────────────────────────────────────

def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def coerce_float(value: Any, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def coerce_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


# ── Profile/speaker spec helpers ─────────────────────────────────────

def split_profile_spec(value: Any) -> tuple[str, str | None]:
    """Split 'speaker:Name' or 'profile:Name' into (raw, name)."""
    text = str(value or "").strip()
    if not text:
        return "", None
    lowered = text.lower()
    if lowered.startswith("profile:") or lowered.startswith("speaker:"):
        _, _, remainder = text.partition(":")
        name = remainder.strip()
        return "", name or None
    return text, None


# ── Normalization ────────────────────────────────────────────────────

def normalize_save_mode(value: Any, default: str) -> str:
    if isinstance(value, str):
        if value in SAVE_MODE_LABELS:
            return value
        if value in LEGACY_SAVE_MODE_MAP:
            return LEGACY_SAVE_MODE_MAP[value]
    return default


def normalize_setting_value(key: str, value: Any, defaults: Dict[str, Any]) -> Any:
    """Normalize a single setting value to its expected type."""
    if key in BOOLEAN_SETTINGS:
        return coerce_bool(value, defaults[key])
    if key in FLOAT_SETTINGS:
        return coerce_float(value, defaults[key])
    if key in INT_SETTINGS:
        return coerce_int(value, defaults[key])
    if key == "save_mode":
        return normalize_save_mode(value, defaults[key])
    if key == "output_format":
        return value if value in SUPPORTED_SOUND_FORMATS else defaults[key]
    if key == "subtitle_format":
        valid = {item[0] for item in SUBTITLE_FORMATS}
        return value if value in valid else defaults[key]
    if key == "separate_chapters_format":
        if isinstance(value, str):
            normalized = value.lower()
            if normalized in {"wav", "flac", "mp3", "opus"}:
                return normalized
        return defaults[key]
    if key == "default_voice":
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return defaults[key]
            spec, profile_name = split_profile_spec(text)
            if profile_name:
                return f"speaker:{profile_name}"
            return spec
        return defaults[key]
    if key == "default_speaker":
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            spec, profile_name = split_profile_spec(text)
            if profile_name:
                return f"speaker:{profile_name}"
            return spec
        return ""
    if key == "chunk_level":
        if isinstance(value, str) and value in CHUNK_LEVEL_VALUES:
            return value
        return defaults[key]
    if key == "normalization_apostrophe_mode":
        if isinstance(value, str):
            normalized_mode = value.strip().lower()
            if normalized_mode in {"off", "spacy", "llm"}:
                return normalized_mode
        return defaults[key]
    if key == "normalization_numbers_year_style":
        if isinstance(value, str):
            normalized_style = value.strip().lower()
            if normalized_style in {"american", "off"}:
                return normalized_style
        return defaults[key]
    if key == "llm_context_mode":
        if isinstance(value, str):
            normalized_scope = value.strip().lower()
            if normalized_scope == "sentence":
                return normalized_scope
        return defaults[key]
    if key == "llm_prompt":
        candidate = str(value or "").strip()
        return candidate if candidate else defaults[key]
    if key in {"llm_base_url", "llm_api_key", "llm_model"}:
        return str(value or "").strip()
    if key == "speaker_random_languages":
        if isinstance(value, (list, tuple, set)):
            return [code for code in value if isinstance(code, str) and code in LANGUAGE_DESCRIPTIONS]
        if isinstance(value, str):
            parts = [item.strip().lower() for item in value.split(",") if item.strip()]
            return [code for code in parts if code in LANGUAGE_DESCRIPTIONS]
        return defaults.get(key, [])
    if key == "supertonic_total_steps":
        try:
            steps = int(value)
        except (TypeError, ValueError):
            return defaults.get(key, 5)
        return max(2, min(15, steps))
    if key == "supertonic_speed":
        try:
            speed = float(value)
        except (TypeError, ValueError):
            return defaults.get(key, 1.0)
        return max(0.7, min(2.0, speed))
    return value if value is not None else defaults.get(key)


# ── Defaults ─────────────────────────────────────────────────────────

def has_output_override() -> bool:
    return bool(os.environ.get("ABOGEN_OUTPUT_DIR") or os.environ.get("ABOGEN_OUTPUT_ROOT"))


def settings_defaults() -> Dict[str, Any]:
    """Default values for all settings keys."""
    llm_env_defaults = environment_llm_defaults()
    return {
        "output_format": "wav",
        "subtitle_format": "srt",
        "save_mode": "default_output" if has_output_override() else "save_next_to_input",
        "default_speaker": "",
        "default_voice": get_default_voice("kokoro"),
        "supertonic_total_steps": 5,
        "supertonic_speed": 1.0,
        "replace_single_newlines": False,
        "use_gpu": True,
        "save_chapters_separately": False,
        "merge_chapters_at_end": True,
        "save_as_project": False,
        "separate_chapters_format": "wav",
        "silence_between_chapters": 2.0,
        "chapter_intro_delay": 0.5,
        "read_title_intro": False,
        "read_closing_outro": True,
        "normalize_chapter_opening_caps": True,
        "max_subtitle_words": 50,
        "chunk_level": "paragraph",
        "enable_entity_recognition": True,
        "generate_epub3": False,
        "auto_prefix_chapter_titles": True,
        "speaker_analysis_threshold": DEFAULT_ANALYSIS_THRESHOLD,
        "speaker_pronunciation_sentence": "This is {{name}} speaking.",
        "speaker_random_languages": [],
        "llm_base_url": llm_env_defaults.get("llm_base_url", ""),
        "llm_api_key": llm_env_defaults.get("llm_api_key", ""),
        "llm_model": llm_env_defaults.get("llm_model", ""),
        "llm_timeout": llm_env_defaults.get("llm_timeout", 30.0),
        "llm_prompt": llm_env_defaults.get("llm_prompt", DEFAULT_LLM_PROMPT),
        "llm_context_mode": llm_env_defaults.get("llm_context_mode", "sentence"),
        "normalization_numbers": True,
        "normalization_currency": True,
        "normalization_footnotes": True,
        "normalization_titles": True,
        "normalization_terminal": True,
        "normalization_phoneme_hints": True,
        "normalization_caps_quotes": True,
        "normalization_internet_slang": False,
        "normalization_apostrophes_contractions": True,
        "normalization_apostrophes_plural_possessives": True,
        "normalization_apostrophes_sibilant_possessives": True,
        "normalization_apostrophes_decades": True,
        "normalization_apostrophes_leading_elisions": True,
        "normalization_apostrophe_mode": "spacy",
        "normalization_numbers_year_style": "american",
        "normalization_contraction_aux_be": True,
        "normalization_contraction_aux_have": True,
        "normalization_contraction_modal_will": True,
        "normalization_contraction_modal_would": True,
        "normalization_contraction_negation_not": True,
        "normalization_contraction_let_us": True,
    }


def integration_defaults() -> Dict[str, Dict[str, Any]]:
    """Default values for integration settings."""
    return {
        "calibre_opds": {
            "enabled": False,
            "base_url": "",
            "username": "",
            "password": "",
            "verify_ssl": True,
        },
        "audiobookshelf": {
            "enabled": False,
            "base_url": "",
            "api_token": "",
            "library_id": "",
            "collection_id": "",
            "folder_id": "",
            "verify_ssl": True,
            "send_cover": True,
            "send_chapters": True,
            "send_subtitles": False,
            "auto_send": False,
            "timeout": 30.0,
        },
    }


# ── LLM helpers ──────────────────────────────────────────────────────

_PROMPT_TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def llm_ready(settings: Mapping[str, Any]) -> bool:
    base_url = str(settings.get("llm_base_url") or "").strip()
    return bool(base_url)


def render_prompt_template(template: str, context: Mapping[str, str]) -> str:
    if not template:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return context.get(key, "")

    return _PROMPT_TOKEN_RE.sub(_replace, template)
