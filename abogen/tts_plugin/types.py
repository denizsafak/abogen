"""Core domain types for the TTS Plugin Architecture.

This module contains immutable value objects that form the core domain.
These types have zero dependencies and are used across the plugin system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


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
class SynthesizedAudio:
    """Immutable value object for synthesized audio result.

    Attributes:
        data: Raw audio bytes.
        format: Audio format of the result.
        duration: Duration of the audio.
    """

    data: bytes
    format: AudioFormat
    duration: Duration


@dataclass(frozen=True)
class EngineConfig:
    """Immutable configuration of an Engine instance.

    Contains parameters that define how a particular Engine instance is
    created and that remain constant throughout the lifetime of that Engine.

    Plugin implementations may ignore fields that are not applicable to them.

    Attributes:
        device: Device to use (e.g., "cpu", "cuda:0").
        lang_code: Language code for the engine (e.g., "a" for Kokoro English).
            Plugins that do not require a language code ignore this field.
    """

    device: str = "cpu"
    lang_code: str = "a"
