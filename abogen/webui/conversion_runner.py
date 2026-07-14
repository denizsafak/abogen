from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
import gc
from datetime import datetime
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, cast

import numpy as np
import soundfile as sf
import static_ffmpeg

from abogen.tts_plugin.utils import get_voices, is_plugin_registered, resolve_voice_to_plugin
from abogen.infrastructure.exporters import ExportService
from abogen.epub3.exporter import build_epub3_package
from abogen.kokoro_text_normalization import ApostropheConfig, normalize_for_pipeline, HAS_NUM2WORDS
from abogen.normalization_settings import (
    build_apostrophe_config,
    build_llm_configuration,
    get_runtime_settings,
    apply_overrides as apply_normalization_overrides,
)
from abogen.entity_analysis import normalize_token as normalize_entity_token
from abogen.entity_analysis import normalize_manual_override_token
from abogen.text_extractor import ExtractedChapter, extract_from_path
from abogen.utils import (
    calculate_text_length,
    create_process,
    get_internal_cache_path,
    get_user_cache_path,
    get_user_output_path,
    load_config,
)
from abogen.tts_plugin.utils import create_pipeline
from abogen.voice_cache import ensure_voice_assets
from abogen.voice_formulas import extract_voice_ids, get_new_voice
from abogen.voice_profiles import load_profiles, normalize_profile_entry
from abogen.pronunciation_store import increment_usage
from abogen.llm_client import LLMClientError
from abogen.infrastructure.subtitle_writer import create_subtitle_writer, SubtitleMode
from abogen.domain.chapter_titles import (
    simplify_heading_text as _simplify_heading_text,
    headings_equivalent as _headings_equivalent,
    strip_duplicate_heading_line as _strip_duplicate_heading_line,
    normalize_caps_word as _normalize_caps_word,
    normalize_chapter_opening_caps as _normalize_chapter_opening_caps,
    format_spoken_chapter_title as _format_spoken_chapter_title,
)
from abogen.domain.metadata_helpers import (
    normalize_metadata_map as _normalize_metadata_map,
    format_author_sentence as _format_author_sentence,
    ensure_sentence as _ensure_sentence,
    normalize_series_number as _normalize_series_number,
    extract_series_metadata as _extract_series_metadata,
    format_series_sentence as _format_series_sentence,
)


from .service import Job, JobStatus


_export_svc = ExportService()

SPLIT_PATTERN = r"\n+"
SAMPLE_RATE = 24000


def _supertonic_voice_from_spec(spec: Any, fallback: str) -> str:
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


def _split_speaker_reference(value: Any) -> tuple[Optional[str], str]:
    raw = str(value or "").strip()
    if not raw or ":" not in raw:
        return None, raw
    prefix, remainder = raw.split(":", 1)
    prefix = prefix.strip().lower()
    if prefix not in {"speaker", "profile"}:
        return None, raw
    name = remainder.strip()
    return (name or None), raw


def _formula_from_kokoro_entry(entry: Mapping[str, Any]) -> str:
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
        if not name or weight <= 0:
            continue
        parts.append((name, weight))
        total += weight
    if total <= 0 or not parts:
        return ""

    def _format_weight(value: float) -> str:
        normalized = value / total if total else 0.0
        return (f"{normalized:.4f}").rstrip("0").rstrip(".") or "0"

    return "+".join(f"{name}*{_format_weight(weight)}" for name, weight in parts)


def _infer_provider_from_spec(value: Any, fallback: str = "kokoro") -> str:
    return resolve_voice_to_plugin(str(value or ""), fallback=fallback)


class _JobCancelled(Exception):
    """Raised internally to abort a conversion when the client cancels."""


@dataclass
class AudioSink:
    write: Callable[[np.ndarray], None]


def _coerce_truthy(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


_OUTPUT_SANITIZE_RE = re.compile(r"[^\w\-_.]+")


def _build_title_intro_text(
    metadata: Optional[Mapping[str, Any]],
    fallback_basename: str,
) -> str:
    normalized = _normalize_metadata_map(metadata)
    fallback_title = Path(fallback_basename).stem if fallback_basename else ""
    title = normalized.get("title") or normalized.get("book_title") or normalized.get("album") or fallback_title
    if not title:
        title = fallback_title
    subtitle = normalized.get("subtitle") or normalized.get("sub_title")
    if subtitle and title and subtitle.casefold() == title.casefold():
        subtitle = ""
    author_value = ""
    for candidate in ("artist", "album_artist", "author", "authors", "writer", "composer"):
        value = normalized.get(candidate)
        if value:
            author_value = value
            break

    series_name, series_number = _extract_series_metadata(normalized)
    series_sentence = _format_series_sentence(series_name, series_number)

    sentences: List[str] = []
    if series_sentence:
        sentences.append(_ensure_sentence(series_sentence))
    if title:
        sentences.append(_ensure_sentence(title))
    if subtitle:
        sentences.append(_ensure_sentence(subtitle))
    author_sentence = _format_author_sentence(author_value)
    if author_sentence:
        sentences.append(_ensure_sentence(author_sentence))
    return " ".join(sentences).strip()


def _build_outro_text(
    metadata: Optional[Mapping[str, Any]],
    fallback_basename: str,
) -> str:
    normalized = _normalize_metadata_map(metadata)
    fallback_title = Path(fallback_basename).stem if fallback_basename else ""
    title = (
        normalized.get("title")
        or normalized.get("book_title")
        or normalized.get("album")
        or fallback_title
    )
    author_value = ""
    for candidate in ("authors", "author", "album_artist", "artist", "writer", "composer"):
        value = normalized.get(candidate)
        if value:
            author_value = value
            break
    author_sentence = _format_author_sentence(author_value)
    authors_fragment = author_sentence[3:].strip() if author_sentence.lower().startswith("by ") else author_sentence.strip()

    if title and authors_fragment:
        closing_line = f"The end of {title} from {authors_fragment}"
    elif title:
        closing_line = f"The end of {title}"
    elif authors_fragment:
        closing_line = f"The end from {authors_fragment}"
    else:
        closing_line = "The end"

    series_name, series_number = _extract_series_metadata(normalized)
    series_sentence = _format_series_sentence(series_name, series_number)

    sentences: List[str] = [_ensure_sentence(closing_line)]
    if series_sentence:
        sentences.append(_ensure_sentence(series_sentence))

    return " ".join(sentence for sentence in sentences if sentence).strip()


def _spec_to_voice_ids(spec: Any) -> Set[str]:
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


def _job_voice_fallback(job: Any) -> str:
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


def _collect_required_voice_ids(job: Job) -> Set[str]:
    voices: Set[str] = set()
    voices.update(_spec_to_voice_ids(job.voice))
    voices.update(_spec_to_voice_ids(_job_voice_fallback(job)))

    for chapter in getattr(job, "chapters", []) or []:
        if not isinstance(chapter, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(_spec_to_voice_ids(chapter.get(key)))

    for chunk in getattr(job, "chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        for key in ("resolved_voice", "voice_formula", "voice"):
            voices.update(_spec_to_voice_ids(chunk.get(key)))

    speakers = getattr(job, "speakers", {})
    if isinstance(speakers, dict):
        for payload in speakers.values() or []:
            if not isinstance(payload, dict):
                continue
            for key in ("resolved_voice", "voice_formula", "voice"):
                voices.update(_spec_to_voice_ids(payload.get(key)))

    voices.update(get_voices("kokoro"))
    return voices


def _initialize_voice_cache(job: Job) -> None:
    try:
        targets = _collect_required_voice_ids(job)
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


_SIGNIFICANT_LENGTH_THRESHOLDS: Dict[str, int] = {"epub": 1000, "markdown": 500}
_MIN_SHORT_CONTENT: Dict[str, int] = {"epub": 240, "markdown": 160}
_STRUCTURAL_KEYWORDS = (
    "preface",
    "prologue",
    "introduction",
    "foreword",
    "epilogue",
    "afterword",
    "appendix",
    "acknowledgment",
    "acknowledgement",
)
_STRUCTURAL_MIN_LENGTH = 120
_MAX_SHORT_CHAPTERS = 2


def _infer_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return "epub"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".txt":
        return "text"
    return suffix.lstrip(".") or "text"


def _looks_structural(title: str) -> bool:
    lowered = title.strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in _STRUCTURAL_KEYWORDS)


def _auto_select_relevant_chapters(
    chapters: List[ExtractedChapter],
    file_type: str,
) -> tuple[List[ExtractedChapter], List[tuple[str, int]]]:
    if not chapters:
        return [], []

    normalized = file_type.lower()
    threshold = _SIGNIFICANT_LENGTH_THRESHOLDS.get(normalized, 0)
    min_short = _MIN_SHORT_CONTENT.get(normalized, 0)

    kept: List[ExtractedChapter] = []
    skipped: List[tuple[str, int]] = []
    short_kept = 0

    for chapter in chapters:
        stripped = chapter.text.strip()
        length = len(stripped)
        if length == 0:
            skipped.append((chapter.title, length))
            continue

        keep = False
        if threshold == 0:
            keep = True
        elif length >= threshold:
            keep = True
        elif not kept:
            keep = True
        elif min_short and length >= min_short and short_kept < _MAX_SHORT_CHAPTERS:
            keep = True
            short_kept += 1
        elif _looks_structural(chapter.title) and length >= _STRUCTURAL_MIN_LENGTH:
            keep = True

        if keep:
            kept.append(chapter)
        else:
            skipped.append((chapter.title, length))

    if kept:
        return kept, skipped

    # Fallback: retain the longest non-empty chapter so conversion can proceed.
    longest_idx = None
    longest_length = 0
    for idx, chapter in enumerate(chapters):
        stripped_length = len(chapter.text.strip())
        if stripped_length > longest_length:
            longest_length = stripped_length
            longest_idx = idx

    if longest_idx is None or longest_length == 0:
        return [], []

    fallback_chapter = chapters[longest_idx]
    kept = [fallback_chapter]
    skipped = [
        (chapter.title, len(chapter.text.strip()))
        for idx, chapter in enumerate(chapters)
        if idx != longest_idx and chapter.text.strip()
    ]
    return kept, skipped


def _chapter_label(file_type: str) -> str:
    return "chapters" if file_type.lower() in {"epub", "markdown"} else "pages"


def _update_metadata_for_chapter_count(metadata: Dict[str, Any], count: int, file_type: str) -> None:
    if not metadata or count <= 0:
        return

    label = "Chapters" if file_type.lower() in {"epub", "markdown"} else "Pages"
    metadata["chapter_count"] = str(count)

    pattern = re.compile(r"\(\d+\s+(Chapters?|Pages?)\)")
    replacement = f"({count} {label})"
    for key in ("album", "ALBUM"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        metadata[key] = pattern.sub(replacement, value)


def _apply_chapter_overrides(
    extracted: List[ExtractedChapter],
    overrides: List[Dict[str, Any]],
) -> tuple[List[ExtractedChapter], Dict[str, str], List[str]]:
    if not overrides:
        return [], {}, []

    selected: List[ExtractedChapter] = []
    metadata_updates: Dict[str, str] = {}
    diagnostics: List[str] = []

    for position, payload in enumerate(overrides):
        if not isinstance(payload, dict):
            diagnostics.append(
                f"Skipped chapter override at position {position + 1}: unsupported payload type {type(payload).__name__}."
            )
            continue

        enabled = _coerce_truthy(payload.get("enabled", True))
        payload["enabled"] = enabled
        if not enabled:
            continue

        metadata_payload = payload.get("metadata") or {}
        if isinstance(metadata_payload, dict):
            for key, value in metadata_payload.items():
                if value is None:
                    continue
                metadata_updates[str(key)] = str(value)

        base: Optional[ExtractedChapter] = None
        idx_candidate = payload.get("index")
        idx_normalized: Optional[int] = None
        if isinstance(idx_candidate, int):
            idx_normalized = idx_candidate
        elif isinstance(idx_candidate, str):
            try:
                idx_normalized = int(idx_candidate)
            except ValueError:
                idx_normalized = None
        if idx_normalized is not None and 0 <= idx_normalized < len(extracted):
            base = extracted[idx_normalized]
            payload["index"] = idx_normalized

        if base is None:
            source_title = payload.get("source_title")
            if isinstance(source_title, str):
                base = next((chapter for chapter in extracted if chapter.title == source_title), None)

        if base is None:
            candidate_title = payload.get("title")
            if isinstance(candidate_title, str):
                base = next((chapter for chapter in extracted if chapter.title == candidate_title), None)

        text_override = payload.get("text")
        if text_override is not None:
            text_value = str(text_override)
        elif base is not None:
            text_value = base.text
        else:
            diagnostics.append(
                f"Skipped chapter override at position {position + 1}: no text provided and no matching source chapter found."
            )
            continue

        title_override = payload.get("title")
        if title_override is not None:
            title_value = str(title_override)
        elif base is not None:
            title_value = base.title
        else:
            title_value = f"Chapter {position + 1}"

        if base and not payload.get("source_title"):
            payload["source_title"] = base.title

        payload["title"] = title_value
        payload["text"] = text_value
        payload["characters"] = len(text_value)
        payload.setdefault("order", payload.get("order", position))

        selected.append(ExtractedChapter(title=title_value, text=text_value))

    return selected, metadata_updates, diagnostics


def _merge_metadata(
    extracted: Optional[Dict[str, str]],
    overrides: Dict[str, Any],
) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    if extracted:
        for key, value in extracted.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
    for key, value in (overrides or {}).items():
        key_str = str(key)
        if value is None:
            merged.pop(key_str, None)
        else:
            merged[key_str] = str(value)
    return merged


_APOSTROPHE_CONFIG = ApostropheConfig()


def _normalize_for_pipeline(
    text: str,
    *,
    normalization_overrides: Optional[Mapping[str, Any]] = None,
) -> str:
    """Normalize text for tests or utilities with optional overrides."""

    runtime_settings = get_runtime_settings()
    if normalization_overrides:
        runtime_settings = apply_normalization_overrides(runtime_settings, normalization_overrides)
    apostrophe_config = build_apostrophe_config(settings=runtime_settings, base=_APOSTROPHE_CONFIG)
    return normalize_for_pipeline(text, config=apostrophe_config, settings=runtime_settings)


def _merge_pronunciation_overrides(job: Any) -> List[Dict[str, Any]]:
    """Return pronunciation override entries, ensuring manual overrides are included.

    Pending jobs keep both `manual_overrides` and `pronunciation_overrides`, but the
    latter can be stale if the UI didn't resync before enqueue. During conversion,
    we must merge manual overrides so they always apply (before TTS).

    Precedence: manual overrides win over existing entries for the same normalized key.
    """

    collected: Dict[str, Dict[str, Any]] = {}

    existing = getattr(job, "pronunciation_overrides", None)
    if isinstance(existing, list):
        for entry in existing:
            if not isinstance(entry, Mapping):
                continue
            token_value = str(entry.get("token") or "").strip()
            pronunciation_value = str(entry.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = str(entry.get("normalized") or "").strip() or normalize_entity_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(entry.get("voice") or "").strip() or None,
                "notes": str(entry.get("notes") or "").strip() or None,
                "context": str(entry.get("context") or "").strip() or None,
                "source": str(entry.get("source") or "pronunciation"),
                "language": getattr(job, "language", None),
            }

    # Speaker pronunciation entries (optional), mirrored from the pending-job collector.
    speakers = getattr(job, "speakers", None)
    if isinstance(speakers, dict):
        for payload in speakers.values():
            if not isinstance(payload, Mapping):
                continue
            token_value = str(payload.get("token") or "").strip()
            pronunciation_value = str(payload.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = normalize_entity_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(
                    payload.get("resolved_voice")
                    or payload.get("voice")
                    or getattr(job, "voice", "")
                ).strip()
                or None,
                "notes": None,
                "context": None,
                "source": "speaker",
                "language": getattr(job, "language", None),
            }

    # Manual overrides should take precedence.
    manual = getattr(job, "manual_overrides", None)
    if isinstance(manual, list):
        for entry in manual:
            if not isinstance(entry, Mapping):
                continue
            token_value = str(entry.get("token") or "").strip()
            pronunciation_value = str(entry.get("pronunciation") or "").strip()
            if not token_value or not pronunciation_value:
                continue
            normalized = str(entry.get("normalized") or "").strip() or normalize_manual_override_token(token_value)
            if not normalized:
                continue
            collected[normalized] = {
                "token": token_value,
                "normalized": normalized,
                "pronunciation": pronunciation_value,
                "voice": str(entry.get("voice") or "").strip() or None,
                "notes": str(entry.get("notes") or "").strip() or None,
                "context": str(entry.get("context") or "").strip() or None,
                "source": str(entry.get("source") or "manual"),
                "language": getattr(job, "language", None),
            }

    return list(collected.values())


def _compile_pronunciation_rules(
    overrides: Optional[Iterable[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    if not overrides:
        return []

    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for entry in overrides:
        if not isinstance(entry, Mapping):
            continue
        pronunciation_value = str(entry.get("pronunciation") or "").strip()
        if not pronunciation_value:
            continue

        token_values: List[str] = []
        token_raw = entry.get("token")
        if token_raw:
            token_value = str(token_raw).strip()
            if token_value:
                token_values.append(token_value)
        normalized_raw = entry.get("normalized")
        if normalized_raw:
            normalized_value = str(normalized_raw).strip()
            if normalized_value:
                token_values.append(normalized_value)
        if token_raw and not token_values:
            fallback = normalize_entity_token(str(token_raw))
            if fallback:
                token_values.append(fallback)

        if not token_values:
            continue

        usage_normalized = str(entry.get("normalized") or "").strip()
        if not usage_normalized and token_values:
            usage_normalized = normalize_entity_token(token_values[0]) or token_values[0]
        usage_token = str(entry.get("token") or token_values[0])

        for token_value in token_values:
            key = token_value.casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "token": token_value,
                    "normalized": usage_normalized,
                    "replacement": pronunciation_value,
                }
            )

    if not candidates:
        return []

    candidates.sort(key=lambda item: len(item["token"]), reverse=True)
    compiled: List[Dict[str, Any]] = []
    for candidate in candidates:
        token_value = candidate["token"]
        pronunciation_value = candidate["replacement"]
        escaped = re.escape(token_value)
        pattern = re.compile(rf"(?i)(?<!\w){escaped}(?P<possessive>'s|\u2019s|\u2019)?(?!\w)")
        compiled.append(
            {
                "pattern": pattern,
                "replacement": pronunciation_value,
                "normalized": candidate.get("normalized") or token_value,
                "token": candidate.get("token") or token_value,
            }
        )

    return compiled


def _compile_heteronym_sentence_rules(
    overrides: Optional[Iterable[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    """Compile sentence-level replacements for heteronym disambiguation.

    These are intentionally scoped to a specific sentence string rather than a token,
    so we can apply different pronunciations for the same word in different contexts.

    Expected override entry shape (from pending/job):
    - sentence: original sentence text
    - choice: selected option key
    - options: [{key, replacement_sentence, ...}]
    """
    if not overrides:
        return []

    compiled: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for entry in overrides:
        if not isinstance(entry, Mapping):
            continue
        sentence = str(entry.get("sentence") or "").strip()
        if not sentence:
            continue
        choice = str(entry.get("choice") or "").strip()
        if not choice:
            continue

        replacement_sentence = ""
        options = entry.get("options")
        if isinstance(options, list):
            for opt in options:
                if not isinstance(opt, Mapping):
                    continue
                if str(opt.get("key") or "").strip() == choice:
                    replacement_sentence = str(opt.get("replacement_sentence") or "").strip()
                    break
        if not replacement_sentence:
            continue

        rule_key = f"{sentence}\n{choice}".casefold()
        if rule_key in seen:
            continue
        seen.add(rule_key)

        parts = [p for p in re.split(r"\s+", sentence) if p]
        if not parts:
            continue
        pattern_text = r"\s+".join(re.escape(p) for p in parts)
        pattern = re.compile(pattern_text)
        compiled.append({"pattern": pattern, "replacement": replacement_sentence})

    # Replace longer sentences first to avoid partial matches.
    compiled.sort(key=lambda item: len(item["pattern"].pattern), reverse=True)
    return compiled


def _apply_heteronym_sentence_rules(text: str, rules: List[Dict[str, Any]]) -> str:
    if not text or not rules:
        return text
    result = text
    for rule in rules:
        pattern = rule["pattern"]
        replacement = rule["replacement"]
        result = pattern.sub(replacement, result)
    return result


def _apply_pronunciation_rules(
    text: str,
    rules: List[Dict[str, Any]],
    usage_counter: Optional[Dict[str, int]] = None,
) -> str:
    if not text or not rules:
        return text

    result = text
    for rule in rules:
        pattern = rule["pattern"]
        pronunciation_value = rule["replacement"]
        usage_key = str(rule.get("normalized") or "").strip()

        def _replacement(match: re.Match[str]) -> str:
            suffix = match.group("possessive") or ""
            if usage_counter is not None and usage_key:
                usage_counter[usage_key] = usage_counter.get(usage_key, 0) + 1
            return pronunciation_value + suffix

        result = pattern.sub(_replacement, result)

    return result


def _chapter_voice_spec(job: Job, override: Optional[Dict[str, Any]]) -> str:
    if not override:
        return _job_voice_fallback(job)

    resolved = str(override.get("resolved_voice", "")).strip()
    if resolved:
        return resolved

    formula = str(override.get("voice_formula", "")).strip()
    if formula:
        return formula

    voice = str(override.get("voice", "")).strip()
    if voice:
        return voice

    return _job_voice_fallback(job)


def _chunk_voice_spec(job: Any, chunk: Dict[str, Any], fallback: str) -> str:
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
    return _job_voice_fallback(job)


def _group_chunks_by_chapter(chunks: Iterable[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for entry in chunks or []:
        if not isinstance(entry, dict):
            continue
        try:
            chapter_index = int(entry.get("chapter_index", 0))
        except (TypeError, ValueError):
            chapter_index = 0
        grouped[chapter_index].append(dict(entry))

    for chapter_index, items in grouped.items():
        items.sort(key=lambda payload: _safe_int(payload.get("chunk_index")))

    return grouped


def _record_override_usage(
    job: Job,
    usage_counter: Mapping[str, int],
    token_map: Mapping[str, str],
) -> None:
    if not usage_counter:
        return

    language = getattr(job, "language", "") or "a"
    for normalized, amount in usage_counter.items():
        if amount <= 0:
            continue
        token_value = token_map.get(normalized, normalized)
        try:
            increment_usage(language=language, token=token_value, amount=int(amount))
        except Exception:  # pragma: no cover - defensive logging
            job.add_log(f"Failed to record usage for override {token_value}", level="warning")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _chunk_text_for_tts(entry: Mapping[str, Any]) -> str:
    """Choose the best source text for synthesis.

    We must prefer the raw chunk text (`text` / `original_text`) so manual/pronunciation
    overrides can match against the original tokens (e.g. censored words like `Unfu*k`).
    `normalized_text` may have already been run through `normalize_for_pipeline`, which
    can remove punctuation and prevent overrides from triggering.
    """

    if not isinstance(entry, Mapping):
        return ""
    return str(
        entry.get("text")
        or entry.get("original_text")
        or entry.get("normalized_text")
        or ""
    ).strip()


def _apply_m4b_chapters_with_mutagen(
    audio_path: Path,
    chapters: List[Dict[str, Any]],
    job: Job,
) -> bool:
    if not chapters:
        return False

    try:
        from fractions import Fraction
        from mutagen.mp4 import MP4, MP4Chapter  # type: ignore[import]
    except ImportError:
        job.add_log(
            "Unable to write MP4 chapter atoms because mutagen is not installed.",
            level="warning",
        )
        return False

    try:
        mp4 = MP4(str(audio_path))
    except Exception as exc:  # pragma: no cover - defensive
        job.add_log(f"Failed to open m4b for chapter embedding: {exc}", level="warning")
        return False

    chapter_objects: List[MP4Chapter] = []
    for index, entry in enumerate(sorted(chapters, key=lambda item: float(item.get("start") or 0.0))):
        start_raw = entry.get("start")
        if start_raw is None:
            continue
        try:
            start_seconds = max(0.0, float(start_raw))
        except (TypeError, ValueError):
            continue

        title_value = entry.get("title")
        title_text = str(title_value) if title_value else f"Chapter {index + 1}"

        start_fraction = Fraction(int(round(start_seconds * 1000)), 1000)
        chapter_atom = MP4Chapter(start_fraction, title_text)

        end_raw = entry.get("end")
        if end_raw is not None:
            try:
                end_seconds = float(end_raw)
            except (TypeError, ValueError):
                end_seconds = None
            if end_seconds is not None and end_seconds > start_seconds:
                chapter_atom.end = Fraction(int(round(end_seconds * 1000)), 1000)

        chapter_objects.append(chapter_atom)

    if not chapter_objects:
        return False

    try:
        mp4.chapters = cast(Any, chapter_objects)
        mp4.save()
    except Exception as exc:  # pragma: no cover - defensive
        job.add_log(f"Failed to persist MP4 chapter atoms: {exc}", level="warning")
        return False

    return True


def _embed_m4b_metadata(
    audio_path: Path,
    metadata_payload: Dict[str, Any],
    job: Job,
) -> None:
    metadata_map = dict(metadata_payload.get("metadata") or {})
    chapter_entries = list(metadata_payload.get("chapters") or [])
    ffmetadata_path = _export_svc.write_ffmetadata_file(audio_path, metadata_map, chapter_entries)
    cover_path: Optional[Path] = None
    if job.cover_image_path:
        candidate = Path(job.cover_image_path)
        if candidate.exists():
            cover_path = candidate

    metadata_args = _export_svc._metadata_to_ffmpeg_args(metadata_map)

    if not ffmetadata_path and not cover_path and not metadata_args:
        return

    job.add_log("Embedding metadata into m4b output")

    command: List[str] = ["ffmpeg", "-y", "-i", str(audio_path)]
    metadata_index: Optional[int] = None
    cover_index: Optional[int] = None
    next_index = 1

    if ffmetadata_path:
        command += ["-f", "ffmetadata", "-i", str(ffmetadata_path)]
        metadata_index = next_index
        next_index += 1

    if cover_path:
        command += ["-i", str(cover_path)]
        cover_index = next_index
        next_index += 1

    command += ["-map", "0:a"]
    command += ["-c:a", "copy"]

    if cover_index is not None:
        command += ["-map", f"{cover_index}:v:0"]
        command += ["-c:v:0", "mjpeg"]
        command += ["-disposition:v:0", "attached_pic"]
        command += ["-metadata:s:v:0", "title=Cover Art"]
        if job.cover_image_mime:
            command += ["-metadata:s:v:0", f"mimetype={job.cover_image_mime}"]

    if metadata_index is not None:
        command += ["-map_metadata", str(metadata_index)]
        command += ["-map_chapters", str(metadata_index)]
    else:
        command += ["-map_metadata", "0"]

    if metadata_args:
        command.extend(metadata_args)

    command += ["-movflags", "+faststart+use_metadata_tags"]

    temp_output = audio_path.with_suffix(audio_path.suffix + ".tmp")
    if audio_path.suffix.lower() in {".m4b", ".mp4", ".m4a"}:
        command += ["-f", "mp4"]
    command.append(str(temp_output))

    process = create_process(command, text=True)
    try:
        return_code = process.wait()
    finally:
        if ffmetadata_path and ffmetadata_path.exists():
            try:
                ffmetadata_path.unlink()
            except OSError:
                pass

    if return_code != 0:
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed to embed metadata (exit code {return_code})")

    temp_output.replace(audio_path)
    job.add_log("Embedded metadata and chapters into m4b output", level="info")

    mutagen_applied = _apply_m4b_chapters_with_mutagen(audio_path, chapter_entries, job)
    if mutagen_applied:
        job.add_log(
            f"Applied {len(chapter_entries)} chapter markers via mutagen", level="info"
        )


def run_conversion_job(job: Job) -> None:
    job.add_log("Preparing conversion pipeline")
    canceller = _make_canceller(job)

    normalization_settings = get_runtime_settings()
    job_overrides = getattr(job, "normalization_overrides", None)
    if job_overrides:
        normalization_settings = apply_normalization_overrides(normalization_settings, job_overrides)
    apostrophe_config = build_apostrophe_config(
        settings=normalization_settings,
        base=_APOSTROPHE_CONFIG,
    )
    
    if apostrophe_config.convert_numbers and not HAS_NUM2WORDS:
        job.add_log(
            "Number normalization is enabled but 'num2words' library is not available. "
            "Numbers (including years) will NOT be converted to words. "
            "Please install 'num2words' to enable this feature.",
            level="warning"
        )

    apostrophe_mode = str(normalization_settings.get("normalization_apostrophe_mode", "spacy")).lower()
    if apostrophe_mode == "llm":
        llm_config = build_llm_configuration(normalization_settings)
        if not llm_config.is_configured():
            raise RuntimeError(
                "LLM-based apostrophe normalization is selected, but the LLM configuration is incomplete."
            )

    sink_stack = ExitStack()
    subtitle_writer = None
    chapter_paths: list[Path] = []
    chapter_markers: List[Dict[str, Any]] = []
    chunk_markers: List[Dict[str, Any]] = []
    metadata_payload: Dict[str, Any] = {}
    audio_output_path: Optional[Path] = None
    extraction: Optional[Any] = None
    pipeline: Any = None
    pipelines: Dict[str, Any] = {}
    kokoro_cache_ready = False
    normalized_profiles: Dict[str, Dict[str, Any]] = {}
    chunk_groups: Dict[int, List[Dict[str, Any]]] = {}
    active_chapter_configs: List[Dict[str, Any]] = []
    usage_counter: Dict[str, int] = defaultdict(int)
    override_token_map: Dict[str, str] = {}
    try:
        # Load saved speakers once so we can resolve speaker: references during conversion.
        try:
            profiles = load_profiles()
        except Exception:
            profiles = {}
        for name, entry in (profiles or {}).items():
            normalized = normalize_profile_entry(entry)
            if normalized:
                normalized_profiles[str(name)] = normalized

        def get_pipeline(provider: str) -> Any:
            nonlocal kokoro_cache_ready
            provider_norm = str(provider or "kokoro").strip().lower() or "kokoro"
            if not is_plugin_registered(provider_norm):
                provider_norm = "kokoro"

            existing = pipelines.get(provider_norm)
            if existing is not None:
                return existing

            if provider_norm == "supertonic":
                pipelines[provider_norm] = create_pipeline(
                    "supertonic",
                )
                return pipelines[provider_norm]

            # Kokoro
            cfg = load_config()
            disable_gpu = not job.use_gpu or not cfg.get("use_gpu", True)
            device = "cpu"
            if not disable_gpu:
                device = _select_device()
            # Create KPipeline instance directly (uses new Plugin Architecture)
            pipelines[provider_norm] = create_pipeline(
                "kokoro",
                lang_code=job.language,
                device=device
            )
            if not kokoro_cache_ready:
                _initialize_voice_cache(job)
                kokoro_cache_ready = True
            return pipelines[provider_norm]

        def resolve_voice_target(raw_spec: str) -> tuple[str, str, Optional[float], Optional[int]]:
            """Return (provider, voice_spec, speed_override, steps_override)."""
            spec = str(raw_spec or "").strip()
            speaker_name, _ = _split_speaker_reference(spec)
            if speaker_name and speaker_name in normalized_profiles:
                entry = normalized_profiles[speaker_name]
                provider = str(entry.get("provider") or "kokoro").strip().lower() or "kokoro"
                if provider == "supertonic":
                    voice = str(entry.get("voice") or getattr(job, "voice", "M1") or "M1").strip() or "M1"
                    steps = int(entry.get("total_steps") or getattr(job, "supertonic_total_steps", 5) or 5)
                    speed = float(entry.get("speed") or getattr(job, "speed", 1.0) or 1.0)
                    return "supertonic", _supertonic_voice_from_spec(voice, getattr(job, "voice", "M1")), speed, steps
                formula = _formula_from_kokoro_entry(entry)
                return "kokoro", formula or spec, None, None

            fallback_provider = str(getattr(job, "tts_provider", "kokoro") or "kokoro").strip().lower() or "kokoro"
            inferred = _infer_provider_from_spec(spec, fallback=fallback_provider)
            if inferred == "supertonic":
                return "supertonic", _supertonic_voice_from_spec(spec, getattr(job, "voice", "M1")), None, None
            return "kokoro", spec, None, None

        def resolve_voice_choice(raw_spec: str) -> tuple[str, str, Any, Optional[float], Optional[int]]:
            """Resolve a raw voice spec into (provider, resolved_spec, choice, speed, steps).

            For Kokoro formulas, `choice` will be a resolved voice tensor (via `voice_formulas`).
            For SuperTonic, `choice` will be a valid SuperTonic voice id.
            """

            provider, resolved, speed, steps = resolve_voice_target(raw_spec)
            cache_key = f"{provider}:{resolved}" if resolved else provider
            cached = voice_cache.get(cache_key)
            if cached is not None:
                return provider, resolved, cached, speed, steps

            if provider == "kokoro":
                kokoro_backend = get_pipeline("kokoro")
                choice = _resolve_voice(kokoro_backend, resolved, job.use_gpu)
            else:
                choice = resolved

            voice_cache[cache_key] = choice
            return provider, resolved, choice, speed, steps

        extraction = extract_from_path(job.stored_path)
        file_type = _infer_file_type(job.stored_path)
        pronunciation_overrides = _merge_pronunciation_overrides(job)
        pronunciation_rules = _compile_pronunciation_rules(pronunciation_overrides)
        heteronym_sentence_rules = _compile_heteronym_sentence_rules(
            getattr(job, "heteronym_overrides", None)
        )
        if heteronym_sentence_rules:
            job.add_log(
                f"Applying {len(heteronym_sentence_rules)} heteronym override{'s' if len(heteronym_sentence_rules) != 1 else ''} during conversion.",
                level="debug",
            )
        if pronunciation_rules:
            count = len(pronunciation_rules)
            job.add_log(
                f"Applying {count} pronunciation override{'s' if count != 1 else ''} during conversion.",
                level="debug",
            )
        for override_entry in pronunciation_overrides or []:
            if not isinstance(override_entry, Mapping):
                continue
            raw_token = str(override_entry.get("token") or "").strip()
            normalized_value = str(override_entry.get("normalized") or "").strip()
            if not normalized_value and raw_token:
                normalized_value = normalize_entity_token(raw_token) or raw_token
            if normalized_value:
                override_token_map.setdefault(normalized_value, raw_token or normalized_value)

        if not job.chapters:
            filtered, skipped_info = _auto_select_relevant_chapters(extraction.chapters, file_type)
            original_count = len(extraction.chapters)
            if filtered and len(filtered) < original_count:
                extraction.chapters = filtered
                _update_metadata_for_chapter_count(extraction.metadata, len(filtered), file_type)
                threshold = _SIGNIFICANT_LENGTH_THRESHOLDS.get(file_type.lower())
                label = _chapter_label(file_type)
                qualifier = f" (< {threshold} characters)" if threshold else ""
                job.add_log(
                    f"Auto-selected {len(filtered)} of {original_count} {label} based on content{qualifier}.",
                    level="info",
                )
                if skipped_info:
                    preview_count = 5
                    preview = ", ".join(
                        f"{title or 'Untitled'} ({length})" for title, length in skipped_info[:preview_count]
                    )
                    if len(skipped_info) > preview_count:
                        preview += ", …"
                    job.add_log(
                        f"Skipped {len(skipped_info)} short {label}: {preview}",
                        level="debug",
                    )
            elif not filtered:
                job.add_log(
                    "Auto-selection did not identify usable chapters; retaining original set.",
                    level="warning",
                )

        metadata_overrides: Dict[str, Any] = dict(job.metadata_tags or {})
        if job.chapters:
            selected_chapters, chapter_metadata, diagnostics = _apply_chapter_overrides(
                extraction.chapters,
                job.chapters,
            )
            for message in diagnostics:
                job.add_log(message, level="warning")
            if selected_chapters:
                extraction.chapters = selected_chapters
                metadata_overrides.update(chapter_metadata)
                job.add_log(
                    f"Chapter overrides applied: {len(selected_chapters)} selected.",
                    level="info",
                )
                active_chapter_configs = [
                    entry for entry in job.chapters if _coerce_truthy(entry.get("enabled", True))
                ][: len(selected_chapters)]
                if job.chunks:
                    chunk_groups = _group_chunks_by_chapter(job.chunks)
            else:
                raise ValueError("No chapters were enabled in the requested job.")
        elif job.chunks:
            chunk_groups = _group_chunks_by_chapter(job.chunks)

        job.metadata_tags = _merge_metadata(extraction.metadata, metadata_overrides)

        total_characters = extraction.total_characters or calculate_text_length(extraction.combined_text)
        job.total_characters = total_characters
        job.add_log(f"Total characters: {job.total_characters:,}")

        _apply_newline_policy(extraction.chapters, job.replace_single_newlines)

        base_output_dir = _prepare_output_dir(job)
        project_root, audio_dir, subtitle_dir, metadata_dir = _prepare_project_layout(job, base_output_dir)

        if job.output_format.lower() == "m4b" and not job.merge_chapters_at_end:
            job.add_log(
                "Forcing merged output for m4b format; ignoring 'merge chapters at end' setting.",
                level="warning",
            )
            job.merge_chapters_at_end = True

        merged_required = job.merge_chapters_at_end or not job.save_chapters_separately
        audio_path: Optional[Path] = None
        audio_sink: Optional[AudioSink] = None
        if merged_required:
            audio_path = _build_output_path(audio_dir, job.original_filename, job.output_format)
            meta_for_sink = job.metadata_tags if job.metadata_tags else None
            audio_sink = _open_audio_sink(audio_path, job, sink_stack, metadata=meta_for_sink)
            subtitle_writer = _create_subtitle_writer(job, audio_path)
            job.result.audio_path = audio_path
            if subtitle_writer:
                job.result.subtitle_paths.append(subtitle_writer.path)

        chapter_dir: Optional[Path] = None
        if job.save_chapters_separately:
            chapter_dir = audio_dir / "chapters"
            chapter_dir.mkdir(parents=True, exist_ok=True)

        base_voice_spec = _job_voice_fallback(job)
        voice_cache: Dict[str, Any] = {}
        base_provider, base_voice_resolved, _, _ = resolve_voice_target(base_voice_spec)
        if base_provider == "kokoro" and base_voice_resolved and "*" not in base_voice_resolved:
            kokoro_backend = get_pipeline("kokoro")
            voice_cache[f"kokoro:{base_voice_resolved}"] = _resolve_voice(kokoro_backend, base_voice_resolved, job.use_gpu)
        processed_chars = 0
        current_time = 0.0
        total_chapters = len(extraction.chapters)
        if chunk_groups:
            chunk_groups = {
                idx: items for idx, items in chunk_groups.items() if 0 <= idx < total_chapters
            }
        job.add_log(f"Detected {total_chapters} chapter{'s' if total_chapters != 1 else ''}")
        auto_prefix_titles = getattr(job, "auto_prefix_chapter_titles", True)
        read_title_intro = getattr(job, "read_title_intro", False)
        book_intro_text = ""
        intro_provider: Optional[str] = None
        intro_voice_choice: Any = None
        intro_speed: Optional[float] = None
        intro_steps: Optional[int] = None
        if read_title_intro:
            book_intro_text = _build_title_intro_text(job.metadata_tags, job.original_filename)
            if book_intro_text:
                preview = book_intro_text if len(book_intro_text) <= 120 else f"{book_intro_text[:117]}…"
                job.add_log(f"Title intro enabled: {preview}", level="debug")

                intro_voice_spec = base_voice_spec or job.voice
                if intro_voice_spec == "__custom_mix":
                    intro_voice_spec = base_voice_spec or ""
                if not intro_voice_spec:
                    fallback_key = next(iter(voice_cache.keys()), "")
                    if fallback_key and fallback_key != "__custom_mix":
                        intro_voice_spec = fallback_key.split(":", 1)[-1]
                if not intro_voice_spec:
                    intro_voice_spec = get_default_voice("kokoro")

                if intro_voice_spec:
                    intro_provider, _, intro_voice_choice, intro_speed, intro_steps = resolve_voice_choice(
                        intro_voice_spec
                    )
            else:
                job.add_log("Title intro enabled but no usable metadata was found.", level="debug")
        intro_emitted = False

        def emit_text(
            text: str,
            *,
            voice_choice: Any,
            chapter_sink: Optional[AudioSink],
            preview_prefix: Optional[str] = None,
            split_pattern: Optional[str] = SPLIT_PATTERN,
            tts_provider: Optional[str] = None,
            speed_override: Optional[float] = None,
            supertonic_steps_override: Optional[int] = None,
        ) -> int:
            nonlocal processed_chars, current_time
            source_text = str(text or "")
            if heteronym_sentence_rules:
                source_text = _apply_heteronym_sentence_rules(source_text, heteronym_sentence_rules)
            if pronunciation_rules:
                source_text = _apply_pronunciation_rules(
                    source_text,
                    pronunciation_rules,
                    usage_counter,
                )
            try:
                normalized = normalize_for_pipeline(
                    source_text,
                    config=apostrophe_config,
                    settings=normalization_settings,
                )
            except LLMClientError as exc:
                job.add_log(f"LLM normalization failed: {exc}", level="error")
                raise
            local_segments = 0

            provider = str(tts_provider or getattr(job, "tts_provider", "kokoro") or "kokoro").strip().lower() or "kokoro"
            if provider == "supertonic":
                supertonic_pipeline = get_pipeline("supertonic")
                voice_name = _supertonic_voice_from_spec(voice_choice, getattr(job, "voice", "M1"))
                segment_iter = supertonic_pipeline(
                    normalized,
                    voice=voice_name,
                    speed=float(speed_override if speed_override is not None else job.speed),
                    split_pattern=split_pattern,
                    total_steps=int(supertonic_steps_override if supertonic_steps_override is not None else getattr(job, "supertonic_total_steps", 5)),
                )
            else:
                kokoro_backend = get_pipeline("kokoro")
                segment_iter = kokoro_backend(
                    normalized,
                    voice=voice_choice,
                    speed=float(speed_override if speed_override is not None else job.speed),
                    split_pattern=split_pattern,
                )

            try:
                for segment in segment_iter:
                    canceller()
                    graphemes_raw = getattr(segment, "graphemes", "") or ""
                    graphemes = graphemes_raw.strip()

                    audio = _to_float32(getattr(segment, "audio", None))
                    if audio.size == 0:
                        continue

                    local_segments += 1
                    if chapter_sink:
                        chapter_sink.write(audio)
                    if audio_sink:
                        audio_sink.write(audio)

                    duration = len(audio) / SAMPLE_RATE
                    processed_chars += len(graphemes)
                    job.processed_characters = processed_chars
                    if job.total_characters:
                        job.progress = min(processed_chars / job.total_characters, 0.999)
                    else:
                        job.progress = 0.0 if processed_chars == 0 else 0.999

                    preview_text = graphemes or (graphemes_raw[:80] if graphemes_raw else "[silence]")
                    prefix = f"{preview_prefix} · " if preview_prefix else ""
                    job.add_log(f"{prefix}{processed_chars:,}/{job.total_characters or '—'}: {preview_text[:80]}")

                    if subtitle_writer and audio_sink and graphemes:
                        subtitle_writer.write_entry(
                            start=current_time,
                            end=current_time + duration,
                            text=graphemes,
                        )

                    if audio_sink:
                        current_time += duration

            except OverflowError as exc:
                job.add_log(
                    f"Skipped chunk — number too large for TTS conversion: {exc}",
                    level="warning",
                )
            return local_segments

        def append_silence(
            duration_seconds: float,
            *,
            include_in_chapter: bool,
            chapter_sink: Optional[AudioSink],
        ) -> None:
            nonlocal current_time
            if duration_seconds <= 0:
                return
            samples = int(round(duration_seconds * SAMPLE_RATE))
            if samples <= 0:
                return
            silence = np.zeros(samples, dtype="float32")
            if include_in_chapter and chapter_sink:
                chapter_sink.write(silence)
            if audio_sink:
                audio_sink.write(silence)
                current_time += duration_seconds

        for idx, chapter in enumerate(extraction.chapters, start=1):
            canceller()
            raw_title = str(getattr(chapter, "title", "") or "").strip()
            spoken_title = _format_spoken_chapter_title(raw_title, idx, auto_prefix_titles)
            heading_text = spoken_title or raw_title
            chapter_display_title = heading_text or f"Chapter {idx}"
            job.add_log(f"Processing chapter {idx}/{total_chapters}: {chapter_display_title}")
            normalize_opening_caps = bool(getattr(job, "normalize_chapter_opening_caps", True))

            chapter_start_time = current_time
            chapter_override = (
                active_chapter_configs[idx - 1] if idx - 1 < len(active_chapter_configs) else None
            )
            chapter_voice_spec = _chapter_voice_spec(job, chapter_override)
            if not chapter_voice_spec:
                chapter_voice_spec = base_voice_spec

            chapter_provider, chapter_voice_resolved, chapter_speed, chapter_steps = resolve_voice_target(chapter_voice_spec)
            chapter_cache_key = f"{chapter_provider}:{chapter_voice_resolved}" if chapter_voice_resolved else chapter_provider
            if chapter_provider == "kokoro":
                voice_choice = voice_cache.get(chapter_cache_key)
                if voice_choice is None:
                    kokoro_backend = get_pipeline("kokoro")
                    voice_choice = _resolve_voice(kokoro_backend, chapter_voice_resolved, job.use_gpu)
                    voice_cache[chapter_cache_key] = voice_choice
            else:
                voice_choice = chapter_voice_resolved

            chapter_audio_path: Optional[Path] = None
            segments_emitted = 0

            with ExitStack() as chapter_sink_stack:
                chapter_sink: Optional[AudioSink] = None

                if chapter_dir is not None:
                    chapter_audio_path = _build_output_path(
                        chapter_dir,
                        f"{Path(job.original_filename).stem}_{_slugify(chapter_display_title, idx)}",
                        job.separate_chapters_format,
                    )
                    chapter_sink = _open_audio_sink(
                        chapter_audio_path,
                        job,
                        chapter_sink_stack,
                        fmt=job.separate_chapters_format,
                    )

                speak_heading = bool(heading_text)
                first_line = ""
                if chapter.text:
                    first_line = next((line.strip() for line in chapter.text.splitlines() if line.strip()), "")
                remove_heading_from_body = False
                if speak_heading and first_line:
                    if _headings_equivalent(first_line, heading_text) or (raw_title and _headings_equivalent(first_line, raw_title)):
                        remove_heading_from_body = True

                if not intro_emitted and book_intro_text:
                    intro_use_provider = intro_provider or chapter_provider
                    intro_use_voice_choice = intro_voice_choice if intro_voice_choice is not None else voice_choice
                    intro_use_speed = intro_speed if intro_speed is not None else chapter_speed
                    intro_use_steps = intro_steps if intro_steps is not None else chapter_steps
                    intro_segments = emit_text(
                        book_intro_text,
                        voice_choice=intro_use_voice_choice,
                        chapter_sink=chapter_sink,
                        preview_prefix="Book intro",
                        tts_provider=intro_use_provider,
                        speed_override=intro_use_speed,
                        supertonic_steps_override=intro_use_steps,
                    )
                    intro_emitted = True
                    if intro_segments > 0 and job.chapter_intro_delay > 0:
                        append_silence(
                            job.chapter_intro_delay,
                            include_in_chapter=True,
                            chapter_sink=chapter_sink,
                        )

                if speak_heading:
                    heading_segments = emit_text(
                        heading_text,
                        voice_choice=voice_choice,
                        chapter_sink=chapter_sink,
                        preview_prefix=f"Chapter {idx} title",
                        split_pattern=SPLIT_PATTERN,
                        tts_provider=chapter_provider,
                        speed_override=chapter_speed,
                        supertonic_steps_override=chapter_steps,
                    )
                    segments_emitted += heading_segments
                    if heading_segments > 0 and job.chapter_intro_delay > 0:
                        append_silence(
                            job.chapter_intro_delay,
                            include_in_chapter=True,
                            chapter_sink=chapter_sink,
                        )

                chunks_for_chapter = chunk_groups.get(idx - 1, []) if chunk_groups else []
                body_segments = 0
                pending_heading_strip = remove_heading_from_body
                opening_caps_pending = normalize_opening_caps
                opening_caps_logged = False
                if chunks_for_chapter:
                    job.add_log(
                        f"Emitting {len(chunks_for_chapter)} {job.chunk_level} chunks for chapter {idx}.",
                        level="debug",
                    )
                for chunk_entry in chunks_for_chapter:
                    chunk_text = _chunk_text_for_tts(chunk_entry)
                    if not chunk_text:
                        continue

                    mutated_entry = False
                    if pending_heading_strip and heading_text:
                        chunk_text, removed_heading = _strip_duplicate_heading_line(chunk_text, heading_text)
                        if not removed_heading and raw_title:
                            match = _HEADING_NUMBER_PREFIX_RE.match(raw_title)
                            if match:
                                number = match.group("number")
                                if number:
                                    chunk_text, removed_heading = _strip_duplicate_heading_line(chunk_text, number)

                        if removed_heading:
                            pending_heading_strip = False
                            chunk_entry = dict(chunk_entry)
                            chunk_entry["normalized_text"] = chunk_text
                            mutated_entry = True
                            if not chunk_text.strip():
                                continue

                    if opening_caps_pending and chunk_text:
                        normalized_text, normalized_changed = _normalize_chapter_opening_caps(chunk_text)
                        if normalized_changed:
                            if not mutated_entry:
                                chunk_entry = dict(chunk_entry)
                                mutated_entry = True
                            chunk_entry["normalized_text"] = normalized_text
                            chunk_text = normalized_text
                            if not opening_caps_logged:
                                job.add_log(
                                    f"Normalized uppercase chapter opening for chapter {idx}.",
                                    level="debug",
                                )
                                opening_caps_logged = True
                        if chunk_text.strip():
                            opening_caps_pending = False

                    chunk_voice_spec = _chunk_voice_spec(
                        job,
                        chunk_entry,
                        chapter_voice_spec or base_voice_spec,
                    )
                    if not chunk_voice_spec:
                        chunk_voice_spec = chapter_voice_spec or base_voice_spec

                    if chunk_voice_spec == chapter_voice_spec:
                        chunk_provider = chapter_provider
                        chunk_voice_resolved = chapter_voice_resolved
                        chunk_speed_use = chapter_speed
                        chunk_steps_use = chapter_steps
                        chunk_voice_choice = voice_choice
                    else:
                        chunk_provider, chunk_voice_resolved, chunk_speed_use, chunk_steps_use = resolve_voice_target(chunk_voice_spec)
                        chunk_cache_key = f"{chunk_provider}:{chunk_voice_resolved}" if chunk_voice_resolved else chunk_provider
                        if chunk_provider == "kokoro":
                            chunk_voice_choice = voice_cache.get(chunk_cache_key)
                            if chunk_voice_choice is None:
                                kokoro_backend = get_pipeline("kokoro")
                                chunk_voice_choice = _resolve_voice(
                                    kokoro_backend,
                                    chunk_voice_resolved,
                                    job.use_gpu,
                                )
                                voice_cache[chunk_cache_key] = chunk_voice_choice
                        else:
                            chunk_voice_choice = chunk_voice_resolved

                    chunk_start = current_time
                    emitted = emit_text(
                        chunk_text,
                        voice_choice=chunk_voice_choice,
                        chapter_sink=chapter_sink,
                        preview_prefix=f"Chunk {chunk_entry.get('id') or chunk_entry.get('chunk_index')}",
                        tts_provider=chunk_provider,
                        speed_override=chunk_speed_use,
                        supertonic_steps_override=chunk_steps_use,
                    )
                    if emitted <= 0:
                        continue

                    body_segments += emitted
                    segments_emitted += emitted
                    chunk_markers.append(
                        {
                            "id": chunk_entry.get("id"),
                            "chapter_index": idx - 1,
                            "chunk_index": _safe_int(
                                chunk_entry.get("chunk_index"), len(chunk_markers)
                            ),
                            "start": chunk_start,
                            "end": current_time,
                            "speaker_id": chunk_entry.get("speaker_id", "narrator"),
                            "voice": chunk_voice_spec,
                            "level": chunk_entry.get("level", job.chunk_level),
                            "characters": len(chunk_text),
                        }
                    )

                if body_segments == 0:
                    chapter_body_start = current_time
                    chapter_text = str(chapter.text or "")
                    if pending_heading_strip and heading_text:
                        chapter_text, removed_heading = _strip_duplicate_heading_line(chapter_text, heading_text)
                        if not removed_heading and raw_title:
                            match = _HEADING_NUMBER_PREFIX_RE.match(raw_title)
                            if match:
                                number = match.group("number")
                                if number:
                                    chapter_text, removed_heading = _strip_duplicate_heading_line(chapter_text, number)

                        if removed_heading:
                            pending_heading_strip = False
                    if opening_caps_pending and chapter_text:
                        normalized_body, normalized_changed = _normalize_chapter_opening_caps(chapter_text)
                        if normalized_changed:
                            chapter_text = normalized_body
                            if not opening_caps_logged:
                                job.add_log(
                                    f"Normalized uppercase chapter opening for chapter {idx}.",
                                    level="debug",
                                )
                                opening_caps_logged = True
                        if str(chapter_text or "").strip():
                            opening_caps_pending = False
                    emitted = emit_text(
                        chapter_text,
                        voice_choice=voice_choice,
                        chapter_sink=chapter_sink,
                        tts_provider=chapter_provider,
                        speed_override=chapter_speed,
                        supertonic_steps_override=chapter_steps,
                    )
                    if emitted > 0:
                        segments_emitted += emitted
                        chunk_markers.append(
                            {
                                "id": None,
                                "chapter_index": idx - 1,
                                "chunk_index": 0,
                                "start": chapter_body_start,
                                "end": current_time,
                                "speaker_id": "narrator",
                                "voice": chapter_voice_spec,
                                "level": job.chunk_level,
                                "characters": len(chapter_text or ""),
                            }
                        )
                    elif chunks_for_chapter:
                        job.add_log(
                            "No audio generated for supplied chunks; chapter text also empty.",
                            level="warning",
                        )

            chapter_end_time = current_time

            if chapter_audio_path is not None:
                job.result.artifacts[f"chapter_{idx:02d}"] = chapter_audio_path
                chapter_paths.append(chapter_audio_path)

            if segments_emitted == 0:
                job.add_log(
                    f"No audio segments were generated for chapter {idx}.",
                    level="warning",
                )
            else:
                job.add_log(f"Finished chapter {idx} with {segments_emitted} segments.")

            if (
                audio_sink
                and job.merge_chapters_at_end
                and idx < total_chapters
                and job.silence_between_chapters > 0
            ):
                append_silence(
                    job.silence_between_chapters,
                    include_in_chapter=False,
                    chapter_sink=None,
                )
                chapter_end_time = current_time

            marker = {
                "index": idx,
                "title": chapter_display_title,
                "start": chapter_start_time,
                "end": chapter_end_time,
                "voice": chapter_voice_spec,
            }
            if raw_title and raw_title != chapter_display_title:
                marker["original_title"] = raw_title
            chapter_markers.append(marker)

        if getattr(job, "read_closing_outro", True):
            outro_text = _build_outro_text(job.metadata_tags, job.original_filename)
            outro_voice_spec = base_voice_spec or job.voice
            if outro_voice_spec == "__custom_mix":
                outro_voice_spec = base_voice_spec or ""
            if not outro_voice_spec:
                fallback_key = next(iter(voice_cache.keys()), "")
                if fallback_key and fallback_key != "__custom_mix":
                    # `voice_cache` keys are internal and include provider prefixes.
                    outro_voice_spec = fallback_key.split(":", 1)[-1]
            if not outro_voice_spec:
                outro_voice_spec = get_default_voice("kokoro")

            if outro_text and outro_voice_spec:
                outro_start_time = current_time
                outro_audio_path: Optional[Path] = None
                outro_segments = 0
                outro_index = total_chapters + 1
                outro_provider, _, outro_voice_choice, outro_speed, outro_steps = resolve_voice_choice(outro_voice_spec)

                with ExitStack() as outro_sink_stack:
                    chapter_sink: Optional[AudioSink] = None
                    if chapter_dir is not None:
                        outro_audio_path = _build_output_path(
                            chapter_dir,
                            f"{Path(job.original_filename).stem}_outro",
                            job.separate_chapters_format,
                        )
                        chapter_sink = _open_audio_sink(
                            outro_audio_path,
                            job,
                            outro_sink_stack,
                            fmt=job.separate_chapters_format,
                        )

                    outro_segments = emit_text(
                        outro_text,
                        voice_choice=outro_voice_choice,
                        chapter_sink=chapter_sink,
                        preview_prefix="Outro",
                        tts_provider=outro_provider,
                        speed_override=outro_speed,
                        supertonic_steps_override=outro_steps,
                    )
                    outro_end_time = current_time

                if outro_segments > 0:
                    job.add_log(f"Appended outro sequence: {outro_text}")
                    if outro_audio_path is not None:
                        job.result.artifacts[f"chapter_{outro_index:02d}"] = outro_audio_path
                        chapter_paths.append(outro_audio_path)
                    chapter_markers.append(
                        {
                            "index": outro_index,
                            "title": "Outro",
                            "start": outro_start_time,
                            "end": outro_end_time,
                            "voice": outro_voice_spec,
                        }
                    )
                else:
                    job.add_log("No audio generated for outro sequence.", level="warning")

        if not audio_path and chapter_paths:
            job.result.audio_path = chapter_paths[0]

        metadata_payload = {
            "metadata": dict(job.metadata_tags or {}),
            "chapters": chapter_markers,
            "chunks": chunk_markers,
            "chunk_level": job.chunk_level,
            "speaker_mode": job.speaker_mode,
            "speakers": dict(getattr(job, "speakers", {}) or {}),
            "generate_epub3": job.generate_epub3,
        }

        if usage_counter:
            _record_override_usage(job, usage_counter, override_token_map)

        if metadata_dir:
            metadata_dir.mkdir(parents=True, exist_ok=True)
            metadata_file = metadata_dir / "metadata.json"
            metadata_file.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
            job.result.artifacts["metadata"] = metadata_file

        if job.generate_epub3:
            audio_asset = job.result.audio_path
            if not audio_asset and chapter_paths:
                audio_asset = chapter_paths[0]

            if audio_asset:
                try:
                    epub_root = project_root
                    epub_output_path = _build_output_path(epub_root, job.original_filename, "epub")
                    job.add_log("Generating EPUB 3 package with synchronized narration…")
                    epub_path = build_epub3_package(
                        output_path=epub_output_path,
                        book_id=job.id,
                        extraction=extraction,
                        metadata_tags=metadata_payload.get("metadata") or {},
                        chapter_markers=chapter_markers,
                        chunk_markers=chunk_markers,
                        chunks=job.chunks,
                        audio_path=audio_asset,
                        speaker_mode=job.speaker_mode,
                        cover_image_path=job.cover_image_path,
                        cover_image_mime=job.cover_image_mime,
                    )
                    job.result.epub_path = epub_path
                    job.result.artifacts["epub3"] = epub_path
                    job.add_log(f"EPUB 3 package created at {epub_path}")
                except Exception as exc:
                    job.add_log(f"Failed to generate EPUB 3 package: {exc}", level="error")
            else:
                job.add_log("Skipped EPUB 3 generation: audio output unavailable.", level="warning")

        if job.save_as_project:
            job.result.artifacts["project_root"] = project_root

        if job.status != JobStatus.CANCELLED:
            job.progress = 1.0

        audio_output_path = job.result.audio_path

    except _JobCancelled:
        job.status = JobStatus.CANCELLED
        job.add_log("Job cancelled", level="warning")
    except Exception as exc:  # pragma: no cover - defensive guard
        job.error = str(exc)
        job.status = JobStatus.FAILED
        exc_type = exc.__class__.__name__
        job.add_log(f"Job failed ({exc_type}): {exc}", level="error")

        chapter_count: Any
        if extraction is not None and hasattr(extraction, "chapters"):
            try:
                chapter_count = len(getattr(extraction, "chapters", []) or [])
            except Exception:  # pragma: no cover - defensive fallback
                chapter_count = "unavailable"
        else:
            chapter_count = "unavailable"

        try:
            chunk_group_count = len(chunk_groups)
            chunk_total = sum(len(items) for items in chunk_groups.values())
        except Exception:  # pragma: no cover - defensive fallback
            chunk_group_count = "unavailable"
            chunk_total = "unavailable"

        job.add_log(
            "Context => chunk_level=%s, chapters=%s, chunk_groups=%s, chunks=%s"
            % (job.chunk_level, chapter_count, chunk_group_count, chunk_total),
            level="debug",
        )

        first_nonempty_group = next((items for items in chunk_groups.values() if items), None)
        if first_nonempty_group:
            first_chunk = dict(first_nonempty_group[0])
            sample_text = str(first_chunk.get("text") or "")[:160].replace("\n", " ")
            job.add_log(
                "First chunk sample => id=%s, speaker=%s, chars=%s, preview=%s"
                % (
                    first_chunk.get("id") or first_chunk.get("chunk_index"),
                    first_chunk.get("speaker_id", "narrator"),
                    len(str(first_chunk.get("text") or "")),
                    sample_text,
                ),
                level="debug",
            )

        tb_lines = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
        for line in tb_lines[:20]:
            trimmed = line.rstrip()
            if trimmed:
                for snippet in trimmed.splitlines():
                    job.add_log(f"TRACE: {snippet}", level="debug")
    finally:
        sink_stack.close()
        if subtitle_writer:
            subtitle_writer.close()

        # Explicitly release the pipeline and force garbage collection to prevent
        # memory accumulation in the worker process, which can lead to host lockups.
        for p in pipelines.values():
            try:
                p.dispose()
            except Exception:
                pass
        pipelines.clear()
        pipeline = None
        gc.collect()
        try:
            import torch  # type: ignore[import-not-found]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        if (
            audio_output_path
            and job.output_format.lower() == "m4b"
            and not job.cancel_requested
            and job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}
        ):
            try:
                _embed_m4b_metadata(audio_output_path, metadata_payload, job)
            except Exception as exc:  # pragma: no cover - ensure failure propagates
                job.add_log(
                    f"Failed to embed metadata into m4b output: {exc}",
                    level="error",
                )
                raise RuntimeError(
                    f"Failed to embed metadata into m4b output: {exc}"
                ) from exc


def _load_pipeline(job: Job):
    cfg = load_config()
    disable_gpu = not job.use_gpu or not cfg.get("use_gpu", True)
    provider = str(getattr(job, "tts_provider", "kokoro") or "kokoro").strip().lower()
    if provider == "supertonic":
        return create_pipeline(
            "supertonic",
        )

    device = "cpu"
    if not disable_gpu:
        device = _select_device()
    return create_pipeline("kokoro", lang_code=job.language, device=device)


def _select_device() -> str:
    import platform

    system = platform.system()
    if system == "Darwin" and platform.processor() == "arm":
        return "mps"
    return "cuda"


def _prepare_output_dir(job: Job) -> Path:
    from platformdirs import user_desktop_dir  # type: ignore[import-not-found]

    default_output = Path(str(get_user_cache_path("outputs")))
    if job.save_mode == "Save to Desktop":
        directory = Path(user_desktop_dir())
    elif job.save_mode == "Save next to input file":
        directory = job.stored_path.parent
    elif job.save_mode == "Choose output folder" and job.output_folder:
        directory = Path(job.output_folder)
    elif job.save_mode == "Use default save location":
        directory = Path(get_user_output_path())
    else:
        directory = default_output
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _build_output_path(directory: Path, original_name: str, extension: str) -> Path:
    sanitized = _sanitize_output_stem(original_name)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{sanitized}.{extension}"


def _prepare_project_layout(job: Job, base_dir: Path) -> tuple[Path, Path, Path, Optional[Path]]:
    base_dir.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_output_stem(job.original_filename)
    folder_name = f"{_output_timestamp_token()}_{sanitized}"
    project_root = base_dir / folder_name
    project_root.mkdir(parents=True, exist_ok=True)

    if job.save_as_project:
        audio_dir = project_root / "audio"
        subtitle_dir = project_root / "subtitles"
        metadata_dir = project_root / "metadata"
        for directory in (audio_dir, subtitle_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return project_root, audio_dir, subtitle_dir, metadata_dir

    return project_root, project_root, project_root, None


def _apply_newline_policy(chapters: List[ExtractedChapter], replace_single_newlines: bool) -> None:
    if not replace_single_newlines:
        return
    newline_regex = re.compile(r"(?<!\n)\n(?!\n)")
    for chapter in chapters:
        chapter.text = newline_regex.sub(" ", chapter.text)


def _slugify(title: str, index: int) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", title.lower()).strip("_")
    if not sanitized:
        sanitized = f"chapter_{index:02d}"
    return sanitized[:80]


def _sanitize_output_stem(name: str) -> str:
    base = Path(name or "").stem
    sanitized = _OUTPUT_SANITIZE_RE.sub("_", base).strip("_")
    return sanitized or "output"


def _output_timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _open_audio_sink(
    path: Path,
    job: Job,
    stack: ExitStack,
    *,
    fmt: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> AudioSink:
    ffmpeg_cache_root = get_internal_cache_path("ffmpeg")
    platform_cache = os.path.join(ffmpeg_cache_root, sys.platform)
    os.makedirs(platform_cache, exist_ok=True)
    try:
        import static_ffmpeg.run as static_ffmpeg_run  # type: ignore

        static_ffmpeg_run.LOCK_FILE = os.path.join(ffmpeg_cache_root, "lock.file")
    except Exception:
        pass

    static_ffmpeg.add_paths(weak=True, download_dir=platform_cache)
    fmt_value = (fmt or job.output_format).lower()

    if fmt_value in {"wav", "flac"}:
        soundfile = stack.enter_context(
            sf.SoundFile(path, mode="w", samplerate=SAMPLE_RATE, channels=1, format=fmt_value.upper())
        )
        return AudioSink(write=lambda data: soundfile.write(data))

    cmd = _build_ffmpeg_command(path, fmt_value, metadata=metadata)
    process = create_process(cmd, stdin=subprocess.PIPE, text=False)

    def _finalize() -> None:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        process.wait()

    stack.callback(_finalize)

    def _write(data: np.ndarray) -> None:
        if job.cancel_requested or process.stdin is None:
            return
        process.stdin.write(data.tobytes())  # type: ignore[arg-type]

    return AudioSink(write=_write)


def _build_ffmpeg_command(path: Path, fmt: str, metadata: Optional[Dict[str, str]] = None) -> list[str]:
    base = [
        "ffmpeg",
        "-y",
        "-f",
        "f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-i",
        "pipe:0",
    ]
    if fmt == "mp3":
        base += ["-c:a", "libmp3lame", "-qscale:a", "2"]
    elif fmt == "opus":
        base += ["-c:a", "libopus", "-b:a", "24000"]
    elif fmt == "m4b":
        base += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart+use_metadata_tags"]
    else:
        base += ["-c:a", "copy"]

    if metadata:
        base.extend(_export_svc._metadata_to_ffmpeg_args(metadata))
    base.append(str(path))
    return base


def _resolve_voice(pipeline, voice_spec: str, use_gpu: bool):
    if "*" in voice_spec:
        # Voice formulas are a Kokoro-only feature (they require a pipeline that can
        # load individual Kokoro voices). When running with SuperTonic (or when the
        # pipeline is otherwise unavailable), treat the spec as a plain string and
        # allow downstream provider-specific resolution to choose a safe fallback.
        if pipeline is None or not hasattr(pipeline, "load_single_voice"):
            return voice_spec
        return get_new_voice(pipeline, voice_spec, use_gpu)
    return voice_spec


def _to_float32(audio_segment) -> np.ndarray:
    if audio_segment is None:
        return np.zeros(0, dtype="float32")

    tensor = audio_segment
    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        try:
            tensor = tensor.cpu()
        except Exception:
            pass
    if hasattr(tensor, "numpy"):
        return np.asarray(tensor.numpy(), dtype="float32").reshape(-1)
    return np.asarray(tensor, dtype="float32").reshape(-1)


def _create_subtitle_writer(job: Job, audio_path: Path):
    if job.subtitle_mode == "Disabled":
        return None

    fmt = (job.subtitle_format or "srt").lower()
    if job.subtitle_mode == "Sentence + Highlighting" and fmt == "srt":
        job.add_log("Highlighting requires ASS subtitles. Switching format.", level="warning")
        fmt = "ass"

    try:
        return create_subtitle_writer(
            audio_path.with_suffix(f".{fmt}"),
            fmt,
            job.subtitle_mode or "Line",
        )
    except (ValueError, KeyError):
        job.add_log(f"Unsupported subtitle format '{job.subtitle_format}'. Skipping.", level="warning")
        return None


def _make_canceller(job: Job) -> Callable[[], None]:
    def _cancel() -> None:
        if job.cancel_requested:
            raise _JobCancelled

    return _cancel
