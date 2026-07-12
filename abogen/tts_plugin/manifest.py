"""Plugin manifest types for the TTS Plugin Architecture.

This module contains static metadata types that describe plugins.
These types have no dependencies and are immutable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AudioFormatManifest:
    """Manifest describing an audio format.

    Attributes:
        mime: MIME type of the audio.
        extension: File extension.
    """

    mime: str
    extension: str


@dataclass(frozen=True)
class EnumOption:
    """Manifest describing an enum option for a parameter.

    Attributes:
        value: The enum value.
        label: Human-readable label.
    """

    value: str
    label: str


@dataclass(frozen=True)
class ParameterManifest:
    """Manifest describing a synthesis parameter.

    Attributes:
        id: Parameter identifier.
        name: Human-readable name.
        description: Parameter description.
        type: Parameter type ("float", "int", "string", "boolean", "enum").
        default: Default value.
        min: Minimum value (optional, for numeric types).
        max: Maximum value (optional, for numeric types).
        step: Step size (optional, for numeric types).
        options: Available options (optional, for enum type).
        unit: Unit of measurement (optional).
        group: Parameter group (optional).
    """

    id: str
    name: str
    description: str
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple[EnumOption, ...] = field(default_factory=tuple)
    unit: str | None = None
    group: str | None = None


@dataclass(frozen=True)
class VoiceManifest:
    """Manifest describing a voice.

    Attributes:
        id: Voice identifier.
        name: Human-readable name.
        tags: Voice tags (e.g., language, style).
    """

    id: str
    name: str
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VoiceSourceManifest:
    """Manifest describing a voice source.

    Attributes:
        id: Voice source identifier.
        name: Human-readable name.
        type: Source type ("list", "speaker_id", "clone", "blend", "generate", "none").
        config: Source-specific configuration.
    """

    id: str
    name: str
    type: str
    config: Any = None


@dataclass(frozen=True)
class EngineManifest:
    """Manifest describing engine capabilities.

    Attributes:
        voiceSources: Available voice sources.
        parameters: Available synthesis parameters.
        audioFormats: Supported audio formats.
    """

    voiceSources: tuple[VoiceSourceManifest, ...] = field(default_factory=tuple)
    parameters: tuple[ParameterManifest, ...] = field(default_factory=tuple)
    audioFormats: tuple[AudioFormatManifest, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GpuRequirement:
    """Manifest describing GPU requirements.

    Attributes:
        required: Whether GPU is required.
        type: GPU type (e.g., "cuda", "rocm").
        memory: Required GPU memory in GB.
    """

    required: bool = False
    type: str | None = None
    memory: float | None = None


@dataclass(frozen=True)
class RequirementManifest:
    """Manifest describing plugin requirements.

    Attributes:
        gpu: GPU requirements (optional).
        memory: Required RAM in GB (optional).
        internet: Whether internet is required (optional).
    """

    gpu: GpuRequirement | None = None
    memory: float | None = None
    internet: bool | None = None


@dataclass(frozen=True)
class ModelManifest:
    """Manifest describing a model requirement.

    Attributes:
        id: Model identifier.
        name: Human-readable name.
        size: Model size as string (e.g., "100MB", "2GB").
    """

    id: str
    name: str
    size: str


@dataclass(frozen=True)
class PluginManifest:
    """Main manifest for a TTS plugin.

    Attributes:
        id: Plugin identifier (unique).
        name: Human-readable name.
        version: Plugin version.
        api_version: API version (semver format: MAJOR.MINOR).
        description: Plugin description.
        author: Plugin author.
        capabilities: List of capability identifiers.
        requires: Plugin requirements.
        engine: Engine manifest.
        voices: Optional static voice catalog. None = not declared (use VoiceLister),
            empty tuple = explicitly no static voices, non-empty = static catalog.
    """

    id: str
    name: str
    version: str
    api_version: str
    description: str
    author: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    requires: RequirementManifest = field(default_factory=RequirementManifest)
    engine: EngineManifest = field(default_factory=EngineManifest)
    voices: tuple[VoiceManifest, ...] | None = None
