"""Ports / interfaces for the conversion service.

These protocols define how the conversion service communicates with
the outside world (UI, TTS backends, voice resolvers).

The service ONLY depends on these interfaces, never on concrete
implementations (PyQt signals, Flask Job, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, runtime_checkable


class ConversionEvents(Protocol):
    """UI-specific actions the conversion service delegates back to the caller.

    Implementations:
    - PyQt: emits signals (log_updated, progress_updated, etc.)
    - WebUI: updates Job attributes (job.add_log, job.progress, etc.)
    """

    def log(self, message: str, level: str = "info") -> None:
        """Log a message to the UI."""
        ...

    def progress(self, processed: int, total: int, etr: str) -> None:
        """Update progress display."""
        ...

    def check_cancelled(self) -> None:
        """Check if conversion was cancelled.

        Should raise ConversionCancelled (or UI-specific exception)
        if cancellation is requested. Normal return means "continue".
        """
        ...


class PipelineProvider(Protocol):
    """Provides access to TTS backends (Kokoro, SuperTonic, etc.).

    Implementations:
    - PyQt: wraps self.backend (single pipeline)
    - WebUI: wraps PipelinePool (multi-provider)
    """

    def get(self, provider: str, language: str, use_gpu: bool) -> Any:
        """Get a TTS backend instance."""
        ...

    def dispose_all(self) -> None:
        """Dispose all backend resources."""
        ...


@dataclass
class ResolvedVoice:
    """A resolved voice ready for TTS synthesis."""

    provider: str
    resolved_spec: str
    voice: Any  # loaded voice tensor or name
    speed: float
    supertonic_steps: int


class VoiceResolver(Protocol):
    """Resolves voice specs into loaded voice objects.

    Implementations:
    - PyQt: wraps load_voice_cached + VoiceCache
    - WebUI: wraps resolve_voice_choice + PipelinePool + VoiceCache
    """

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        """Resolve a voice spec into a loaded voice."""
        ...


class SubtitleWriter(Protocol):
    """Writes subtitle entries to a file."""

    def open(self) -> None:
        """Open the subtitle file for writing."""
        ...

    def write_entry(self, start: float, end: float, text: str) -> None:
        """Write a single subtitle entry."""
        ...

    def close(self) -> None:
        """Close the subtitle file."""
        ...


class AudioSink(Protocol):
    """Writes audio data to a file."""

    def write(self, audio: Any) -> None:
        """Write audio samples to the sink."""
        ...

    def close(self) -> None:
        """Close the audio file."""
        ...
