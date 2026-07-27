"""WebUI conversion runner — thin adapter between Job and shared layer.

This module is the WebUI's adapter for the conversion system. It:
1. Builds a ConversionRequest from a Job
2. Creates an Events adapter
3. Calls run_conversion() from the shared application layer
4. Maps the ConversionResult back to Job state

All conversion logic (chapter loop, voice resolution, TTS, metadata,
subtitle writing, m4b/epub3 finalization) lives in the application layer.

Language: Job.language is Language enum. Frontend must send ISO codes.
Engine converts Language → its own format internally.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from abogen.application.conversion_config import (
    ChapterChunkConfig,
    Epub3ExportConfig,
)
from abogen.application.conversion_ports import ConversionCancelled
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_service import run_conversion
from abogen.domain.enums import (
    OutputFormat,
    SaveMode,
    SubtitleFormat,
    SubtitleMode,
)

from .service import Job, JobStatus


# ---------------------------------------------------------------------------
# Build ConversionRequest from Job
# ---------------------------------------------------------------------------


def _build_request(job: Job) -> ConversionRequest:
    """Build a ConversionRequest from a WebUI Job."""
    source_path = Path(job.stored_path) if job.stored_path else None

    return ConversionRequest(
        # Source
        source_path=source_path,
        original_filename=job.original_filename,
        # TTS Settings
        language=job.language,
        tts_provider=job.tts_provider,
        voice=job.voice,
        speed=job.speed,
        use_gpu=job.use_gpu,
        supertonic_total_steps=job.supertonic_total_steps,
        # Output Format
        output_format=_resolve_output_format(job.output_format),
        subtitle_mode=_resolve_subtitle_mode(job.subtitle_mode),
        subtitle_format=_resolve_subtitle_format(job.subtitle_format),
        max_subtitle_words=job.max_subtitle_words,
        # Save Options
        save_mode=_resolve_save_mode(job.save_mode),
        output_folder=job.output_folder,
        save_chapters_separately=job.save_chapters_separately,
        merge_chapters_at_end=job.merge_chapters_at_end,
        separate_chapters_format=_resolve_output_format(job.separate_chapters_format),
        save_as_project=job.save_as_project,
        # Timing
        silence_between_chapters=job.silence_between_chapters,
        chapter_intro_delay=job.chapter_intro_delay,
        # Content Processing
        replace_single_newlines=job.replace_single_newlines,
        read_title_intro=job.read_title_intro,
        read_closing_outro=job.read_closing_outro,
        auto_prefix_chapter_titles=job.auto_prefix_chapter_titles,
        normalize_chapter_opening_caps=job.normalize_chapter_opening_caps,
        # Metadata
        metadata_tags=job.metadata_tags or {},
        # Artifacts
        cover_image_path=job.cover_image_path,
        cover_image_mime=job.cover_image_mime,
        # Pronunciation overrides (raw data)
        pronunciation_overrides=job.pronunciation_overrides or [],
        manual_overrides=job.manual_overrides or [],
        heteronym_overrides=job.heteronym_overrides or [],
        normalization_overrides=job.normalization_overrides or None,
        # Feature configs
        epub3_export=Epub3ExportConfig(book_id=job.id) if job.generate_epub3 else None,
        chapter_chunk=ChapterChunkConfig(
            chapter_overrides=job.chapters or [],
            chunks=job.chunks or [],
            chunk_level=job.chunk_level,
            speaker_mode=job.speaker_mode,
            speakers=job.speakers or {},
        ),
    )


def _resolve_output_format(fmt: str) -> OutputFormat:
    try:
        return OutputFormat.from_str(fmt)
    except ValueError:
        return OutputFormat.WAV


def _resolve_subtitle_mode(mode: str) -> SubtitleMode:
    try:
        return SubtitleMode.from_str(mode)
    except ValueError:
        return SubtitleMode.DISABLED


def _resolve_subtitle_format(fmt: str) -> SubtitleFormat:
    try:
        return SubtitleFormat.from_str(fmt)
    except ValueError:
        return SubtitleFormat.SRT


def _resolve_save_mode(mode: str) -> SaveMode:
    normalized = mode.strip().lower()
    for m in SaveMode:
        if m.value == normalized:
            return m
    return SaveMode.SAVE_NEXT_TO_INPUT


# ---------------------------------------------------------------------------
# Apply ConversionResult back to Job
# ---------------------------------------------------------------------------


def _apply_result(job: Job, result: Any) -> None:
    """Map ConversionResult fields back to Job result and state."""
    job.result.audio_path = result.audio_path
    job.result.subtitle_paths = list(result.subtitle_paths)
    job.result.artifacts = dict(result.artifacts)
    job.result.epub_path = result.epub_path
    job.progress = 1.0


# ---------------------------------------------------------------------------
# Events adapter
# ---------------------------------------------------------------------------


class WebUIEventsAdapter:
    """Adapts Job to ConversionEvents protocol."""

    def __init__(self, job: Job):
        self._job = job

    def log(self, message: str, level: str = "info") -> None:
        self._job.add_log(message, level=level)

    def progress(self, pct: int, etr: str) -> None:
        self._job.progress = min(pct / 100.0, 0.999)
        self._job.etr_str = etr

    def check_cancelled(self) -> None:
        if self._job.cancel_requested:
            raise ConversionCancelled("Job cancelled")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_conversion_job(job: Job) -> None:
    """Run a conversion job using the shared application layer."""
    job.add_log("Preparing conversion pipeline")

    request = _build_request(job)
    events = WebUIEventsAdapter(job)

    try:
        result = run_conversion(request, events)
        _apply_result(job, result)

        if job.status != JobStatus.CANCELLED:
            job.progress = 1.0

    except ConversionCancelled:
        job.status = JobStatus.CANCELLED
        job.add_log("Job cancelled", level="warning")
    except Exception as exc:
        job.error = str(exc)
        job.status = JobStatus.FAILED
        job.add_log(f"Job failed: {exc}", level="error")
    finally:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
