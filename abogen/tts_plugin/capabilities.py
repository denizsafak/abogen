"""Capability interfaces for the TTS Plugin Architecture.

This module defines optional capability interfaces that engines can implement.
Capabilities are additive; implementing new capabilities doesn't break old plugins.
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from abogen.tts_plugin.manifest import VoiceManifest
from abogen.tts_plugin.types import SynthesisRequest, SynthesizedAudio, VoiceSelection


@runtime_checkable
class VoiceLister(Protocol):
    """Protocol for listing available voices.

    Engines that support voice listing should implement this interface.
    """

    def listVoices(self, sourceId: str) -> list[VoiceManifest]:
        """List available voices for a given source.

        Args:
            sourceId: The voice source identifier.

        Returns:
            List of VoiceManifest describing available voices.

        Raises:
            EngineError: On failure.
        """
        ...


@runtime_checkable
class PreviewGenerator(Protocol):
    """Protocol for generating voice previews.

    Engines that support voice preview should implement this interface.
    """

    def generatePreview(self, voice: VoiceSelection, text: str) -> SynthesizedAudio:
        """Generate a preview audio for a voice.

        Args:
            voice: Voice selection for the preview.
            text: Text to use for the preview.

        Returns:
            SynthesizedAudio with the preview audio data.

        Raises:
            EngineError: On failure.
        """
        ...


@runtime_checkable
class StreamingSynthesizer(Protocol):
    """Protocol for streaming synthesis.

    Optional capability of EngineSession, not Engine.
    Engines that support streaming synthesis should implement this interface.
    """

    def synthesizeStream(self, request: SynthesisRequest) -> Iterator[bytes]:
        """Synthesize audio in streaming mode.

        Args:
            request: The synthesis request.

        Yields:
            Audio chunks as they become available.

        Raises:
            CancelledError: If cancel() is called during iteration.
            EngineError: On synthesis failure.
        """
        ...
        # This is a generator function; implementation will use yield
        yield b""  # pragma: no cover


@runtime_checkable
class CancelableSession(Protocol):
    """Protocol for cancellation support.

    Optional capability for engines that support cancellation.
    cancel() causes synthesize() to raise CancelledError.
    """

    def cancel(self) -> None:
        """Cancel in-progress synthesis.

        After cancellation, synthesize() raises CancelledError.
        The session remains usable after cancellation.

        Raises:
            EngineError: If called after dispose().
        """
        ...
