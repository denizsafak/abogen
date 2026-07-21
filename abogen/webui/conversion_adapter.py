"""WebUI adapter: Job -> ConversionRequest.

Converts a WebUI Job into a ConversionRequest that the application layer can process.
This adapter is the bridge between the WebUI layer and the application/domain layer.

The adapter is responsible for:
- Mapping Job fields to ConversionRequest fields
- Handling UI-specific state (logs, progress, cancellation)
- Providing PipelineProvider and VoiceResolver implementations

All conversions happen through this adapter — the application layer
never accesses Job directly.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_ports import ResolvedVoice


def build_conversion_request_from_job(job: Any) -> ConversionRequest:
    """Convert a WebUI Job into a ConversionRequest.

    This is the primary function that maps Job fields to ConversionRequest.
    All fields are copied — the request is independent of the Job.

    Args:
        job: WebUI Job instance

    Returns:
        ConversionRequest with all Job data mapped
    """
    return ConversionRequest(
        # Source
        source_path=job.stored_path,
        original_filename=job.original_filename,
        # TTS Settings
        language=job.language or "a",
        tts_provider=job.tts_provider or "kokoro",
        voice=job.voice or "M1",
        voice_profile=job.voice_profile,
        speed=job.speed or 1.0,
        use_gpu=job.use_gpu,
        supertonic_total_steps=job.supertonic_total_steps or 5,
        # Output Format
        output_format=job.output_format or "wav",
        subtitle_mode=job.subtitle_mode or "Disabled",
        subtitle_format=job.subtitle_format or "srt",
        max_subtitle_words=job.max_subtitle_words or 50,
        # Save Options
        save_mode=job.save_mode or "save_next_to_input",
        output_folder=job.output_folder,
        save_chapters_separately=job.save_chapters_separately,
        merge_chapters_at_end=job.merge_chapters_at_end,
        separate_chapters_format=job.separate_chapters_format or "wav",
        save_as_project=job.save_as_project,
        # Timing
        silence_between_chapters=job.silence_between_chapters or 2.0,
        chapter_intro_delay=job.chapter_intro_delay or 0.0,
        # Content Processing
        replace_single_newlines=job.replace_single_newlines,
        read_title_intro=job.read_title_intro,
        read_closing_outro=job.read_closing_outro,
        auto_prefix_chapter_titles=job.auto_prefix_chapter_titles,
        normalize_chapter_opening_caps=job.normalize_chapter_opening_caps,
        # Pronunciation / Normalization
        pronunciation_overrides=job.pronunciation_overrides or [],
        manual_overrides=job.manual_overrides or [],
        heteronym_overrides=job.heteronym_overrides or [],
        normalization_overrides=job.normalization_overrides or {},
        # Chapter/Chunk Configuration
        chapter_overrides=job.chapters or [],
        chunks=job.chunks or [],
        chunk_level=job.chunk_level or "paragraph",
        speaker_mode=job.speaker_mode or "single",
        speakers=job.speakers or {},
        # Metadata
        metadata_tags=job.metadata_tags or {},
        # Artifacts
        cover_image_path=job.cover_image_path,
        cover_image_mime=job.cover_image_mime,
        generate_epub3=job.generate_epub3,
    )


class WebJobEvents:
    """WebUI implementation of ConversionEvents protocol.

    Wraps a Job to provide logging, progress, and cancellation.
    """

    def __init__(self, job: Any):
        self._job = job

    def log(self, message: str, level: str = "info") -> None:
        """Log a message to the Job."""
        self._job.add_log(message, level=level)

    def progress(self, pct: int, etr: str) -> None:
        """Update progress on the Job."""
        self._job.progress = pct / 100.0
        self._job.etr_str = etr

    def check_cancelled(self) -> None:
        """Check if the Job was cancelled.

        Raises:
            ConversionCancelled: If cancellation was requested
        """
        if self._job.cancel_requested:
            raise ConversionCancelled("Job cancelled by user")


class ConversionCancelled(Exception):
    """Raised when conversion is cancelled."""
    pass


class WebPipelineProvider:
    """WebUI implementation of PipelineProvider protocol.

    Wraps PipelinePool to provide TTS backends.
    """

    def __init__(self, pipeline_pool: Any):
        self._pool = pipeline_pool

    def get(self, provider: str, language: str, use_gpu: bool) -> Any:
        """Get a TTS backend instance."""
        return self._pool.get(provider, language, use_gpu)

    def dispose_all(self) -> None:
        """Dispose all backend resources."""
        self._pool.dispose_all()


class WebVoiceResolver:
    """WebUI implementation of VoiceResolver protocol.

    Wraps the voice resolution logic from conversion_runner.py.
    """

    def __init__(
        self,
        resolve_fn: Callable[[str], tuple[str, str, Any, Optional[float], Optional[int]]],
    ):
        """Initialize with a voice resolution function.

        Args:
            resolve_fn: Function that takes a voice_spec and returns
                (provider, resolved_spec, voice_choice, speed, steps)
        """
        self._resolve_fn = resolve_fn

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        """Resolve a voice spec into a loaded voice."""
        provider, resolved_spec, voice, speed, steps = self._resolve_fn(voice_spec)
        return ResolvedVoice(
            provider=provider,
            resolved_spec=resolved_spec,
            voice=voice,
            speed=speed or 1.0,
            supertonic_steps=steps or 5,
        )
