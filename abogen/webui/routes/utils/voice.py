import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, cast
import numpy as np

from abogen.speaker_configs import slugify_label
from abogen.speaker_analysis import analyze_speakers
from abogen.webui.routes.utils.settings import load_settings, settings_defaults, _DEFAULT_ANALYSIS_THRESHOLD, _CHUNK_LEVEL_OPTIONS, _APOSTROPHE_MODE_OPTIONS, _NORMALIZATION_GROUPS
from abogen.webui.routes.utils.common import split_profile_spec
from abogen.voice_profiles import (
    load_profiles,
    serialize_profiles,
)
from abogen.voice_formulas import get_new_voice, parse_formula_terms
from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    SUBTITLE_FORMATS,
    SUPPORTED_SOUND_FORMATS,
    SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION,
    SAMPLE_VOICE_TEXTS,
    VOICES_INTERNAL,
)
from abogen.speaker_configs import list_configs
from abogen.utils import load_numpy_kpipeline
from abogen.webui.conversion_runner import _select_device, _to_float32, SAMPLE_RATE, SPLIT_PATTERN

_preview_pipeline_lock = threading.RLock()
_preview_pipelines: Dict[Tuple[str, str], Any] = {}

def build_narrator_roster(
    voice: str,
    voice_profile: Optional[str],
    existing: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    roster: Dict[str, Any] = {
        "narrator": {
            "id": "narrator",
            "label": "Narrator",
            "voice": voice,
        }
    }
    if voice_profile:
        roster["narrator"]["voice_profile"] = voice_profile
    existing_entry: Optional[Mapping[str, Any]] = None
    if existing is not None:
        existing_entry = existing.get("narrator") if isinstance(existing, Mapping) else None
    if isinstance(existing_entry, Mapping):
        roster_entry = roster["narrator"]
        for key in ("label", "voice", "voice_profile", "voice_formula", "pronunciation"):
            value = existing_entry.get(key)
            if value is not None and value != "":
                roster_entry[key] = value
    return roster


def build_speaker_roster(
    analysis: Dict[str, Any],
    base_voice: str,
    voice_profile: Optional[str],
    existing: Optional[Mapping[str, Any]] = None,
    order: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    roster = build_narrator_roster(base_voice, voice_profile, existing)
    existing_map: Dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}
    speakers = analysis.get("speakers", {}) if isinstance(analysis, dict) else {}
    ordered_ids: Iterable[str]
    if order is not None:
        ordered_ids = [sid for sid in order if sid in speakers]
    else:
        ordered_ids = speakers.keys()

    for speaker_id in ordered_ids:
        payload = speakers.get(speaker_id, {})
        if speaker_id == "narrator":
            continue
        if isinstance(payload, Mapping) and payload.get("suppressed"):
            continue
        previous = existing_map.get(speaker_id)
        roster[speaker_id] = {
            "id": speaker_id,
            "label": payload.get("label") or speaker_id.replace("_", " ").title(),
            "analysis_confidence": payload.get("confidence"),
            "analysis_count": payload.get("count"),
            "gender": payload.get("gender", "unknown"),
        }
        detected_gender = payload.get("detected_gender")
        if detected_gender:
            roster[speaker_id]["detected_gender"] = detected_gender
        samples = payload.get("sample_quotes")
        if isinstance(samples, list):
            roster[speaker_id]["sample_quotes"] = samples
        if isinstance(previous, Mapping):
            for key in ("voice", "voice_profile", "voice_formula", "resolved_voice", "pronunciation"):
                value = previous.get(key)
                if value is not None and value != "":
                    roster[speaker_id][key] = value
            if "sample_quotes" not in roster[speaker_id]:
                prev_samples = previous.get("sample_quotes")
                if isinstance(prev_samples, list):
                    roster[speaker_id]["sample_quotes"] = prev_samples
            if "detected_gender" not in roster[speaker_id]:
                prev_detected = previous.get("detected_gender")
                if isinstance(prev_detected, str) and prev_detected:
                    roster[speaker_id]["detected_gender"] = prev_detected
    return roster


def match_configured_speaker(
    config_speakers: Mapping[str, Any],
    roster_id: str,
    roster_label: str,
) -> Optional[Mapping[str, Any]]:
    if not config_speakers:
        return None
    entry = config_speakers.get(roster_id)
    if entry:
        return cast(Mapping[str, Any], entry)
    slug = slugify_label(roster_label)
    if slug != roster_id and slug in config_speakers:
        return cast(Mapping[str, Any], config_speakers[slug])
    lower_label = roster_label.strip().lower()
    for record in config_speakers.values():
        if not isinstance(record, Mapping):
            continue
        if str(record.get("label", "")).strip().lower() == lower_label:
            return record
    return None


def apply_speaker_config_to_roster(
    roster: Mapping[str, Any],
    config: Optional[Mapping[str, Any]],
    *,
    persist_changes: bool = False,
    fallback_languages: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, Any], List[str], Optional[Dict[str, Any]]]:
    if not isinstance(roster, Mapping):
        effective_languages = [code for code in (fallback_languages or []) if isinstance(code, str) and code]
        return {}, effective_languages, None
    updated_roster: Dict[str, Any] = {key: dict(value) for key, value in roster.items() if isinstance(value, Mapping)}
    if not config:
        effective_languages = [code for code in (fallback_languages or []) if isinstance(code, str) and code]
        return updated_roster, effective_languages, None

    speakers_map = config.get("speakers")
    if not isinstance(speakers_map, Mapping):
        effective_languages = [code for code in (fallback_languages or []) if isinstance(code, str) and code]
        return updated_roster, effective_languages, None

    config_languages = config.get("languages")
    if isinstance(config_languages, list):
        allowed_languages = [code for code in config_languages if isinstance(code, str) and code]
    else:
        allowed_languages = []
    if not allowed_languages and fallback_languages:
        allowed_languages = [code for code in fallback_languages if isinstance(code, str) and code]

    default_voice = config.get("default_voice") if isinstance(config.get("default_voice"), str) else ""
    used_voices = {entry.get("resolved_voice") or entry.get("voice") for entry in updated_roster.values()} - {None}
    narrator_voice = ""
    narrator_entry = updated_roster.get("narrator") if isinstance(updated_roster, Mapping) else None
    if isinstance(narrator_entry, Mapping):
        narrator_voice = str(
            narrator_entry.get("resolved_voice")
            or narrator_entry.get("default_voice")
            or ""
        ).strip()
        if narrator_voice:
            used_voices.add(narrator_voice)

    config_changed = False
    new_config_payload: Dict[str, Any] = {
        "language": config.get("language", "a"),
        "languages": allowed_languages,
        "default_voice": default_voice,
        "speakers": dict(speakers_map),
        "version": config.get("version", 1),
        "notes": config.get("notes", ""),
    }

    speakers_payload = new_config_payload["speakers"]

    for speaker_id, roster_entry in updated_roster.items():
        if speaker_id == "narrator":
            continue
        label = str(roster_entry.get("label") or speaker_id)
        config_entry = match_configured_speaker(speakers_map, speaker_id, label)
        if config_entry is None:
            continue
        voice_id = str(config_entry.get("voice") or "").strip()
        voice_profile = str(config_entry.get("voice_profile") or "").strip()
        voice_formula = str(config_entry.get("voice_formula") or "").strip()
        resolved_voice = str(config_entry.get("resolved_voice") or "").strip()
        languages = config_entry.get("languages") if isinstance(config_entry.get("languages"), list) else []
        chosen_voice = resolved_voice or voice_formula or voice_id or roster_entry.get("voice")
        usable_languages = languages or allowed_languages

        if chosen_voice:
            roster_entry["resolved_voice"] = chosen_voice
            roster_entry["voice"] = chosen_voice if not voice_profile and not voice_formula else roster_entry.get("voice", chosen_voice)
        if voice_profile:
            roster_entry["voice_profile"] = voice_profile
        if voice_formula:
            roster_entry["voice_formula"] = voice_formula
            roster_entry["resolved_voice"] = voice_formula
        if not voice_formula and not voice_profile and resolved_voice:
            roster_entry["resolved_voice"] = resolved_voice
        roster_entry["config_languages"] = usable_languages or []

        if chosen_voice:
            used_voices.add(chosen_voice)

        # persist updates back to config payload if required
        if persist_changes:
            slug = config_entry.get("id") or slugify_label(label)
            speakers_payload[slug] = {
                "id": slug,
                "label": label,
                "gender": config_entry.get("gender", "unknown"),
                "voice": voice_id,
                "voice_profile": voice_profile,
                "voice_formula": voice_formula,
                "resolved_voice": roster_entry.get("resolved_voice", resolved_voice or voice_id),
                "languages": usable_languages,
            }

    new_config = new_config_payload if (persist_changes and config_changed) else None
    return updated_roster, allowed_languages, new_config


def filter_voice_catalog(
    catalog: Iterable[Mapping[str, Any]],
    *,
    gender: str,
    allowed_languages: Optional[Iterable[str]] = None,
) -> List[str]:
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


def build_voice_catalog() -> List[Dict[str, str]]:
    catalog: List[Dict[str, str]] = []
    gender_map = {"f": "Female", "m": "Male"}
    for voice_id in VOICES_INTERNAL:
        prefix, _, rest = voice_id.partition("_")
        language_code = prefix[0] if prefix else "a"
        gender_code = prefix[1] if len(prefix) > 1 else ""
        catalog.append(
            {
                "id": voice_id,
                "language": language_code,
                "language_label": LANGUAGE_DESCRIPTIONS.get(language_code, language_code.upper()),
                "gender": gender_map.get(gender_code, "Unknown"),
                "gender_code": gender_code,
                "display_name": rest.replace("_", " ").title() if rest else voice_id,
            }
        )
    return catalog


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


def prepare_speaker_metadata(
    *,
    chapters: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    analysis_chunks: Optional[List[Dict[str, Any]]] = None,
    voice: str,
    voice_profile: Optional[str],
    threshold: int,
    existing_roster: Optional[Mapping[str, Any]] = None,
    run_analysis: bool = True,
    speaker_config: Optional[Mapping[str, Any]] = None,
    apply_config: bool = False,
    persist_config: bool = False,
) -> tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], List[str], Optional[Dict[str, Any]]]:
    chunk_list = [dict(chunk) for chunk in chunks]
    analysis_source = [dict(chunk) for chunk in (analysis_chunks or chunks)]
    threshold_value = max(1, int(threshold))
    analysis_enabled = run_analysis
    settings_state = load_settings()
    global_random_languages = [
        code
        for code in settings_state.get("speaker_random_languages", [])
        if isinstance(code, str) and code
    ]

    if not analysis_enabled:
        for chunk in chunk_list:
            chunk["speaker_id"] = "narrator"
            chunk["speaker_label"] = "Narrator"
        analysis_payload = {
            "version": "1.0",
            "narrator": "narrator",
            "assignments": {str(chunk.get("id")): "narrator" for chunk in chunk_list},
            "speakers": {
                "narrator": {
                    "id": "narrator",
                    "label": "Narrator",
                    "count": len(chunk_list),
                    "confidence": "low",
                    "sample_quotes": [],
                    "suppressed": False,
                }
            },
            "suppressed": [],
            "stats": {
                "total_chunks": len(chunk_list),
                "explicit_chunks": 0,
                "active_speakers": 0,
                "unique_speakers": 1,
                "suppressed": 0,
            },
        }
        roster = build_narrator_roster(voice, voice_profile, existing_roster)
        narrator_pron = roster["narrator"].get("pronunciation")
        if narrator_pron:
            analysis_payload["speakers"]["narrator"]["pronunciation"] = narrator_pron
        return chunk_list, roster, analysis_payload, [], None

    analysis_result = analyze_speakers(
        chapters,
        analysis_source,
        threshold=threshold_value,
        max_speakers=0,
    )
    analysis_payload = analysis_result.to_dict()
    speakers_payload = analysis_payload.get("speakers", {})
    ordered_ids = [
        sid
        for sid, meta in sorted(
            (
                (sid, meta)
                for sid, meta in speakers_payload.items()
                if sid != "narrator" and isinstance(meta, Mapping) and not meta.get("suppressed")
            ),
            key=lambda item: item[1].get("count", 0),
            reverse=True,
        )
    ]
    analysis_payload["ordered_speakers"] = ordered_ids
    assignments = analysis_payload.get("assignments", {})
    suppressed_ids = analysis_payload.get("suppressed", [])
    suppressed_details: List[Dict[str, Any]] = []
    speakers_payload = analysis_payload.get("speakers", {})
    if isinstance(suppressed_ids, Iterable):
        for suppressed_id in suppressed_ids:
            speaker_meta = speakers_payload.get(suppressed_id) if isinstance(speakers_payload, dict) else None
            if isinstance(speaker_meta, dict):
                suppressed_details.append(
                    {
                        "id": suppressed_id,
                        "label": speaker_meta.get("label")
                        or str(suppressed_id).replace("_", " ").title(),
                        "pronunciation": speaker_meta.get("pronunciation"),
                    }
                )
            else:
                suppressed_details.append(
                    {
                        "id": suppressed_id,
                        "label": str(suppressed_id).replace("_", " ").title(),
                        "pronunciation": None,
                    }
                )
    analysis_payload["suppressed_details"] = suppressed_details
    roster = build_speaker_roster(
        analysis_payload,
        voice,
        voice_profile,
        existing=existing_roster,
        order=analysis_payload.get("ordered_speakers"),
    )
    applied_languages: List[str] = []
    updated_config: Optional[Dict[str, Any]] = None
    if apply_config and speaker_config:
        roster, applied_languages, updated_config = apply_speaker_config_to_roster(
            roster,
            speaker_config,
            persist_changes=persist_config,
            fallback_languages=global_random_languages,
        )
        speakers_payload = analysis_payload.get("speakers")
        if isinstance(speakers_payload, dict):
            for roster_id, roster_payload in roster.items():
                speaker_meta = speakers_payload.get(roster_id)
                if isinstance(speaker_meta, dict):
                    for key in ("voice", "voice_profile", "voice_formula", "resolved_voice"):
                        value = roster_payload.get(key)
                        if value:
                            speaker_meta[key] = value
    effective_languages: List[str] = []
    if applied_languages:
        effective_languages = applied_languages
    elif isinstance(analysis_payload.get("config_languages"), list):
        effective_languages = [
            code for code in analysis_payload.get("config_languages", []) if isinstance(code, str) and code
        ]
    elif global_random_languages:
        effective_languages = list(global_random_languages)

    if effective_languages:
        analysis_payload["config_languages"] = effective_languages
    speakers_payload = analysis_payload.get("speakers")
    if isinstance(speakers_payload, dict):
        for roster_id, roster_payload in roster.items():
            if roster_id in speakers_payload and isinstance(roster_payload, dict):
                pronunciation_value = roster_payload.get("pronunciation")
                if pronunciation_value:
                    speakers_payload[roster_id]["pronunciation"] = pronunciation_value

    fallback_languages = effective_languages or []
    inject_recommended_voices(roster, fallback_languages=fallback_languages)

    for chunk in chunk_list:
        chunk_id = str(chunk.get("id"))
        speaker_id = assignments.get(chunk_id, "narrator")
        chunk["speaker_id"] = speaker_id
        speaker_meta = roster.get(speaker_id)
        chunk["speaker_label"] = speaker_meta.get("label") if isinstance(speaker_meta, dict) else speaker_id

    return chunk_list, roster, analysis_payload, applied_languages, updated_config


def formula_from_profile(entry: Dict[str, Any]) -> Optional[str]:
    voices = entry.get("voices") or []
    if not voices:
        return None
    total = sum(weight for _, weight in voices)
    if total <= 0:
        return None

    def _format_weight(value: float) -> str:
        normalized = value / total if total else 0.0
        return (f"{normalized:.4f}").rstrip("0").rstrip(".") or "0"

    parts = [f"{name}*{_format_weight(weight)}" for name, weight in voices if weight > 0]
    return "+".join(parts) if parts else None


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
        "languages": LANGUAGE_DESCRIPTIONS,
        "voices": VOICES_INTERNAL,
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


def resolve_profile_voice(
    profile_name: Optional[str],
    *,
    profiles: Optional[Mapping[str, Any]] = None,
) -> tuple[str, Optional[str]]:
    if not profile_name:
        return "", None
    source = profiles if isinstance(profiles, Mapping) else None
    if source is None:
        source = load_profiles()
    entry = source.get(profile_name) if isinstance(source, Mapping) else None
    if not isinstance(entry, Mapping):
        return "", None
    formula = formula_from_profile(dict(entry)) or ""
    language = entry.get("language") if isinstance(entry.get("language"), str) else None
    if isinstance(language, str):
        language = language.strip().lower() or None
    return formula, language


def resolve_voice_setting(
    value: Any,
    *,
    profiles: Optional[Mapping[str, Any]] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    base_spec, profile_name = split_profile_spec(value)
    if profile_name:
        formula, language = resolve_profile_voice(profile_name, profiles=profiles)
        return formula or "", profile_name, language
    return base_spec, None, None


def resolve_voice_choice(
    language: str,
    base_voice: str,
    profile_name: str,
    custom_formula: str,
    profiles: Dict[str, Any],
) -> tuple[str, str, Optional[str]]:
    resolved_voice = base_voice
    resolved_language = language
    selected_profile = None

    if profile_name:
        from abogen.voice_profiles import normalize_profile_entry

        entry_raw = profiles.get(profile_name)
        entry = normalize_profile_entry(entry_raw)
        provider = str((entry or {}).get("provider") or "").strip().lower()

        # Provider-aware behavior:
        # - Kokoro profiles typically represent mixes (formula strings).
        # - SuperTonic profiles represent a discrete voice id + settings.
        #   In that case, we return a speaker reference so downstream can
        #   resolve provider per-speaker and allow mixed-provider casting.
        if provider == "supertonic":
            resolved_voice = f"speaker:{profile_name}"
            selected_profile = profile_name
            profile_language = (entry or {}).get("language")
            if profile_language:
                resolved_language = str(profile_language)
        else:
            formula = formula_from_profile(entry or {}) if entry else None
            if formula:
                resolved_voice = formula
                selected_profile = profile_name
                profile_language = (entry or {}).get("language")
                if profile_language:
                    resolved_language = profile_language

    if custom_formula:
        resolved_voice = custom_formula
        selected_profile = None

    return resolved_voice, resolved_language, selected_profile


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
    voices = [(voice, float(weight)) for voice, weight in pairs if float(weight) > 0]
    if not voices:
        return None
    total = sum(weight for _, weight in voices)
    if total <= 0:
        return None

    def _format_value(value: float) -> str:
        normalized = value / total if total else 0.0
        return (f"{normalized:.4f}").rstrip("0").rstrip(".") or "0"

    parts = [f"{voice}*{_format_value(weight)}" for voice, weight in voices]
    return "+".join(parts)


def profiles_payload() -> Dict[str, Any]:
    return {"profiles": serialize_profiles()}


def get_preview_pipeline(language: str, device: str):
    key = (language, device)
    with _preview_pipeline_lock:
        pipeline = _preview_pipelines.get(key)
        if pipeline is not None:
            return pipeline
        _, KPipeline = load_numpy_kpipeline()
        pipeline = KPipeline(lang_code=language, repo_id="hexgrad/Kokoro-82M", device=device)
        _preview_pipelines[key] = pipeline
        return pipeline


def synthesize_audio_from_normalized(
    *,
    normalized_text: str,
    voice_spec: str,
    language: str,
    speed: float,
    use_gpu: bool,
    max_seconds: float,
) -> np.ndarray:
    if not normalized_text.strip():
        raise ValueError("Preview text is required")

    device = "cpu"
    if use_gpu:
        try:
            device = _select_device()
        except Exception:
            device = "cpu"
            use_gpu = False

    pipeline = get_preview_pipeline(language, device)
    if pipeline is None:
        raise RuntimeError("Preview pipeline is unavailable")

    voice_choice: Any = voice_spec
    if voice_spec and "*" in voice_spec:
        voice_choice = get_new_voice(pipeline, voice_spec, use_gpu)

    segments = pipeline(
        normalized_text,
        voice=voice_choice,
        speed=speed,
        split_pattern=SPLIT_PATTERN,
    )

    audio_chunks: List[np.ndarray] = []
    accumulated = 0
    max_samples = int(max(1.0, max_seconds) * SAMPLE_RATE)

    for segment in segments:
        graphemes = getattr(segment, "graphemes", "").strip()
        if not graphemes:
            continue
        audio = _to_float32(getattr(segment, "audio", None))
        if audio.size == 0:
            continue
        remaining = max_samples - accumulated
        if remaining <= 0:
            break
        if audio.shape[0] > remaining:
            audio = audio[:remaining]
        audio_chunks.append(audio)
        accumulated += audio.shape[0]
        if accumulated >= max_samples:
            break

    if not audio_chunks:
        raise RuntimeError("Preview could not be generated")

    return np.concatenate(audio_chunks)
