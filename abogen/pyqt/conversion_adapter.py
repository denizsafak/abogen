"""PyQt adapter: ConversionThread -> ConversionRequest.

Converts a PyQt ConversionThread into a ConversionRequest that the application layer can process.
This adapter is the bridge between the PyQt layer and the application/domain layer.

The adapter is responsible for:
- Mapping ConversionThread fields to ConversionRequest fields
- Handling UI-specific state (signals, dialogs, cancellation)
- Providing PipelineProvider and VoiceResolver implementations

Subtitle file/timestamp special paths remain in ConversionThread.run() early return.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_ports import ResolvedVoice


def build_conversion_request_from_thread(thread: Any) -> ConversionRequest:
    """Convert a PyQt ConversionThread into a ConversionRequest.

    This is the primary function that maps thread fields to ConversionRequest.
    All fields are copied — the request is independent of the thread.

    Args:
        thread: PyQt ConversionThread instance

    Returns:
        ConversionRequest with all thread data mapped
    """
    # Determine source path
    source_path = None
    is_direct_text = getattr(thread, "is_direct_text", False)
    if not is_direct_text and thread.file_name:
        source_path = Path(thread.file_name)

    # Determine original filename
    original_filename = ""
    if getattr(thread, "from_queue", False):
        base_path = getattr(thread, "save_base_path", None) or thread.file_name
    else:
        base_path = getattr(thread, "display_path", None) or thread.file_name

    if base_path:
        original_filename = os.path.basename(base_path)

    # Determine output folder
    output_folder = None
    if thread.output_folder:
        output_folder = Path(thread.output_folder)

    return ConversionRequest(
        # Source
        source_path=source_path,
        direct_text=thread.file_name if is_direct_text else None,
        original_filename=original_filename,
        # TTS Settings
        language=thread.lang_code or "a",
        tts_provider="kokoro",  # PyQt uses Kokoro by default
        voice=thread.voice or "M1",
        voice_profile=getattr(thread, "voice_profile", None),
        speed=thread.speed or 1.0,
        use_gpu=thread.use_gpu,
        supertonic_total_steps=getattr(thread, "supertonic_total_steps", None) or 5,
        # Output Format
        output_format=thread.output_format or "wav",
        subtitle_mode=thread.subtitle_mode or "Disabled",
        subtitle_format=getattr(thread, "subtitle_format", "srt"),
        max_subtitle_words=getattr(thread, "max_subtitle_words", None) or 50,
        # Save Options
        save_mode=thread.save_option or "save_next_to_input",
        output_folder=output_folder,
        save_chapters_separately=getattr(thread, "save_chapters_separately", False),
        merge_chapters_at_end=getattr(thread, "merge_chapters_at_end", True),
        separate_chapters_format=getattr(thread, "separate_chapters_format", "wav"),
        save_as_project=getattr(thread, "save_as_project", False),
        # Timing
        silence_between_chapters=getattr(thread, "silence_duration", None) or 2.0,
        chapter_intro_delay=getattr(thread, "chapter_intro_delay", None) or 0.0,
        # Content Processing
        replace_single_newlines=getattr(thread, "replace_single_newlines", False),
        read_title_intro=getattr(thread, "read_title_intro", False),
        read_closing_outro=getattr(thread, "read_closing_outro", True),
        auto_prefix_chapter_titles=getattr(thread, "auto_prefix_chapter_titles", True),
        normalize_chapter_opening_caps=getattr(thread, "normalize_chapter_opening_caps", False),
        # Pronunciation / Normalization
        pronunciation_overrides=getattr(thread, "pronunciation_overrides", []) or [],
        manual_overrides=getattr(thread, "manual_overrides", []) or [],
        heteronym_overrides=getattr(thread, "heteronym_overrides", []) or [],
        normalization_overrides=getattr(thread, "normalization_overrides", None),
        # Chapter/Chunk Configuration
        chapter_overrides=[],  # PyQt doesn't use chapter overrides from GUI
        chunks=[],  # PyQt doesn't use chunks from GUI
        chunk_level="paragraph",
        speaker_mode="single",
        speakers={},
        # Metadata
        metadata_tags=getattr(thread, "metadata_tags", {}) or {},
        # Artifacts
        cover_image_path=getattr(thread, "cover_image_path", None),
        cover_image_mime=getattr(thread, "cover_image_mime", None),
        generate_epub3=getattr(thread, "generate_epub3", False),
    )


class PyQtEvents:
    """PyQt implementation of ConversionEvents protocol.

    Wraps a ConversionThread to provide logging, progress, and cancellation.
    """

    def __init__(self, thread: Any):
        self._thread = thread

    def log(self, message: str, level: str = "info") -> None:
        """Log a message via signal."""
        self._thread.log_updated.emit((message, _level_to_color(level)))

    def progress(self, pct: int, etr: str) -> None:
        """Update progress via signal."""
        self._thread.progress_updated.emit(pct, etr)

    def check_cancelled(self) -> None:
        """Check if conversion was cancelled.

        Raises:
            ConversionCancelled: If cancellation was requested
        """
        if self._thread.cancel_requested:
            raise ConversionCancelled("Conversion cancelled by user")


class ConversionCancelled(Exception):
    """Raised when conversion is cancelled."""
    pass


class PyQtPipelineProvider:
    """PyQt implementation of PipelineProvider protocol.

    Wraps the existing backend from ConversionThread.
    """

    def __init__(self, backend: Any):
        self._backend = backend

    def get(self, provider: str, language: str, use_gpu: bool) -> Any:
        """Get a TTS backend instance.

        For PyQt, this returns the pre-initialized backend.
        """
        return self._backend

    def dispose_all(self) -> None:
        """Dispose all backend resources."""
        pass  # PyQt manages backend lifecycle in thread


class PyQtVoiceResolver:
    """PyQt implementation of VoiceResolver protocol.

    Wraps load_voice_cached from the ConversionThread.
    """

    def __init__(self, thread: Any):
        self._thread = thread

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        """Resolve a voice spec into a loaded voice."""
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        # Use thread's load_voice_cached method
        loaded_voice = self._thread.load_voice_cached(voice_spec, self._thread.backend)

        return ResolvedVoice(
            provider="kokoro",
            resolved_spec=voice_spec,
            voice=loaded_voice,
            speed=self._thread.speed,
            supertonic_steps=getattr(self._thread, "supertonic_total_steps", 5),
        )


def _level_to_color(level: str) -> str:
    """Map log level to PyQt color string."""
    colors = {
        "info": "grey",
        "warning": "orange",
        "error": "red",
        "debug": "grey",
    }
    return colors.get(level, "grey")
