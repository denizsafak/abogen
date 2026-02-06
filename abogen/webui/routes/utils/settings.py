import os
import re
from typing import Any, Dict, Mapping, Optional

from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    SUBTITLE_FORMATS,
    SUPPORTED_SOUND_FORMATS,
    VOICES_INTERNAL,
)
from abogen.normalization_settings import (
    DEFAULT_LLM_PROMPT,
    environment_llm_defaults,
)
from abogen.utils import load_config, save_config
from abogen.integrations.calibre_opds import CalibreOPDSClient
from abogen.integrations.audiobookshelf import AudiobookshelfConfig
from abogen.webui.routes.utils.common import split_profile_spec

SAVE_MODE_LABELS = {
    "save_next_to_input": "Save next to input file",
    "save_to_desktop": "Save to Desktop",
    "choose_output_folder": "Choose output folder",
    "default_output": "Use default save location",
}

LEGACY_SAVE_MODE_MAP = {label: key for key, label in SAVE_MODE_LABELS.items()}

_CHUNK_LEVEL_OPTIONS = [
    {"value": "paragraph", "label": "Paragraphs"},
    {"value": "sentence", "label": "Sentences"},
]

_CHUNK_LEVEL_VALUES = {option["value"] for option in _CHUNK_LEVEL_OPTIONS}

_DEFAULT_ANALYSIS_THRESHOLD = 3

_APOSTROPHE_MODE_OPTIONS = [
    {"value": "off", "label": "Off"},
    {"value": "spacy", "label": "spaCy (built-in)"},
    {"value": "llm", "label": "LLM assisted"},
]

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
    "normalization_numbers_year_style",
    "normalization_apostrophe_mode",
}

BOOLEAN_SETTINGS = {
    "replace_single_newlines",
    "use_gpu",
    "save_chapters_separately",
    "merge_chapters_at_end",
    "save_as_project",
    "generate_epub3",
    "enable_entity_recognition",
    "read_title_intro",
    "read_closing_outro",
    "auto_prefix_chapter_titles",
    "normalize_chapter_opening_caps",
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

_NORMALIZATION_GROUPS = [
    {
        "label": "General Rules",
        "options": [
            {"key": "normalization_numbers", "label": "Convert grouped numbers to words"},
            {"key": "normalization_currency", "label": "Convert currency symbols ($10 → ten dollars)"},
            {"key": "normalization_titles", "label": "Expand titles and suffixes (Dr., St., Jr., …)"},
            {"key": "normalization_internet_slang", "label": "Expand internet slang (pls → please)"},
            {"key": "normalization_footnotes", "label": "Remove footnote indicators ([1], [2])"},
            {"key": "normalization_terminal", "label": "Ensure sentences end with terminal punctuation"},
            {"key": "normalization_caps_quotes", "label": "Convert ALL CAPS dialogue inside quotes"},
        ]
    },
    {
        "label": "Apostrophes & Contractions",
        "options": [
            {"key": "normalization_apostrophes_contractions", "label": "Expand contractions (it's → it is)"},
            {"key": "normalization_apostrophes_plural_possessives", "label": "Collapse plural possessives (dogs' → dogs)"},
            {"key": "normalization_apostrophes_sibilant_possessives", "label": "Mark sibilant possessives (boss's → boss + IZ marker)"},
            {"key": "normalization_apostrophes_decades", "label": "Expand decades ('90s → 1990s)"},
            {"key": "normalization_apostrophes_leading_elisions", "label": "Expand leading elisions ('tis → it is)"},
            {"key": "normalization_phoneme_hints", "label": "Add phoneme hints for possessives"},
            {"key": "normalization_contraction_aux_be", "label": "Expand auxiliary 'be' (I'm → I am)"},
            {"key": "normalization_contraction_aux_have", "label": "Expand auxiliary 'have' (I've → I have)"},
            {"key": "normalization_contraction_modal_will", "label": "Expand modal 'will' (I'll → I will)"},
            {"key": "normalization_contraction_modal_would", "label": "Expand modal 'would' (I'd → I would)"},
            {"key": "normalization_contraction_negation_not", "label": "Expand negation 'not' (don't → do not)"},
            {"key": "normalization_contraction_let_us", "label": "Expand 'let's' → let us"},
        ]
    }
]


def integration_defaults() -> Dict[str, Dict[str, Any]]:
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


def has_output_override() -> bool:
    return bool(os.environ.get("ABOGEN_OUTPUT_DIR") or os.environ.get("ABOGEN_OUTPUT_ROOT"))


def settings_defaults() -> Dict[str, Any]:
    llm_env_defaults = environment_llm_defaults()
    return {
        "output_format": "wav",
        "subtitle_format": "srt",
        "save_mode": "default_output" if has_output_override() else "save_next_to_input",
        "default_speaker": "",
        "default_voice": VOICES_INTERNAL[0] if VOICES_INTERNAL else "",
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
        "speaker_analysis_threshold": _DEFAULT_ANALYSIS_THRESHOLD,
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


def llm_ready(settings: Mapping[str, Any]) -> bool:
    base_url = str(settings.get("llm_base_url") or "").strip()
    return bool(base_url)


_PROMPT_TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def render_prompt_template(template: str, context: Mapping[str, str]) -> str:
    if not template:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return context.get(key, "")

    return _PROMPT_TOKEN_RE.sub(_replace, template)


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


def normalize_save_mode(value: Any, default: str) -> str:
    if isinstance(value, str):
        if value in SAVE_MODE_LABELS:
            return value
        if value in LEGACY_SAVE_MODE_MAP:
            return LEGACY_SAVE_MODE_MAP[value]
    return default


def normalize_setting_value(key: str, value: Any, defaults: Dict[str, Any]) -> Any:
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
        if isinstance(value, str) and value in _CHUNK_LEVEL_VALUES:
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


def load_settings() -> Dict[str, Any]:
    defaults = settings_defaults()
    cfg = load_config() or {}
    settings: Dict[str, Any] = {}
    for key, default in defaults.items():
        raw_value = cfg.get(key, default)
        settings[key] = normalize_setting_value(key, raw_value, defaults)
    return settings


def load_integration_settings() -> Dict[str, Dict[str, Any]]:
    defaults = integration_defaults()
    cfg = load_config() or {}
    # Integrations are stored under the "integrations" key in the config
    stored_integrations = cfg.get("integrations", {})
    if not isinstance(stored_integrations, Mapping):
        stored_integrations = {}

    integrations: Dict[str, Dict[str, Any]] = {}
    for key, default in defaults.items():
        stored = stored_integrations.get(key)
        merged: Dict[str, Any] = dict(default)
        if isinstance(stored, Mapping):
            for field, default_value in default.items():
                value = stored.get(field, default_value)
                if isinstance(default_value, bool):
                    merged[field] = coerce_bool(value, default_value)
                elif isinstance(default_value, float):
                    try:
                        merged[field] = float(value)
                    except (TypeError, ValueError):
                        merged[field] = default_value
                elif isinstance(default_value, int):
                    try:
                        merged[field] = int(value)
                    except (TypeError, ValueError):
                        merged[field] = default_value
                else:
                    merged[field] = str(value or "")
        if key == "calibre_opds":
            merged["has_password"] = bool(isinstance(stored, Mapping) and stored.get("password"))
            # Do not clear the password here, let the template decide whether to show it or not
            # merged["password"] = "" 
        elif key == "audiobookshelf":
            merged["has_api_token"] = bool(isinstance(stored, Mapping) and stored.get("api_token"))
            # Do not clear the token here
            # merged["api_token"] = ""
        integrations[key] = merged

    # Environment variable fallbacks for Calibre OPDS
    calibre = integrations["calibre_opds"]
    if not calibre.get("base_url"):
        calibre["base_url"] = os.environ.get("CALIBRE_SERVER_HOST", "")
    if not calibre.get("username"):
        calibre["username"] = os.environ.get("OPDS_USERNAME", "")
    if not calibre.get("password"):
        calibre["password"] = os.environ.get("OPDS_PASSWORD", "")
    
    # If we have a password (from storage or env), mark it as present for the UI
    if calibre.get("password"):
        calibre["has_password"] = True

    # Auto-enable if configured via env but not explicitly disabled in config
    stored_calibre = stored_integrations.get("calibre_opds")
    if stored_calibre is None and calibre.get("base_url"):
        calibre["enabled"] = True

    return integrations


def stored_integration_config(name: str) -> Dict[str, Any]:
    cfg = load_config() or {}
    # Check under "integrations" first (new structure)
    integrations = cfg.get("integrations")
    if isinstance(integrations, Mapping):
        entry = integrations.get(name)
        if isinstance(entry, Mapping):
            return dict(entry)
    
    # Fallback to top-level (legacy structure)
    entry = cfg.get(name)
    if isinstance(entry, Mapping):
        return dict(entry)
    return {}


def calibre_settings_from_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    defaults = integration_defaults()["calibre_opds"]
    stored = stored_integration_config("calibre_opds")

    base_url = str(
        payload.get("base_url")
        or payload.get("calibre_opds_base_url")
        or stored.get("base_url")
        or ""
    ).strip()
    username = str(
        payload.get("username")
        or payload.get("calibre_opds_username")
        or stored.get("username")
        or ""
    ).strip()
    password_input = str(
        payload.get("password")
        or payload.get("calibre_opds_password")
        or ""
    ).strip()
    use_saved_password = coerce_bool(
        payload.get("use_saved_password")
        or payload.get("calibre_opds_use_saved_password"),
        False,
    )
    clear_saved_password = coerce_bool(
        payload.get("clear_saved_password")
        or payload.get("calibre_opds_password_clear"),
        False,
    )
    password = ""
    if password_input:
        password = password_input
    elif use_saved_password and not clear_saved_password:
        password = str(stored.get("password") or "")

    verify_ssl = coerce_bool(
        payload.get("verify_ssl")
        or payload.get("calibre_opds_verify_ssl"),
        defaults["verify_ssl"],
    )
    enabled = coerce_bool(
        payload.get("enabled")
        or payload.get("calibre_opds_enabled"),
        coerce_bool(stored.get("enabled"), False),
    )

    return {
        "enabled": enabled,
        "base_url": base_url,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
    }


def audiobookshelf_settings_from_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    defaults = integration_defaults()["audiobookshelf"]
    stored = stored_integration_config("audiobookshelf")

    base_url = str(
        payload.get("base_url")
        or payload.get("audiobookshelf_base_url")
        or stored.get("base_url")
        or ""
    ).strip()
    library_id = str(
        payload.get("library_id")
        or payload.get("audiobookshelf_library_id")
        or stored.get("library_id")
        or ""
    ).strip()
    collection_id = str(
        payload.get("collection_id")
        or payload.get("audiobookshelf_collection_id")
        or stored.get("collection_id")
        or ""
    ).strip()
    folder_id = str(
        payload.get("folder_id")
        or payload.get("audiobookshelf_folder_id")
        or stored.get("folder_id")
        or ""
    ).strip()
    token_input = str(
        payload.get("api_token")
        or payload.get("audiobookshelf_api_token")
        or ""
    ).strip()
    use_saved_token = coerce_bool(
        payload.get("use_saved_token")
        or payload.get("audiobookshelf_use_saved_token"),
        False,
    )
    clear_saved_token = coerce_bool(
        payload.get("clear_saved_token")
        or payload.get("audiobookshelf_api_token_clear"),
        False,
    )
    if token_input:
        api_token = token_input
    elif use_saved_token and not clear_saved_token:
        api_token = str(stored.get("api_token") or "")
    else:
        api_token = ""

    verify_ssl = coerce_bool(
        payload.get("verify_ssl")
        or payload.get("audiobookshelf_verify_ssl"),
        defaults["verify_ssl"],
    )
    send_cover = coerce_bool(
        payload.get("send_cover")
        or payload.get("audiobookshelf_send_cover"),
        defaults["send_cover"],
    )
    send_chapters = coerce_bool(
        payload.get("send_chapters")
        or payload.get("audiobookshelf_send_chapters"),
        defaults["send_chapters"],
    )
    send_subtitles = coerce_bool(
        payload.get("send_subtitles")
        or payload.get("audiobookshelf_send_subtitles"),
        defaults["send_subtitles"],
    )
    auto_send = coerce_bool(
        payload.get("auto_send")
        or payload.get("audiobookshelf_auto_send"),
        defaults["auto_send"],
    )
    timeout_raw = (
        payload.get("timeout")
        or payload.get("audiobookshelf_timeout")
        or stored.get("timeout")
        or defaults["timeout"]
    )
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = defaults["timeout"]

    enabled = coerce_bool(
        payload.get("enabled")
        or payload.get("audiobookshelf_enabled"),
        coerce_bool(stored.get("enabled"), False),
    )

    return {
        "enabled": enabled,
        "base_url": base_url,
        "library_id": library_id,
        "collection_id": collection_id,
        "folder_id": folder_id,
        "api_token": api_token,
        "verify_ssl": verify_ssl,
        "send_cover": send_cover,
        "send_chapters": send_chapters,
        "send_subtitles": send_subtitles,
        "auto_send": auto_send,
        "timeout": timeout,
    }


def build_audiobookshelf_config(settings: Mapping[str, Any]) -> Optional[AudiobookshelfConfig]:
    base_url = str(settings.get("base_url") or "").strip()
    api_token = str(settings.get("api_token") or "").strip()
    library_id = str(settings.get("library_id") or "").strip()
    if not (base_url and api_token and library_id):
        return None
    try:
        timeout = float(settings.get("timeout", 3600.0))
    except (TypeError, ValueError):
        timeout = 3600.0
    return AudiobookshelfConfig(
        base_url=base_url,
        api_token=api_token,
        library_id=library_id,
        collection_id=(str(settings.get("collection_id") or "").strip() or None),
        folder_id=(str(settings.get("folder_id") or "").strip() or None),
        verify_ssl=coerce_bool(settings.get("verify_ssl"), True),
        send_cover=coerce_bool(settings.get("send_cover"), True),
        send_chapters=coerce_bool(settings.get("send_chapters"), True),
        send_subtitles=coerce_bool(settings.get("send_subtitles"), False),
        timeout=timeout,
    )


def calibre_integration_enabled(
    integrations: Optional[Mapping[str, Any]] = None,
) -> bool:
    if integrations is None:
        integrations = load_integration_settings()
    payload = integrations.get("calibre_opds") if isinstance(integrations, Mapping) else None
    if not isinstance(payload, Mapping):
        return False
    base_url = str(payload.get("base_url") or "").strip()
    enabled_flag = coerce_bool(payload.get("enabled"), False)
    return bool(enabled_flag and base_url)


def audiobookshelf_manual_available() -> bool:
    settings = stored_integration_config("audiobookshelf")
    if not settings:
        return False
    return coerce_bool(settings.get("enabled"), False)


def build_calibre_client(settings: Mapping[str, Any]) -> CalibreOPDSClient:
    base_url = str(settings.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Calibre OPDS base URL is required")
    username = str(settings.get("username") or "").strip() or None
    password = str(settings.get("password") or "").strip() or None
    verify_ssl = coerce_bool(settings.get("verify_ssl"), True)
    timeout_raw = settings.get("timeout", 15.0)
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = 15.0
    return CalibreOPDSClient(
        base_url,
        username=username,
        password=password,
        timeout=timeout,
        verify=verify_ssl,
    )


def apply_integration_form(cfg: Dict[str, Any], form: Mapping[str, Any]) -> None:
    defaults = integration_defaults()

    current_calibre = dict(cfg.get("calibre_opds") or {})
    calibre_enabled = coerce_bool(form.get("calibre_opds_enabled"), False)
    calibre_base = str(form.get("calibre_opds_base_url") or current_calibre.get("base_url") or "").strip()
    calibre_username = str(form.get("calibre_opds_username") or current_calibre.get("username") or "").strip()
    calibre_password_input = str(form.get("calibre_opds_password") or "")
    calibre_clear = coerce_bool(form.get("calibre_opds_password_clear"), False)
    if calibre_password_input:
        calibre_password = calibre_password_input
    elif calibre_clear:
        calibre_password = ""
    else:
        calibre_password = str(current_calibre.get("password") or "")
    calibre_verify = coerce_bool(form.get("calibre_opds_verify_ssl"), defaults["calibre_opds"]["verify_ssl"])
    cfg["calibre_opds"] = {
        "enabled": calibre_enabled,
        "base_url": calibre_base,
        "username": calibre_username,
        "password": calibre_password,
        "verify_ssl": calibre_verify,
    }

    current_abs = dict(cfg.get("audiobookshelf") or {})
    abs_enabled = coerce_bool(form.get("audiobookshelf_enabled"), False)
    abs_base = str(form.get("audiobookshelf_base_url") or current_abs.get("base_url") or "").strip()
    abs_library = str(form.get("audiobookshelf_library_id") or current_abs.get("library_id") or "").strip()
    abs_collection = str(form.get("audiobookshelf_collection_id") or current_abs.get("collection_id") or "").strip()
    abs_folder = str(form.get("audiobookshelf_folder_id") or current_abs.get("folder_id") or "").strip()
    abs_token_input = str(form.get("audiobookshelf_api_token") or "")
    abs_token_clear = coerce_bool(form.get("audiobookshelf_api_token_clear"), False)
    if abs_token_input:
        abs_token = abs_token_input
    elif abs_token_clear:
        abs_token = ""
    else:
        abs_token = str(current_abs.get("api_token") or "")
    abs_verify = coerce_bool(form.get("audiobookshelf_verify_ssl"), defaults["audiobookshelf"]["verify_ssl"])
    abs_send_cover = coerce_bool(form.get("audiobookshelf_send_cover"), defaults["audiobookshelf"]["send_cover"])
    abs_send_chapters = coerce_bool(form.get("audiobookshelf_send_chapters"), defaults["audiobookshelf"]["send_chapters"])
    abs_send_subtitles = coerce_bool(form.get("audiobookshelf_send_subtitles"), defaults["audiobookshelf"]["send_subtitles"])
    abs_auto_send = coerce_bool(form.get("audiobookshelf_auto_send"), defaults["audiobookshelf"]["auto_send"])
    timeout_raw = form.get("audiobookshelf_timeout", current_abs.get("timeout", defaults["audiobookshelf"]["timeout"]))
    try:
        abs_timeout = float(timeout_raw)
    except (TypeError, ValueError):
        abs_timeout = defaults["audiobookshelf"]["timeout"]
    cfg["audiobookshelf"] = {
        "enabled": abs_enabled,
        "base_url": abs_base,
        "api_token": abs_token,
        "library_id": abs_library,
        "collection_id": abs_collection,
        "folder_id": abs_folder,
        "verify_ssl": abs_verify,
        "send_cover": abs_send_cover,
        "send_chapters": abs_send_chapters,
        "send_subtitles": abs_send_subtitles,
        "auto_send": abs_auto_send,
        "timeout": abs_timeout,
    }


def save_settings(settings: Dict[str, Any]) -> None:
    save_config(settings)
