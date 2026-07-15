"""Voice resolution helpers.

Functions for resolving voice specifications, collecting required voice IDs,
and determining the voice to use for chapters and chunks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from abogen.tts_plugin.utils import get_voices
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


def job_voice_fallback(job: Any) -> str:
    base = str(getattr(job, "voice", "") or "").strip()
    if base and base != "__custom_mix":
        return base

    speakers = getattr(job, "speakers", None)
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

    for chapter in getattr(job, "chapters", []) or []:
        if not isinstance(chapter, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            candidate = str(chapter.get(key) or "").strip()
            if candidate and candidate != "__custom_mix":
                return candidate

    return ""


def collect_required_voice_ids(job: Any) -> Set[str]:
    voices: Set[str] = set()
    voices.update(spec_to_voice_ids(job.voice))
    voices.update(spec_to_voice_ids(job_voice_fallback(job)))

    for chapter in getattr(job, "chapters", []) or []:
        if not isinstance(chapter, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(spec_to_voice_ids(chapter.get(key)))

    for chunk in getattr(job, "chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(spec_to_voice_ids(chunk.get(key)))

    speakers = getattr(job, "speakers", {})
    if isinstance(speakers, dict):
        for payload in speakers.values() or []:
            if not isinstance(payload, dict):
                continue
            for key in ("resolved_voice", "voice_formula", "voice"):
                voices.update(spec_to_voice_ids(payload.get(key)))

    voices.update(get_voices("kokoro"))
    return voices


def initialize_voice_cache(job: Any) -> None:
    try:
        targets = collect_required_voice_ids(job)
        downloaded, errors = ensure_voice_assets(
            targets,
            on_progress=lambda message: job.add_log(message, level="debug"),
        )
    except RuntimeError as exc:
        job.add_log(f"Voice cache unavailable: {exc}", level="warning")
        return

    if downloaded:
        job.add_log(
            f"Cached {len(downloaded)} voice asset{'s' if len(downloaded) != 1 else ''} locally.",
            level="info",
        )

    for voice_id, error in errors.items():
        job.add_log(f"Failed to cache voice '{voice_id}': {error}", level="warning")


def chapter_voice_spec(job: Any, override: Optional[Dict[str, Any]]) -> str:
    if not override:
        return job_voice_fallback(job)

    resolved = str(override.get("resolved_voice", "")).strip()
    if resolved:
        return resolved

    formula = str(override.get("voice_formula", "")).strip()
    if formula:
        return formula

    voice = str(override.get("voice", "")).strip()
    if voice:
        return voice

    return job_voice_fallback(job)


def chunk_voice_spec(job: Any, chunk: Dict[str, Any], fallback: str) -> str:
    for key in ("resolved_voice", "voice_formula", "voice"):
        value = chunk.get(key)
        if value:
            return str(value)

    speaker_id = chunk.get("speaker_id")
    speakers = getattr(job, "speakers", None)
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
    return job_voice_fallback(job)
