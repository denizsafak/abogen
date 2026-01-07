from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from abogen.constants import LANGUAGE_DESCRIPTIONS
from abogen.utils import get_user_config_path

_CONFIG_WRAPPER_KEY = "abogen_speaker_configs"


def _config_path() -> str:
    config_path = get_user_config_path()
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "speaker_configs.json")


def load_configs() -> Dict[str, Dict[str, Any]]:
    path = _config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    if isinstance(payload, dict) and _CONFIG_WRAPPER_KEY in payload:
        payload = payload[_CONFIG_WRAPPER_KEY]
    if not isinstance(payload, dict):
        return {}
    sanitized: Dict[str, Dict[str, Any]] = {}
    for name, entry in payload.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        sanitized[name] = _sanitize_config(entry)
    return sanitized


def save_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    path = _config_path()
    sanitized: Dict[str, Dict[str, Any]] = {}
    for name, entry in configs.items():
        if not isinstance(name, str) or not name.strip():
            continue
        sanitized[name] = _sanitize_config(entry)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({_CONFIG_WRAPPER_KEY: sanitized}, handle, indent=2, sort_keys=True)


def get_config(name: str) -> Optional[Dict[str, Any]]:
    name = (name or "").strip()
    if not name:
        return None
    configs = load_configs()
    data = configs.get(name)
    return dict(data) if isinstance(data, dict) else None


def upsert_config(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Configuration name is required")
    configs = load_configs()
    configs[name] = _sanitize_config(payload or {})
    save_configs(configs)
    return configs[name]


def delete_config(name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    configs = load_configs()
    if name in configs:
        del configs[name]
        save_configs(configs)


def _sanitize_config(entry: Dict[str, Any]) -> Dict[str, Any]:
    language = str(entry.get("language") or "a").strip() or "a"
    speakers_raw = entry.get("speakers")
    if not isinstance(speakers_raw, dict):
        speakers_raw = {}
    speakers: Dict[str, Any] = {}
    for speaker_id, payload in speakers_raw.items():
        if not isinstance(speaker_id, str) or not isinstance(payload, dict):
            continue
        record = _sanitize_speaker({"id": speaker_id, **payload})
        speakers[record["id"]] = record
    allowed_languages = entry.get("languages") or entry.get("allowed_languages") or []
    if not isinstance(allowed_languages, list):
        allowed_languages = []
    normalized_langs = []
    for code in allowed_languages:
        if isinstance(code, str) and code:
            normalized_langs.append(code.lower())
    default_voice = entry.get("default_voice")
    if not isinstance(default_voice, str):
        default_voice = ""
    return {
        "language": language.lower(),
        "languages": normalized_langs,
        "default_voice": default_voice,
        "speakers": speakers,
        "version": int(entry.get("version", 1)),
        "notes": entry.get("notes") if isinstance(entry.get("notes"), str) else "",
    }


def slugify_label(label: str) -> str:
    normalized = (label or "").strip().lower()
    if not normalized:
        return "speaker"
    slug = "".join(ch if ch.isalnum() else "_" for ch in normalized)
    slug = "_".join(filter(None, slug.split("_")))
    return slug or "speaker"


def _sanitize_speaker(entry: Dict[str, Any]) -> Dict[str, Any]:
    label = (entry.get("label") or entry.get("name") or "").strip()
    gender = (entry.get("gender") or "unknown").strip().lower()
    if gender not in {"male", "female", "unknown"}:
        gender = "unknown"
    voice = entry.get("voice")
    voice_profile = entry.get("voice_profile")
    voice_formula = entry.get("voice_formula")
    voice_languages = entry.get("languages") or []
    if not isinstance(voice_languages, list):
        voice_languages = []
    normalized_langs = []
    for code in voice_languages:
        if isinstance(code, str) and code:
            normalized_langs.append(code.lower())
    resolved_voice = entry.get("resolved_voice") or voice_formula or voice
    resolved_label = label or entry.get("id") or ""
    slug = entry.get("id") if isinstance(entry.get("id"), str) else slugify_label(resolved_label)
    return {
        "id": slug,
        "label": resolved_label,
        "gender": gender,
        "voice": voice if isinstance(voice, str) else "",
        "voice_profile": voice_profile if isinstance(voice_profile, str) else "",
        "voice_formula": voice_formula if isinstance(voice_formula, str) else "",
        "resolved_voice": resolved_voice if isinstance(resolved_voice, str) else "",
        "languages": normalized_langs,
    }


def list_configs() -> List[Dict[str, Any]]:
    configs = load_configs()
    ordered = []
    for name in sorted(configs):
        entry = configs[name]
        ordered.append({"name": name, **entry})
    return ordered


def describe_language(code: str) -> str:
    code = (code or "a").lower()
    return LANGUAGE_DESCRIPTIONS.get(code, code.upper())
