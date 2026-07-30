from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, cast

from abogen.speaker_configs import slugify_label
from abogen.webui.routes.utils.settings import load_settings, settings_defaults, _DEFAULT_ANALYSIS_THRESHOLD, _CHUNK_LEVEL_OPTIONS, _APOSTROPHE_MODE_OPTIONS, _NORMALIZATION_GROUPS
from abogen.voice_profiles import (
    load_profiles,
    serialize_profiles,
)
from abogen.voice_formulas import parse_formula_terms
from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    SUBTITLE_FORMATS,
    SUPPORTED_SOUND_FORMATS,
    SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
    SAMPLE_VOICE_TEXTS,
)
from abogen.tts_plugin.utils import get_voices
from abogen.speaker_configs import list_configs
from abogen.domain.voice_resolution import formula_from_profile
from abogen.domain.voice_catalog import build_voice_catalog, filter_voice_catalog


def inject_recommended_voices(
    roster: Mapping[str, Any],
    *,
    fallback_languages: Optional[Iterable[str]] = None,
) -> None:
    voice_catalog = build_voice_catalog()
    fallback_list = [code for code in (fallback_languages or []) if isinstance(code, str) and code]
    for speaker_id, payload in roster.items():
        if not isinstance(payload, dict):
            continue
        languages = payload.get("config_languages")
        if isinstance(languages, list) and languages:
            language_list = languages
        else:
            language_list = fallback_list
        gender = str(payload.get("gender", "unknown"))
        payload["recommended_voices"] = filter_voice_catalog(
            voice_catalog,
            gender=gender,
            allowed_languages=language_list,
        )


def extract_speaker_config_form(form: Mapping[str, Any]) -> Tuple[str, Dict[str, Any], List[str]]:
    getter = getattr(form, "getlist", None)

    def _get_list(name: str) -> List[str]:
        if callable(getter):
            values = cast(Iterable[Any], getter(name))
            return [str(value).strip() for value in values if value]
        raw_value = form.get(name)
        if isinstance(raw_value, str):
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return []

    name = (form.get("config_name") or "").strip()
    language = str(form.get("config_language") or "a").strip() or "a"
    allowed_languages = []
    default_voice = (form.get("config_default_voice") or "").strip()
    notes = (form.get("config_notes") or "").strip()
    
    try:
        parsed = int(form.get("config_version") or 1)
        version = max(1, min(parsed, 9999))
    except (TypeError, ValueError):
        version = 1

    speaker_rows = _get_list("speaker_rows")
    speakers: Dict[str, Dict[str, Any]] = {}
    for row_key in speaker_rows:
        prefix = f"speaker-{row_key}-"
        label = (form.get(prefix + "label") or "").strip()
        if not label:
            continue
        raw_gender = (form.get(prefix + "gender") or "unknown").strip().lower()
        gender = raw_gender if raw_gender in {"male", "female", "unknown"} else "unknown"
        voice = (form.get(prefix + "voice") or "").strip()
        voice_profile = (form.get(prefix + "profile") or "").strip()
        voice_formula = (form.get(prefix + "formula") or "").strip()
        speaker_id = (form.get(prefix + "id") or "").strip() or slugify_label(label)
        speakers[speaker_id] = {
            "id": speaker_id,
            "label": label,
            "gender": gender,
            "voice": voice,
            "voice_profile": voice_profile,
            "voice_formula": voice_formula,
            "resolved_voice": voice_formula or voice,
            "languages": [],
        }

    payload = {
        "language": language,
        "languages": allowed_languages,
        "default_voice": default_voice,
        "speakers": speakers,
        "notes": notes,
        "version": version,
    }

    errors: List[str] = []
    if not name:
        errors.append("Configuration name is required.")
    if not speakers:
        errors.append("Add at least one speaker to the configuration.")

    return name, payload, errors


def template_options() -> Dict[str, Any]:
    current_settings = load_settings()
    profiles = serialize_profiles()
    ordered_profiles = sorted(profiles.items())
    profile_options = []
    for name, entry in ordered_profiles:
        provider = str((entry or {}).get("provider") or "kokoro").strip().lower()
        profile_options.append(
            {
                "name": name,
                "language": (entry or {}).get("language", ""),
                "provider": provider,
                "formula": formula_from_profile(entry or {}) or "",
                "voice": (entry or {}).get("voice", ""),
                "total_steps": (entry or {}).get("total_steps"),
                "speed": (entry or {}).get("speed"),
            }
        )
    voice_catalog = build_voice_catalog()
    return {
        "languages": {lang.value: label for lang, label in LANGUAGE_DESCRIPTIONS.items()},
        "voices": get_voices("kokoro"),
        "subtitle_formats": SUBTITLE_FORMATS,
        "supported_langs_for_subs": SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
        "output_formats": SUPPORTED_SOUND_FORMATS,
        "voice_profiles": ordered_profiles,
        "voice_profile_options": profile_options,
        "separate_formats": ["wav", "flac", "mp3", "opus"],
        "voice_catalog": voice_catalog,
        "voice_catalog_map": {entry["id"]: entry for entry in voice_catalog},
        "sample_voice_texts": SAMPLE_VOICE_TEXTS,
        "voice_profiles_data": profiles,
        "speaker_configs": list_configs(),
        "chunk_levels": _CHUNK_LEVEL_OPTIONS,
        "speaker_analysis_threshold": current_settings.get(
            "speaker_analysis_threshold", _DEFAULT_ANALYSIS_THRESHOLD
        ),
        "speaker_pronunciation_sentence": current_settings.get(
            "speaker_pronunciation_sentence", settings_defaults()["speaker_pronunciation_sentence"]
        ),
        "apostrophe_modes": _APOSTROPHE_MODE_OPTIONS,
        "normalization_groups": _NORMALIZATION_GROUPS,
    }


def parse_voice_formula(formula: str) -> List[tuple[str, float]]:
    voices = parse_formula_terms(formula)
    total = sum(weight for _, weight in voices)
    if total <= 0:
        raise ValueError("Voice weights must sum to a positive value")
    return voices


def sanitize_voice_entries(entries: Iterable[Any]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            voice_id = entry.get("id") or entry.get("voice")
            if not voice_id:
                continue
            enabled = entry.get("enabled", True)
            if not enabled:
                continue
            sanitized.append({"voice": voice_id, "weight": entry.get("weight")})
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            sanitized.append({"voice": entry[0], "weight": entry[1]})
    return sanitized


def pairs_to_formula(pairs: Iterable[Tuple[str, float]]) -> Optional[str]:
    from abogen.voice_formulas import pairs_to_formula as _pairs_to_formula
    return _pairs_to_formula(pairs)


def profiles_payload() -> Dict[str, Any]:
    return {"profiles": serialize_profiles()}
