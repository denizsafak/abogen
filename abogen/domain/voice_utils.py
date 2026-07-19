from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple, Set

from abogen.voice_formulas import extract_voice_ids, get_new_voice
from abogen.tts_plugin.utils import get_voices


def infer_provider_from_spec(value: Any, fallback: str = "kokoro") -> str:
    """Infer TTS provider from voice specification."""
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if raw.upper() == raw and raw.replace("_", "").isalnum():
        return "supertonic"
    if raw == "__custom_mix" or "*" in raw or "+" in raw:
        return "kokoro"
    if raw in get_voices("kokoro"):
        return "kokoro"
    return fallback


def supertonic_voice_from_spec(spec: Any, fallback: str) -> str:
    """Normalize a voice specification for Supertonic.

    This function only performs Supertonic-specific normalization (uppercase conversion
    and fallback handling). Backend resolution is handled by the registry.
    """
    raw = str(spec or "").strip()
    fallback_raw = str(fallback or "").strip()

    # Normalize to uppercase for Supertonic voice IDs
    upper = raw.upper() if raw else ""

    # If empty or contains formula characters, use fallback
    if not upper or "*" in upper or "+" in upper:
        upper = fallback_raw.upper() if fallback_raw else ""

    # If still empty, use default Supertonic voice
    if not upper or "*" in upper or "+" in upper:
        upper = "M1"

    return upper


def split_speaker_reference(value: Any) -> Tuple[Optional[str], str]:
    """Parse speaker/profile reference from string.

    Expected format: "speaker:name" or "profile:name"
    Returns (name, original) or (None, original) if not a valid reference.
    """
    raw = str(value or "").strip()
    if not raw or ":" not in raw:
        return None, raw
    prefix, remainder = raw.split(":", 1)
    prefix = prefix.strip().lower()
    if prefix not in {"speaker", "profile"}:
        return None, raw
    name = remainder.strip()
    return (name or None), raw


def formula_from_kokoro_entry(entry: Mapping[str, Any]) -> str:
    """Build voice formula string from kokoro entry."""
    voices = entry.get("voices") or []
    if not voices:
        return ""
    total = 0.0
    parts: list[tuple[str, float]] = []
    for item in voices:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        name = str(item[0] or "").strip()
        try:
            weight = float(item[1])
        except (TypeError, ValueError):
            continue
        if name and weight > 0:
            parts.append((name, weight))
            total += weight

    if not parts:
        return ""

    normalized = [(name, weight / total) for name, weight in parts]
    return " + ".join(f"{name}*{weight:.6f}" for name, weight in normalized)


def coerce_truthy(value: Any, default: bool = True) -> bool:
    """Coerce a value to boolean with default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in {"false", "0", "no", "off", ""}
    if value is None:
        return default
    return bool(value)


def resolve_voice_target(
    raw_spec: str,
    normalized_profiles: Dict[str, Dict[str, Any]],
    *,
    job_voice: str = "M1",
    job_tts_provider: str = "kokoro",
    job_supertonic_total_steps: int = 5,
    job_speed: float = 1.0,
) -> Tuple[str, str, Optional[float], Optional[int]]:
    """Resolve a raw voice spec into (provider, voice_spec, speed_override, steps_override).

    Pure function — all dependencies are passed as parameters.
    """
    spec = str(raw_spec or "").strip()
    speaker_name, _ = split_speaker_reference(spec)
    if speaker_name and speaker_name in normalized_profiles:
        entry = normalized_profiles[speaker_name]
        provider = str(entry.get("provider") or "kokoro").strip().lower() or "kokoro"
        if provider == "supertonic":
            voice = str(entry.get("voice") or job_voice or "M1").strip() or "M1"
            steps = int(entry.get("total_steps") or job_supertonic_total_steps or 5)
            speed = float(entry.get("speed") or job_speed or 1.0)
            return "supertonic", supertonic_voice_from_spec(voice, job_voice), speed, steps
        formula = formula_from_kokoro_entry(entry)
        return "kokoro", formula or spec, None, None

    fallback_provider = str(job_tts_provider or "kokoro").strip().lower() or "kokoro"
    inferred = infer_provider_from_spec(spec, fallback=fallback_provider)
    if inferred == "supertonic":
        return "supertonic", supertonic_voice_from_spec(spec, job_voice), None, None
    return "kokoro", spec, None, None