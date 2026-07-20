"""Shared settings core.

Defines the SETTINGS_REGISTRY — the single source of truth for all settings.
Every setting has a key, type, default, validation rules, and UI scope.
Both Web UI and Desktop GUI must reference this registry.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

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


# ── Schema ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Setting:
    """Contract for a single setting.

    Attributes:
        key: Config dict key (e.g. "output_format").
        type_: Python type (bool, int, float, str, list).
        default: Default value or callable returning one.
        min_value: Minimum for numeric types.
        max_value: Maximum for numeric types.
        valid_values: Allowed values for str types (None = any).
        gui_only: True if only used by PyQt Desktop GUI.
        web_only: True if only used by Web UI.
        normalizer: Optional callable(value, default) -> normalized_value.
        description: Human-readable explanation.
    """
    key: str
    type_: type
    default: Any
    min_value: float | None = None
    max_value: float | None = None
    valid_values: tuple[Any, ...] | None = None
    gui_only: bool = False
    web_only: bool = False
    normalizer: Callable | None = None
    description: str = ""

    def coerce(self, value: Any, fallback: Any | None = None) -> Any:
        """Coerce value to the declared type, returning fallback on failure."""
        fb = fallback if fallback is not None else self.default
        if self.type_ is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"true", "1", "yes", "on"}
            if value is None:
                return fb
            return bool(value)
        if self.type_ is int:
            try:
                v = int(value)
            except (TypeError, ValueError):
                return fb
            if self.min_value is not None:
                v = max(int(self.min_value), v)
            if self.max_value is not None:
                v = min(int(self.max_value), v)
            return v
        if self.type_ is float:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return fb
            if self.min_value is not None:
                v = max(self.min_value, v)
            if self.max_value is not None:
                v = min(self.max_value, v)
            return v
        if self.type_ is str:
            if isinstance(value, str):
                v = value.strip()
                if self.valid_values and v not in self.valid_values:
                    return fb
                return v
            return fb
        if self.type_ is list:
            if isinstance(value, (list, tuple, set)):
                return list(value)
            return fb
        return value


# ── Normalizers (used by Setting.normalizer) ─────────────────────────

def _norm_save_mode(value: Any, default: str) -> str:
    if isinstance(value, str):
        if value in SAVE_MODE_LABELS:
            return value
        if value in LEGACY_SAVE_MODE_MAP:
            return LEGACY_SAVE_MODE_MAP[value]
    return default


def _norm_voice_spec(value: Any, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        spec, profile_name = split_profile_spec(text)
        if profile_name:
            return f"speaker:{profile_name}"
        return spec
    return default


def _norm_speaker_spec(value: Any, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        spec, profile_name = split_profile_spec(text)
        if profile_name:
            return f"speaker:{profile_name}"
        return spec
    return ""


def _norm_language_list(value: Any, default: list) -> list:
    if isinstance(value, (list, tuple, set)):
        return [code for code in value if isinstance(code, str) and code in LANGUAGE_DESCRIPTIONS]
    if isinstance(value, str):
        parts = [item.strip().lower() for item in value.split(",") if item.strip()]
        return [code for code in parts if code in LANGUAGE_DESCRIPTIONS]
    return default


def _norm_stripped_str(value: Any, default: str) -> str:
    return str(value or "").strip()


def _norm_prompt(value: Any, default: str) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate else default


# ── Registry ─────────────────────────────────────────────────────────

def _default_output_format() -> str:
    return "wav"


def _default_save_mode() -> str:
    return "default_output" if has_output_override() else "save_next_to_input"


def _default_llm(key: str) -> str:
    return environment_llm_defaults().get(key, "")


SETTINGS_REGISTRY: list[Setting] = [
    # ── Core output ──────────────────────────────────────────────
    Setting("output_format", str, "wav",
            valid_values=tuple(SUPPORTED_SOUND_FORMATS),
            description="Audio output format"),
    Setting("subtitle_format", str, "srt",
            valid_values=tuple(item[0] for item in SUBTITLE_FORMATS),
            description="Subtitle file format"),
    Setting("save_mode", str, _default_save_mode,
            normalizer=_norm_save_mode,
            description="Where to save output files"),
    Setting("separate_chapters_format", str, "wav",
            valid_values=("wav", "flac", "mp3", "opus"),
            description="Format for separately saved chapters"),
    Setting("chunk_level", str, "paragraph",
            valid_values=("paragraph", "sentence"),
            description="Text chunking granularity"),

    # ── Voice ────────────────────────────────────────────────────
    Setting("default_speaker", str, "",
            normalizer=_norm_speaker_spec,
            description="Default speaker name"),
    Setting("default_voice", str, lambda: get_default_voice("kokoro"),
            normalizer=_norm_voice_spec,
            description="Default TTS voice"),
    Setting("speed", float, 1.0, min_value=0.5, max_value=3.0,
            gui_only=True,
            description="TTS speed multiplier"),
    Setting("supertonic_total_steps", int, 5, min_value=2, max_value=15,
            description="SuperTonic processing steps"),
    Setting("supertonic_speed", float, 1.0, min_value=0.7, max_value=2.0,
            description="SuperTonic speed"),

    # ── Chapter handling ─────────────────────────────────────────
    Setting("silence_between_chapters", float, 2.0, min_value=0.0,
            description="Silence gap between chapters (seconds)"),
    Setting("chapter_intro_delay", float, 0.5, min_value=0.0,
            description="Delay after chapter heading (seconds)"),
    Setting("read_title_intro", bool, False,
            description="Read chapter title as intro"),
    Setting("read_closing_outro", bool, True,
            description="Read closing/outro text"),
    Setting("normalize_chapter_opening_caps", bool, True,
            description="Normalize chapter opening caps"),
    Setting("auto_prefix_chapter_titles", bool, True,
            description="Auto-prefix chapter titles"),
    Setting("save_chapters_separately", bool, False,
            description="Save each chapter as separate file"),
    Setting("merge_chapters_at_end", bool, True,
            description="Merge chapters into single file"),
    Setting("save_as_project", bool, False,
            description="Save as editable project"),
    Setting("generate_epub3", bool, False,
            description="Generate EPUB3 output"),

    # ── GPU / performance ────────────────────────────────────────
    Setting("use_gpu", bool, True,
            description="Use GPU acceleration"),

    # ── Text processing ──────────────────────────────────────────
    Setting("replace_single_newlines", bool, False,
            description="Replace single newlines with spaces"),
    Setting("max_subtitle_words", int, 50, min_value=1, max_value=500,
            description="Max words per subtitle"),
    Setting("enable_entity_recognition", bool, True,
            description="Enable entity recognition"),

    # ── Speaker analysis ─────────────────────────────────────────
    Setting("speaker_analysis_threshold", int, 3, min_value=1, max_value=25,
            description="Speaker analysis threshold"),
    Setting("speaker_pronunciation_sentence", str, "This is {{name}} speaking.",
            description="Template for pronunciation samples"),
    Setting("speaker_random_languages", list, [],
            normalizer=_norm_language_list,
            description="Languages for random speaker assignment"),

    # ── LLM ──────────────────────────────────────────────────────
    Setting("llm_base_url", str, lambda: _default_llm("llm_base_url"),
            normalizer=_norm_stripped_str,
            description="LLM API base URL"),
    Setting("llm_api_key", str, lambda: _default_llm("llm_api_key"),
            normalizer=_norm_stripped_str,
            description="LLM API key"),
    Setting("llm_model", str, lambda: _default_llm("llm_model"),
            normalizer=_norm_stripped_str,
            description="LLM model name"),
    Setting("llm_timeout", float, lambda: _default_llm("llm_timeout") or 30.0,
            min_value=1.0,
            description="LLM request timeout"),
    Setting("llm_prompt", str, lambda: _default_llm("llm_prompt") or DEFAULT_LLM_PROMPT,
            normalizer=_norm_prompt,
            description="LLM normalization prompt"),
    Setting("llm_context_mode", str, lambda: _default_llm("llm_context_mode") or "sentence",
            valid_values=("sentence",),
            description="LLM context mode"),

    # ── Normalization (booleans) ─────────────────────────────────
    Setting("normalization_numbers", bool, True,
            description="Convert grouped numbers to words"),
    Setting("normalization_currency", bool, True,
            description="Convert currency symbols"),
    Setting("normalization_footnotes", bool, True,
            description="Remove footnote indicators"),
    Setting("normalization_titles", bool, True,
            description="Expand titles and suffixes"),
    Setting("normalization_terminal", bool, True,
            description="Ensure terminal punctuation"),
    Setting("normalization_phoneme_hints", bool, True,
            description="Add phoneme hints for possessives"),
    Setting("normalization_caps_quotes", bool, True,
            description="Convert ALL CAPS in quotes"),
    Setting("normalization_internet_slang", bool, False,
            description="Expand internet slang"),
    Setting("normalization_apostrophes_contractions", bool, True,
            description="Expand contractions"),
    Setting("normalization_apostrophes_plural_possessives", bool, True,
            description="Collapse plural possessives"),
    Setting("normalization_apostrophes_sibilant_possessives", bool, True,
            description="Mark sibilant possessives"),
    Setting("normalization_apostrophes_decades", bool, True,
            description="Expand decades"),
    Setting("normalization_apostrophes_leading_elisions", bool, True,
            description="Expand leading elisions"),
    Setting("normalization_contraction_aux_be", bool, True,
            description="Expand auxiliary 'be'"),
    Setting("normalization_contraction_aux_have", bool, True,
            description="Expand auxiliary 'have'"),
    Setting("normalization_contraction_modal_will", bool, True,
            description="Expand modal 'will'"),
    Setting("normalization_contraction_modal_would", bool, True,
            description="Expand modal 'would'"),
    Setting("normalization_contraction_negation_not", bool, True,
            description="Expand negation 'not'"),
    Setting("normalization_contraction_let_us", bool, True,
            description="Expand 'let's'"),

    # ── Normalization (strings) ──────────────────────────────────
    Setting("normalization_apostrophe_mode", str, "spacy",
            valid_values=("off", "spacy", "llm"),
            description="Apostrophe handling mode"),
    Setting("normalization_numbers_year_style", str, "american",
            valid_values=("american", "off"),
            description="Year style for number normalization"),

    # ── PyQt GUI-only ────────────────────────────────────────────
    Setting("theme", str, "system",
            gui_only=True,
            description="UI theme"),
    Setting("check_updates", bool, True,
            gui_only=True,
            description="Check for updates on startup"),
    Setting("subtitle_mode", str, "Sentence",
            gui_only=True,
            description="Subtitle display mode"),
    Setting("selected_format", str, "wav",
            gui_only=True,
            description="Last selected audio format"),
    Setting("selected_voice", str, "af_heart",
            gui_only=True,
            description="Last selected voice"),
    Setting("selected_profile_name", str, None,
            gui_only=True,
            description="Last selected profile name"),
    Setting("log_window_max_lines", int, 2000, min_value=100,
            gui_only=True,
            description="Max lines in log window"),
    Setting("use_silent_gaps", bool, True,
            gui_only=True,
            description="Use silent gaps between chunks"),
    Setting("subtitle_speed_method", str, "tts",
            gui_only=True,
            valid_values=("tts", "ffmpeg"),
            description="Speed adjustment method for subtitles"),
    Setting("use_spacy_segmentation", bool, True,
            gui_only=True,
            description="Use spaCy for sentence segmentation"),
    Setting("word_substitutions_enabled", bool, False,
            gui_only=True,
            description="Enable word substitutions"),
    Setting("word_substitutions_list", str, "",
            gui_only=True,
            description="Word substitutions list"),
    Setting("case_sensitive_substitutions", bool, False,
            gui_only=True,
            description="Case-sensitive substitutions"),
    Setting("replace_all_caps", bool, False,
            gui_only=True,
            description="Replace ALL CAPS text"),
    Setting("replace_numerals", bool, False,
            gui_only=True,
            description="Replace numerals with words"),
    Setting("fix_nonstandard_punctuation", bool, False,
            gui_only=True,
            description="Fix nonstandard punctuation"),
    Setting("queue_override_settings", bool, False,
            gui_only=True,
            description="Override settings per queue item"),
    Setting("disable_kokoro_internet", bool, False,
            description="Disable Kokoro internet access"),
]


# ── Registry helpers ─────────────────────────────────────────────────

_REGISTRY_BY_KEY: dict[str, Setting] = {s.key: s for s in SETTINGS_REGISTRY}

SETTING_KEYS: frozenset[str] = frozenset(_REGISTRY_BY_KEY.keys())
GUI_ONLY_KEYS: frozenset[str] = frozenset(s.key for s in SETTINGS_REGISTRY if s.gui_only)
WEB_ONLY_KEYS: frozenset[str] = frozenset(s.key for s in SETTINGS_REGISTRY if s.web_only)
SHARED_KEYS: frozenset[str] = SETTING_KEYS - GUI_ONLY_KEYS - WEB_ONLY_KEYS

BOOLEAN_SETTINGS: frozenset[str] = frozenset(s.key for s in SETTINGS_REGISTRY if s.type_ is bool)
FLOAT_SETTINGS: frozenset[str] = frozenset(s.key for s in SETTINGS_REGISTRY if s.type_ is float)
INT_SETTINGS: frozenset[str] = frozenset(s.key for s in SETTINGS_REGISTRY if s.type_ is int)

# Backward-compatible aliases (used by existing code)
_NORMALIZATION_BOOLEAN_KEYS: frozenset[str] = frozenset(
    s.key for s in SETTINGS_REGISTRY
    if s.type_ is bool and s.key.startswith("normalization_")
)
_NORMALIZATION_STRING_KEYS: frozenset[str] = frozenset(
    s.key for s in SETTINGS_REGISTRY
    if s.type_ is str and s.key.startswith("normalization_")
)


def get_setting(key: str) -> Setting | None:
    """Look up a setting by key."""
    return _REGISTRY_BY_KEY.get(key)


def has_output_override() -> bool:
    return bool(os.environ.get("ABOGEN_OUTPUT_DIR") or os.environ.get("ABOGEN_OUTPUT_ROOT"))


# ── Defaults ─────────────────────────────────────────────────────────

def settings_defaults() -> Dict[str, Any]:
    """Default values for all shared settings (excludes gui_only)."""
    result: Dict[str, Any] = {}
    for s in SETTINGS_REGISTRY:
        if s.gui_only:
            continue
        result[s.key] = s.default() if callable(s.default) else s.default
    return result


def all_settings_defaults() -> Dict[str, Any]:
    """Default values for ALL settings (including gui_only)."""
    result: Dict[str, Any] = {}
    for s in SETTINGS_REGISTRY:
        result[s.key] = s.default() if callable(s.default) else s.default
    return result


def load_settings() -> Dict[str, Any]:
    """Load and normalize settings from config file."""
    from abogen.utils import load_config
    defaults = settings_defaults()
    cfg = load_config() or {}
    settings: Dict[str, Any] = {}
    for key, default in defaults.items():
        raw_value = cfg.get(key, default)
        settings[key] = normalize_setting_value(key, raw_value, defaults)
    return settings


# ── Normalization (delegates to Setting.coerce) ──────────────────────

def normalize_setting_value(key: str, value: Any, defaults: Dict[str, Any]) -> Any:
    """Normalize a single setting value using the registry schema."""
    setting = _REGISTRY_BY_KEY.get(key)
    if setting is None:
        return value if value is not None else defaults.get(key)

    fallback = defaults.get(key, setting.default() if callable(setting.default) else setting.default)

    if setting.normalizer is not None:
        return setting.normalizer(value, fallback)

    return setting.coerce(value, fallback)


def validate_setting(key: str, value: Any) -> tuple[bool, str]:
    """Validate a setting value against its schema. Returns (ok, error_message)."""
    setting = _REGISTRY_BY_KEY.get(key)
    if setting is None:
        return False, f"Unknown setting: {key}"
    if setting.type_ is str and setting.valid_values is not None:
        v = str(value or "").strip()
        if v and v not in setting.valid_values:
            return False, f"Invalid value '{v}' for {key}. Allowed: {setting.valid_values}"
    if setting.type_ is int:
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return False, f"Invalid integer value for {key}: {value!r}"
        if setting.min_value is not None and iv < setting.min_value:
            return False, f"{key} must be >= {setting.min_value}, got {iv}"
        if setting.max_value is not None and iv > setting.max_value:
            return False, f"{key} must be <= {setting.max_value}, got {iv}"
    if setting.type_ is float:
        try:
            fv = float(value)
        except (TypeError, ValueError):
            return False, f"Invalid float value for {key}: {value!r}"
        if setting.min_value is not None and fv < setting.min_value:
            return False, f"{key} must be >= {setting.min_value}, got {fv}"
        if setting.max_value is not None and fv > setting.max_value:
            return False, f"{key} must be <= {setting.max_value}, got {fv}"
    return True, ""


# ── Constants (backward-compatible) ──────────────────────────────────

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

CHUNK_LEVEL_VALUES = frozenset(option["value"] for option in CHUNK_LEVEL_OPTIONS)

DEFAULT_ANALYSIS_THRESHOLD = 3


# ── Coercion helpers (backward-compatible, delegate to Setting.coerce) ──

def coerce_bool(value: Any, default: bool) -> bool:
    return Setting("_", bool, default).coerce(value, default)


def coerce_float(value: Any, default: float) -> float:
    return Setting("_", float, default).coerce(value, default)


def coerce_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    return Setting("_", int, default, min_value=minimum, max_value=maximum).coerce(value, default)


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


def normalize_save_mode(value: Any, default: str) -> str:
    return _norm_save_mode(value, default)


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


# ── Integration defaults ─────────────────────────────────────────────

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
