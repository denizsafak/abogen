"""Core domain types for the TTS Plugin Architecture.

This module contains immutable value objects that form the core domain.
These types have zero dependencies and are used across the plugin system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from abogen.domain.enums import Language


@dataclass(frozen=True)
class AudioFormat:
    """Immutable value object representing an audio format.

    Attributes:
        mime: MIME type of the audio (e.g., "audio/wav", "audio/mpeg").
        extension: File extension (e.g., "wav", "mp3").
    """

    mime: str
    extension: str


@dataclass(frozen=True)
class Duration:
    """Immutable value object representing a time duration.

    Attributes:
        seconds: Duration in seconds.
    """

    seconds: float


@dataclass(frozen=True)
class VoiceSelection:
    """Immutable value object for voice selection. Opaque to engine.

    Attributes:
        source: Voice source identifier (e.g., "builtin", "clone").
        key: Voice key within the source.
        payload: Optional payload for clone/blend sources.
    """

    source: str
    key: str
    payload: Any = None


@dataclass(frozen=True)
class ParameterValues:
    """Immutable value object for synthesis parameters. Behaves like Mapping[str, Any].

    Attributes:
        values: Mapping of parameter names to their values.
    """

    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SynthesisRequest:
    """Immutable value object for a synthesis request.

    Attributes:
        text: Text to synthesize.
        voice: Voice selection.
        parameters: Synthesis parameters.
        format: Desired audio output format.
    """

    text: str
    voice: VoiceSelection
    parameters: ParameterValues
    format: AudioFormat


@dataclass(frozen=True)
class TokenTiming:
    """Per-token timing within a synthesized segment.

    Attributes:
        text: Token text.
        whitespace: Whitespace following the token ("" if none).
        start: Start time in seconds (relative to segment start).
        end: End time in seconds (relative to segment start).
    """

    text: str
    whitespace: str = ""
    start: float = 0.0
    end: float = 0.0


@dataclass(frozen=True)
class AudioSegment:
    """One contiguous synthesized segment (sentence-level chunk).

    Engines that split the input text (via ``split_pattern``) expose each
    chunk as its own AudioSegment so hosts can report per-sentence progress
    and build subtitles from per-token timings.

    Attributes:
        graphemes: The text this segment was synthesized from.
        audio: Raw float32 PCM audio bytes for this segment.
        sample_rate: Sample rate of ``audio``.
        tokens: Per-token timing details, when the engine provides them.
    """

    graphemes: str
    audio: bytes
    sample_rate: int
    tokens: tuple[TokenTiming, ...] = ()


@dataclass(frozen=True)
class SynthesizedAudio:
    """Immutable value object for synthesized audio result.

    Attributes:
        data: Raw audio bytes.
        format: Audio format of the result.
        duration: Duration of the audio.
        segments: Per-segment details when the engine split the text into
            sentence-level chunks (empty for engines that only produce a
            single merged result).
    """

    data: bytes
    format: AudioFormat
    duration: Duration
    segments: tuple[AudioSegment, ...] = ()


@dataclass(frozen=True)
class EngineConfig:
    """Immutable configuration of an Engine instance.

    Contains parameters that define how a particular Engine instance is
    created and that remain constant throughout the lifetime of that Engine.

    Plugin implementations may ignore fields that are not applicable to them.

    Attributes:
        device: Device to use (e.g., "cpu", "cuda:0").
        language: Language enum value. The engine converts to its internal
            format internally — callers never see engine-specific codes.
    """

    device: str = "cpu"
    language: Language = Language.EN_US
