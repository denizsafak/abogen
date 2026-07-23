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

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from abogen.application.conversion_config import (
    ChapterChunkConfig,
    Epub3ExportConfig,
    PronunciationConfig,
    WordSubstitutionConfig,
)
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_ports import ConversionCancelled, ResolvedVoice


def build_conversion_request_from_job(job: Any) -> ConversionRequest:
    """Convert a WebUI Job into a ConversionRequest.

    This is the primary function that maps Job fields to ConversionRequest.
    All fields are copied — the request is independent of the Job.

    Args:
        job: WebUI Job instance

    Returns:
        ConversionRequest with all Job data mapped
    """
    # Build word substitution config
    word_substitution = None
    if getattr(job, "word_substitutions_enabled", False):
        word_substitution = WordSubstitutionConfig(
            substitutions_list=getattr(job, "word_substitutions_list", ""),
            case_sensitive=getattr(job, "case_sensitive_substitutions", False),
            replace_caps=getattr(job, "replace_all_caps", False),
            replace_numerals=getattr(job, "replace_numerals", False),
            fix_punctuation=getattr(job, "fix_nonstandard_punctuation", False),
        )

    # Build pronunciation config
    pronunciation = None
    pron_overrides = job.pronunciation_overrides or []
    manual_overrides = job.manual_overrides or []
    heteronym_overrides = job.heteronym_overrides or []
    norm_overrides = job.normalization_overrides or None
    if pron_overrides or manual_overrides or heteronym_overrides or norm_overrides:
        pronunciation = PronunciationConfig(
            pronunciation_overrides=pron_overrides,
            manual_overrides=manual_overrides,
            heteronym_overrides=heteronym_overrides,
            normalization_overrides=norm_overrides,
        )

    # Build chapter/chunk config
    chapter_chunk = ChapterChunkConfig(
        chapter_overrides=job.chapters or [],
        chunks=job.chunks or [],
        chunk_level=job.chunk_level,
        speaker_mode=job.speaker_mode,
        speakers=job.speakers or {},
    )

    # Build epub3 config
    epub3_export = None
    if getattr(job, "generate_epub3", False):
        epub3_export = Epub3ExportConfig(
            book_id=getattr(job, "id", ""),
        )

    return ConversionRequest(
        # Source
        source_path=Path(job.stored_path) if job.stored_path else None,
        original_filename=job.original_filename,
        # TTS Settings
        language=job.language,
        tts_provider=job.tts_provider,
        voice=job.voice,
        voice_profile=job.voice_profile,
        speed=job.speed,
        use_gpu=job.use_gpu,
        supertonic_total_steps=job.supertonic_total_steps,
        # Output Format
        output_format=job.output_format,
        subtitle_mode=job.subtitle_mode,
        subtitle_format=job.subtitle_format,
        max_subtitle_words=job.max_subtitle_words,
        # Save Options
        save_mode=job.save_mode,
        output_folder=Path(job.output_folder) if job.output_folder else None,
        save_chapters_separately=job.save_chapters_separately,
        merge_chapters_at_end=job.merge_chapters_at_end,
        separate_chapters_format=job.separate_chapters_format,
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
        cover_image_path=Path(job.cover_image_path) if job.cover_image_path else None,
        cover_image_mime=job.cover_image_mime,
        # Feature configs
        word_substitution=word_substitution,
        pronunciation=pronunciation,
        chapter_chunk=chapter_chunk,
        epub3_export=epub3_export,
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
