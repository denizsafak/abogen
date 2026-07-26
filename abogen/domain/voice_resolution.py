"""Voice resolution helpers.

Functions for resolving voice specifications, collecting required voice IDs,
and determining the voice to use for chapters and chunks.

All functions accept ConversionRequest (the app-layer contract) instead of
UI-specific objects. This keeps the domain layer UI-agnostic.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from abogen.tts_plugin.utils import get_voices, get_default_voice
from abogen.voice_formulas import extract_voice_ids
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
