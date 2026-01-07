import json
import os
from typing import Any, Dict, Iterable, List, Tuple

from abogen.constants import VOICES_INTERNAL
from abogen.tts_supertonic import DEFAULT_SUPERTONIC_VOICES
from abogen.utils import get_user_config_path


def _get_profiles_path():
    config_path = get_user_config_path()
    config_dir = os.path.dirname(config_path)
    return os.path.join(config_dir, "voice_profiles.json")


def load_profiles():
    """Load all voice profiles from JSON file."""
    path = _get_profiles_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # always expect abogen_voice_profiles wrapper
                if isinstance(data, dict) and "abogen_voice_profiles" in data:
                    return data["abogen_voice_profiles"]
                # fallback: treat as profiles dict
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
    return {}


def save_profiles(profiles):
    """Save all voice profiles to JSON file."""
    path = _get_profiles_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        # always save with abogen_voice_profiles wrapper
        json.dump({"abogen_voice_profiles": profiles}, f, indent=2)


def delete_profile(name):
    """Remove a profile by name."""
    profiles = load_profiles()
    if name in profiles:
        del profiles[name]
        save_profiles(profiles)


def duplicate_profile(src, dest):
    """Duplicate an existing profile."""
    profiles = load_profiles()
    if src in profiles and dest:
        profiles[dest] = profiles[src]
        save_profiles(profiles)


def export_profiles(export_path):
    """Export all profiles to specified JSON file."""
    profiles = load_profiles()
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump({"abogen_voice_profiles": profiles}, f, indent=2)


def serialize_profiles() -> Dict[str, Dict[str, Iterable[Tuple[str, float]]]]:
    """Return profiles in canonical dictionary form."""
    return load_profiles()


def _normalize_supertonic_voice(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return raw if raw in DEFAULT_SUPERTONIC_VOICES else "M1"


def _coerce_supertonic_steps(value: Any) -> int:
    try:
        steps = int(value)
    except (TypeError, ValueError):
        return 5
    return max(2, min(15, steps))


def _coerce_supertonic_speed(value: Any) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.7, min(2.0, speed))


def normalize_profile_entry(entry: Any) -> Dict[str, Any]:
    """Normalize a stored profile entry.

    Backwards compatible:
    - Legacy Kokoro-only entries: {language, voices}
    - New entries: include provider.
    """

    if not isinstance(entry, dict):
        return {}

    provider = str(entry.get("provider") or "kokoro").strip().lower()
    if provider not in {"kokoro", "supertonic"}:
        provider = "kokoro"

    language = str(entry.get("language") or "a").strip().lower() or "a"

    if provider == "supertonic":
        return {
            "provider": "supertonic",
            "language": language,
            "voice": _normalize_supertonic_voice(entry.get("voice") or entry.get("voice_name") or entry.get("name")),
            "total_steps": _coerce_supertonic_steps(entry.get("total_steps") or entry.get("supertonic_total_steps") or entry.get("quality")),
            "speed": _coerce_supertonic_speed(entry.get("speed") or entry.get("supertonic_speed")),
        }

    voices = _normalize_voice_entries(entry.get("voices", []))
    if not voices:
        return {}
    return {
        "provider": "kokoro",
        "language": language,
        "voices": voices,
    }


def _normalize_voice_entries(entries: Iterable) -> List[Tuple[str, float]]:
    normalized: List[Tuple[str, float]] = []
    for item in entries or []:
        if isinstance(item, dict):
            voice = item.get("id") or item.get("voice")
            weight = item.get("weight")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            voice, weight = item[0], item[1]
        else:
            continue
        if voice not in VOICES_INTERNAL:
            continue
        if weight is None:
            continue
        try:
            weight_val = float(weight)
        except (TypeError, ValueError):
            continue
        if weight_val <= 0:
            continue
        normalized.append((voice, weight_val))
    return normalized


def normalize_voice_entries(entries: Iterable) -> List[Tuple[str, float]]:
    """Public helper to normalize voice-weight pairs from arbitrary payloads."""

    return _normalize_voice_entries(entries)


def save_profile(name: str, *, language: str, voices: Iterable) -> None:
    """Persist a single profile after validating its data."""

    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name is required")

    normalized = _normalize_voice_entries(voices)
    if not normalized:
        raise ValueError("At least one voice with a weight above zero is required")

    if not language:
        language = "a"

    profiles = load_profiles()
    profiles[name] = {"provider": "kokoro", "language": language, "voices": normalized}
    save_profiles(profiles)


def remove_profile(name: str) -> None:
    delete_profile(name)


def import_profiles_data(data: Dict, *, replace_existing: bool = False) -> List[str]:
    """Merge profiles from a dictionary structure and persist them.

    Returns the list of profile names that were added or updated.
    """

    if not isinstance(data, dict):
        raise ValueError("Invalid profile payload")

    if "abogen_voice_profiles" in data:
        data = data["abogen_voice_profiles"]

    if not isinstance(data, dict):
        raise ValueError("Invalid profile payload")

    current = load_profiles()
    updated: List[str] = []
    for name, entry in data.items():
        normalized = normalize_profile_entry(entry)
        if not normalized:
            continue
        if name in current and not replace_existing:
            # skip duplicates unless explicit replacement is requested
            continue
        current[name] = normalized
        updated.append(name)

    if updated:
        save_profiles(current)
    return updated


def export_profiles_payload(names: Iterable[str] | None = None) -> Dict[str, Dict]:
    """Return profiles limited to the provided names for download/export."""

    profiles = load_profiles()
    if names is None:
        subset = profiles
    else:
        subset = {name: profiles[name] for name in names if name in profiles}
    return {"abogen_voice_profiles": subset}
