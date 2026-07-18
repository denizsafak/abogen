from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import gc
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import numpy as np
import soundfile as sf
import static_ffmpeg

from abogen.tts_plugin.utils import is_plugin_registered
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
from abogen.text_extractor import extract_from_path
from abogen.utils import (
    calculate_text_length,
    create_process,
    get_internal_cache_path,
    get_user_cache_path,
    get_user_output_path,
    load_config,
)
from abogen.tts_plugin.utils import create_pipeline
from abogen.voice_formulas import get_new_voice
from abogen.voice_profiles import load_profiles, normalize_profile_entry
from abogen.llm_client import LLMClientError
from abogen.infrastructure.subtitle_writer import create_subtitle_writer
from abogen.domain.chapter_titles import (
    simplify_heading_text as _simplify_heading_text,
    headings_equivalent as _headings_equivalent,
    strip_duplicate_heading_line as _strip_duplicate_heading_line,
    normalize_caps_word as _normalize_caps_word,
    normalize_chapter_opening_caps as _normalize_chapter_opening_caps,
    format_spoken_chapter_title as _format_spoken_chapter_title,
    apply_chapter_text_transforms as _apply_chapter_text_transforms,
    _HEADING_NUMBER_PREFIX_RE,
)
from abogen.domain.metadata_helpers import (
    normalize_metadata_map as _normalize_metadata_map,
    format_author_sentence as _format_author_sentence,
    ensure_sentence as _ensure_sentence,
    normalize_series_number as _normalize_series_number,
    extract_series_metadata as _extract_series_metadata,
    format_series_sentence as _format_series_sentence,
)
from abogen.domain.title_builder import (
    build_title_intro_text as _build_title_intro_text,
    build_outro_text as _build_outro_text,
)
from abogen.domain.file_type import (
    infer_file_type as _infer_file_type,
    auto_select_relevant_chapters as _auto_select_relevant_chapters,
    chapter_label as _chapter_label,
    update_metadata_for_chapter_count as _update_metadata_for_chapter_count,
    _SIGNIFICANT_LENGTH_THRESHOLDS,
)
from abogen.domain.pronunciation import (
    compile_pronunciation_rules as _compile_pronunciation_rules,
    compile_heteronym_sentence_rules as _compile_heteronym_sentence_rules,
    apply_pronunciation_rules as _apply_pronunciation_rules,
    merge_pronunciation_overrides as _merge_pronunciation_overrides,
)
from abogen.domain.normalization import prepare_text_for_tts
from abogen.domain.voice_resolution import (
    spec_to_voice_ids as _spec_to_voice_ids,
    job_voice_fallback as _job_voice_fallback,
    collect_required_voice_ids as _collect_required_voice_ids,
    initialize_voice_cache as _initialize_voice_cache,
    chapter_voice_spec as _chapter_voice_spec,
    chunk_voice_spec as _chunk_voice_spec,
    resolve_fallback_voice_spec as _resolve_fallback_voice_spec,
)
from abogen.domain.chapter_overrides import apply_chapter_overrides as _apply_chapter_overrides
from abogen.domain.metadata_merge import merge_metadata as _merge_metadata
from abogen.domain.chunk_utils import (
    safe_int as _safe_int,
    group_chunks_by_chapter as _group_chunks_by_chapter,
    record_override_usage as _record_override_usage,
    chunk_text_for_tts as _chunk_text_for_tts,
)
from abogen.domain.voice_utils import (
    supertonic_voice_from_spec as _supertonic_voice_from_spec,
    split_speaker_reference as _split_speaker_reference,
    formula_from_kokoro_entry as _formula_from_kokoro_entry,
    infer_provider_from_spec as _infer_provider_from_spec,
    coerce_truthy as _coerce_truthy,
)
from abogen.domain.output_paths import (
    slugify as _slugify,
    sanitize_output_stem as _sanitize_output_stem,
    output_timestamp_token as _output_timestamp_token,
    build_output_path as _build_output_path,
    apply_newline_policy as _apply_newline_policy,
    resolve_output_directory as _resolve_output_directory,
    resolve_project_layout as _resolve_project_layout,
)
from abogen.domain.device import select_device as _select_device
from abogen.domain.split_pattern import get_split_pattern
from abogen.domain.progress import ProgressTracker, calc_etr_str
from abogen.domain.subtitle_generation import process_subtitle_tokens
from abogen.domain.audio_helpers import (
    build_ffmpeg_command as _build_ffmpeg_command,
    to_float32 as _to_float32,
)
from abogen.domain.audio_buffer import (
    create_silence as _create_silence,
    normalize_audio as _normalize_audio,
    SAMPLE_RATE,
)


from .service import Job, JobStatus


_export_svc = ExportService()

SPLIT_PATTERN = r"\n+"  # Kept for backward compatibility; prefer get_split_pattern()
SAMPLE_RATE = 24000


class _FakeToken:
    """Minimal token stub for languages without per-word token support."""

    def __init__(self, text: str, start: float, end: float):
        self.text = text
        self.start_ts = start
        self.end_ts = end
        self.whitespace = ""


class _JobCancelled(Exception):
    """Raised internally to abort a conversion when the client cancels."""


@dataclass
class AudioSink:
    write: Callable[[np.ndarray], None]


_APOSTROPHE_CONFIG = ApostropheConfig()


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

    # Compute language-aware split pattern once for the entire job
    job_split_pattern = get_split_pattern(
        str(job.language or "a"),
        str(job.subtitle_mode or "Disabled"),
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
        etr_start_time = time.time()
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

                intro_voice_spec = _resolve_fallback_voice_spec(
                    base_voice_spec, job.voice, list(voice_cache.keys())
                )

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
            split_pattern: Optional[str] = None,
            tts_provider: Optional[str] = None,
            speed_override: Optional[float] = None,
            supertonic_steps_override: Optional[int] = None,
        ) -> int:
            nonlocal processed_chars, current_time
            if split_pattern is None:
                split_pattern = job_split_pattern
            source_text = str(text or "")
            try:
                normalized = prepare_text_for_tts(
                    source_text,
                    heteronym_rules=heteronym_sentence_rules,
                    pronunciation_rules=pronunciation_rules,
                    normalization_overrides=getattr(job, "normalization_overrides", None),
                    usage_counter=usage_counter,
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
                # Accumulate tokens for subtitle processing (token-level grouping)
                accumulated_tokens: List[dict] = []

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
                    chunk_start = current_time
                    processed_chars += len(graphemes)
                    job.processed_characters = processed_chars
                    if job.total_characters:
                        job.progress = min(processed_chars / job.total_characters, 0.999)
                        job.etr_str = calc_etr_str(
                            time.time() - etr_start_time,
                            processed_chars,
                            job.total_characters,
                        )
                    else:
                        job.progress = 0.0 if processed_chars == 0 else 0.999

                    preview_text = graphemes or (graphemes_raw[:80] if graphemes_raw else "[silence]")
                    prefix = f"{preview_prefix} · " if preview_prefix else ""
                    job.add_log(f"{prefix}{processed_chars:,}/{job.total_characters or '—'}: {preview_text[:80]}")

                    # Accumulate tokens from this segment for subtitle processing
                    if subtitle_writer and audio_sink:
                        tokens_list = getattr(segment, "tokens", [])

                        # Fallback for languages without token support: create a single token
                        if not tokens_list and graphemes:
                            tokens_list = [_FakeToken(graphemes, 0, duration)]

                        for tok in tokens_list:
                            accumulated_tokens.append({
                                "start": chunk_start + (tok.start_ts or 0),
                                "end": chunk_start + (tok.end_ts or 0),
                                "text": tok.text,
                                "whitespace": tok.whitespace,
                            })

                    if audio_sink:
                        current_time += duration

                # Flush accumulated tokens through process_subtitle_tokens
                if subtitle_writer and audio_sink and accumulated_tokens:
                    _use_spacy = job.subtitle_mode not in ("Disabled", "Line")
                    new_entries: List[tuple] = []
                    process_subtitle_tokens(
                        accumulated_tokens,
                        new_entries,
                        job.max_subtitle_words,
                        job.subtitle_mode,
                        job.language,
                        use_spacy_segmentation=_use_spacy,
                        fallback_end_time=current_time,
                    )
                    for start, end, text in new_entries:
                        subtitle_writer.write_entry(start=start, end=end, text=text)

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
            silence = _create_silence(duration_seconds)
            if silence.size == 0:
                return
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
                    chunk_text, heading_removed, caps_changed = _apply_chapter_text_transforms(
                        chunk_text,
                        heading_text=heading_text,
                        raw_title=raw_title,
                        strip_heading=pending_heading_strip,
                        normalize_caps=opening_caps_pending,
                    )
                    if heading_removed:
                        pending_heading_strip = False
                        chunk_entry = dict(chunk_entry)
                        chunk_entry["normalized_text"] = chunk_text
                        mutated_entry = True
                        if not chunk_text.strip():
                            continue
                    if caps_changed:
                        if not mutated_entry:
                            chunk_entry = dict(chunk_entry)
                        chunk_entry["normalized_text"] = chunk_text
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
                    chapter_text, heading_removed, caps_changed = _apply_chapter_text_transforms(
                        chapter_text,
                        heading_text=heading_text,
                        raw_title=raw_title,
                        strip_heading=pending_heading_strip,
                        normalize_caps=opening_caps_pending,
                    )
                    if heading_removed:
                        pending_heading_strip = False
                    if caps_changed:
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
            outro_voice_spec = _resolve_fallback_voice_spec(
                base_voice_spec, job.voice, list(voice_cache.keys())
            )

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
                cover_path = None
                if job.cover_image_path:
                    candidate = Path(job.cover_image_path)
                    if candidate.exists():
                        cover_path = candidate
                
                _export_svc.embed_m4b_metadata(
                    audio_path=audio_output_path,
                    metadata=metadata_payload.get("metadata") or {},
                    chapters=metadata_payload.get("chapters") or [],
                    cover_path=cover_path,
                    cover_mime=job.cover_image_mime,
                    log_callback=lambda msg, level="info": job.add_log(msg, level=level),
                )
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


def _prepare_output_dir(job: Job) -> Path:
    from platformdirs import user_desktop_dir  # type: ignore[import-not-found]

    default_output = Path(str(get_user_cache_path("outputs")))
    directory = _resolve_output_directory(
        save_mode=job.save_mode,
        stored_path=job.stored_path,
        output_folder=getattr(job, "output_folder", None),
        desktop_dir=Path(user_desktop_dir()),
        user_output_path=Path(get_user_output_path()),
        user_cache_outputs=default_output,
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _prepare_project_layout(job: Job, base_dir: Path) -> tuple[Path, Path, Path, Optional[Path]]:
    base_dir.mkdir(parents=True, exist_ok=True)
    return _resolve_project_layout(
        original_filename=job.original_filename,
        save_as_project=job.save_as_project,
        base_dir=base_dir,
    )


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


def _resolve_voice(pipeline, voice_spec: str, use_gpu: bool):
    if "*" in voice_spec:
        if pipeline is None or not hasattr(pipeline, "load_single_voice"):
            return voice_spec
        return get_new_voice(pipeline, voice_spec, use_gpu)
    return voice_spec


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
