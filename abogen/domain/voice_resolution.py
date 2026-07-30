"""Voice resolution helpers.

Functions for resolving voice specifications, collecting required voice IDs,
and determining the voice to use for chapters and chunks.

All functions accept ConversionRequest (the app-layer contract) instead of
UI-specific objects. This keeps the domain layer UI-agnostic.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Set, Tuple

from abogen.tts_plugin.utils import get_voices, get_default_voice
from abogen.voice_formulas import extract_voice_ids, pairs_to_formula
from abogen.voice_cache import ensure_voice_assets


def spec_to_voice_ids(spec: Any) -> Set[str]:
    text = str(spec or "").strip()
    if not text:
        return set()
    if text == "__custom_mix":
        return set()
    if "*" in text:
        try:
            return set(extract_voice_ids(text))
        except ValueError:
            return set()
    if text in get_voices("kokoro"):
        return {text}
    return set()


def _get_chapter_overrides(request: Any) -> list:
    """Extract chapter overrides from ConversionRequest."""
    cc = getattr(request, "chapter_chunk", None)
    if cc is not None:
        return getattr(cc, "chapter_overrides", []) or []
    return []


def _get_chunks(request: Any) -> list:
    """Extract chunks from ConversionRequest."""
    cc = getattr(request, "chapter_chunk", None)
    if cc is not None:
        return getattr(cc, "chunks", []) or []
    return []


def job_voice_fallback(request: Any) -> str:
    base = str(getattr(request, "voice", "") or "").strip()
    if base and base != "__custom_mix":
        return base

    speakers = getattr(request, "speakers", None)
    if isinstance(speakers, dict):
        narrator = speakers.get("narrator")
        if isinstance(narrator, dict):
            for key in ("resolved_voice", "voice_formula", "voice"):
                value = narrator.get(key)
                candidate = str(value or "").strip()
                if candidate and candidate != "__custom_mix":
                    return candidate
        for payload in speakers.values() or []:
            if not isinstance(payload, dict):
                continue
            for key in ("resolved_voice", "voice_formula", "voice"):
                value = payload.get(key)
                candidate = str(value or "").strip()
                if candidate and candidate != "__custom_mix":
                    return candidate

    for chapter in _get_chapter_overrides(request):
        if not isinstance(chapter, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            candidate = str(chapter.get(key) or "").strip()
            if candidate and candidate != "__custom_mix":
                return candidate

    return ""


def collect_required_voice_ids(request: Any) -> Set[str]:
    voices: Set[str] = set()
    voices.update(spec_to_voice_ids(request.voice))
    voices.update(spec_to_voice_ids(job_voice_fallback(request)))

    for chapter in _get_chapter_overrides(request):
        if not isinstance(chapter, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(spec_to_voice_ids(chapter.get(key)))

    for chunk in _get_chunks(request):
        if not isinstance(chunk, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(spec_to_voice_ids(chunk.get(key)))

    speakers = getattr(request, "speakers", {})
    if isinstance(speakers, dict):
        for payload in speakers.values() or []:
            if not isinstance(payload, dict):
                continue
            for key in ("resolved_voice", "voice_formula", "voice"):
                voices.update(spec_to_voice_ids(payload.get(key)))

    voices.update(get_voices("kokoro"))
    return voices


def initialize_voice_cache(request: Any, events: Any = None) -> None:
    """Initialize voice cache by downloading required voice assets.

    Args:
        request: ConversionRequest with voice/chapter/chunk/speaker info.
        events: ConversionEvents for logging (optional, for backward compat).
    """
    log = (lambda msg, level="info": events.log(msg, level=level)) if events else (lambda msg, level="info": None)

    try:
        targets = collect_required_voice_ids(request)
        downloaded, errors = ensure_voice_assets(
            targets,
            on_progress=lambda message: log(message, level="debug"),
        )
    except RuntimeError as exc:
        log(f"Voice cache unavailable: {exc}", level="warning")
        return

    if downloaded:
        log(
            f"Cached {len(downloaded)} voice asset{'s' if len(downloaded) != 1 else ''} locally.",
            level="info",
        )

    for voice_id, error in errors.items():
        log(f"Failed to cache voice '{voice_id}': {error}", level="warning")


def chapter_voice_spec(request: Any, override: Optional[Dict[str, Any]]) -> str:
    if not override:
        return job_voice_fallback(request)

    resolved = str(override.get("resolved_voice", "")).strip()
    if resolved:
        return resolved

    formula = str(override.get("voice_formula", "")).strip()
    if formula:
        return formula

    voice = str(override.get("voice", "")).strip()
    if voice:
        return voice

    return job_voice_fallback(request)


def chunk_voice_spec(request: Any, chunk: Dict[str, Any], fallback: str) -> str:
    for key in ("resolved_voice", "voice_formula", "voice"):
        value = chunk.get(key)
        if value:
            return str(value)

    speaker_id = chunk.get("speaker_id")
    speakers = getattr(request, "speakers", None)
    if isinstance(speakers, dict) and speaker_id in speakers:
        speaker_entry = speakers.get(speaker_id) or {}
        if isinstance(speaker_entry, dict):
            for key in ("resolved_voice", "voice_formula", "voice"):
                value = speaker_entry.get(key)
                if value:
                    return str(value)
            profile_formula = speaker_entry.get("voice_formula")
            if profile_formula:
                return str(profile_formula)

    profile_name = chunk.get("voice_profile")
    if profile_name:
        if isinstance(speakers, dict):
            speaker_entry = speakers.get(profile_name)
            if isinstance(speaker_entry, dict):
                for key in ("resolved_voice", "voice_formula", "voice"):
                    value = speaker_entry.get(key)
                    if value:
                        return str(value)

    if fallback:
        return fallback
    return job_voice_fallback(request)


def resolve_fallback_voice_spec(
    base_spec: str,
    job_voice: str,
    voice_cache_keys: list[str],
    provider: str = "kokoro",
) -> str:
    """Resolve the voice spec for intro/outro with a priority fallback chain.

    Priority: base_spec → job_voice → first voice_cache key → default voice.
    ``"__custom_mix"`` is treated as empty (it is not a usable voice spec).
    """
    spec = base_spec or job_voice
    if spec == "__custom_mix":
        spec = job_voice or ""
    if not spec:
        for key in voice_cache_keys:
            if key and key != "__custom_mix":
                spec = key.split(":", 1)[-1]
                break
    if not spec:
        spec = get_default_voice(provider)
    return spec


# ---------------------------------------------------------------------------
# Voice choice resolution (shared by all UIs)
# ---------------------------------------------------------------------------


def formula_from_profile(entry: Dict[str, Any]) -> Optional[str]:
    """Convert a voice profile entry to a voice formula string.

    Handles both Kokoro (voices list) and SuperTonic (single voice) profiles.
    Returns None if the entry has no usable voice data.
    """
    if not isinstance(entry, dict):
        return None
    voices = entry.get("voices") or []
    if not voices:
        return None
    return pairs_to_formula(voices)


def resolve_profile_voice(
    profile_name: Optional[str],
    *,
    profiles: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    """Resolve a profile name to (formula, language).

    Args:
        profile_name: Name of the profile to resolve.
        profiles: Pre-loaded profiles dict. If None, loads from disk.

    Returns:
        (formula_string, language_code) or ("", None) if not found.
    """
    if not profile_name:
        return "", None
    source = profiles if isinstance(profiles, Mapping) else None
    if source is None:
        from abogen.voice_profiles import load_profiles
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
) -> Tuple[str, Optional[str], Optional[str]]:
    """Resolve a raw voice setting value into (spec, profile_name, language).

    Parses 'profile:name' or 'speaker:name' prefixes and resolves
    the profile to a formula string.

    Args:
        value: Raw voice value from user input (e.g. "af_heart", "profile:MyMix").
        profiles: Pre-loaded profiles dict. If None, loads from disk.

    Returns:
        (resolved_spec, profile_name, language) — profile_name and language
        are None when the input is a plain voice spec.
    """
    from abogen.domain.settings_core import split_profile_spec

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
) -> Tuple[str, str, Optional[str]]:
    """Resolve a user's voice selection into (resolved_voice, resolved_language, selected_profile).

    Handles three input modes:
    1. Profile selection → resolves to formula (Kokoro) or speaker reference (SuperTonic)
    2. Custom formula → used directly
    3. Plain voice spec → passed through

    Args:
        language: Current language code (e.g. "a", "e").
        base_voice: Base voice spec (voice ID or formula).
        profile_name: Selected profile name (empty string if none).
        custom_formula: Custom formula string (empty string if none).
        profiles: Dict of all available profiles.

    Returns:
        (resolved_voice, resolved_language, selected_profile)
    """
    from abogen.voice_profiles import normalize_profile_entry

    resolved_voice = base_voice
    resolved_language = language
    selected_profile = None

    if profile_name:
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
