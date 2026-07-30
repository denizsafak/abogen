"""Speaker metadata functions for building and applying speaker rosters.

This module contains the core logic for:
- Building narrator and speaker rosters from analysis results
- Matching speakers to configured presets
- Applying speaker config presets to rosters
- Preparing full speaker metadata for conversion

Moved from webui/routes/utils/voice.py to be available across all UIs.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, cast

from abogen.speaker_analysis import analyze_speakers
from abogen.speaker_configs import slugify_label
from abogen.domain.settings_core import load_settings


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
    inject_recommended: Optional[Any] = None,
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
    if callable(inject_recommended):
        inject_recommended(roster, fallback_languages=fallback_languages)

    for chunk in chunk_list:
        chunk_id = str(chunk.get("id"))
        speaker_id = assignments.get(chunk_id, "narrator")
        chunk["speaker_id"] = speaker_id
        speaker_meta = roster.get(speaker_id)
        chunk["speaker_label"] = speaker_meta.get("label") if isinstance(speaker_meta, dict) else speaker_id

    return chunk_list, roster, analysis_payload, applied_languages, updated_config
