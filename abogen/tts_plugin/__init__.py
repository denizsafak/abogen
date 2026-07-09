"""TTS Plugin Architecture - Public API.

This package defines the frozen Plugin API for the TTS Plugin Architecture.
All public interfaces are fully defined but contain no business logic.

Public modules:
- types: Core domain value objects (AudioFormat, Duration, VoiceSelection, etc.)
- errors: Error hierarchy (EngineError and subtypes)
- manifest: Plugin manifest types (PluginManifest, EngineManifest, etc.)
- engine: Engine and EngineSession protocols
- capabilities: Optional capability interfaces (VoiceLister, PreviewGenerator, etc.)
- host_context: HostContext dataclass
- plugin: Plugin contract (create_engine function signature)
- loader: Plugin discovery and loading
- plugin_manager: Plugin management and engine creation
- compat: Backward compatibility adapter for old create_backend() API

Usage:
    from abogen.tts_plugin import (
        # Types
        AudioFormat,
        Duration,
        VoiceSelection,
        ParameterValues,
        SynthesisRequest,
        SynthesizedAudio,
        EngineConfig,
        # Errors
        EngineError,
        ModelNotFoundError,
        ModelLoadError,
        NetworkError,
        InvalidInputError,
        ConfigurationError,
        CancelledError,
        InternalError,
        # Manifest
        PluginManifest,
        EngineManifest,
        VoiceSourceManifest,
        VoiceManifest,
        ParameterManifest,
        AudioFormatManifest,
        EnumOption,
        RequirementManifest,
        GpuRequirement,
        ModelManifest,
        # Engine
        Engine,
        EngineSession,
        # Capabilities
        VoiceLister,
        PreviewGenerator,
        StreamingSynthesizer,
        CancelableSession,
        # Host Context
        HostContext,
        HttpClient,
        # Plugin Manager
        get_plugin_manager,
        reset_plugin_manager,
        # Compatibility
        create_backend,
    )
"""

from abogen.tts_plugin.capabilities import (
    CancelableSession,
    PreviewGenerator,
    StreamingSynthesizer,
    VoiceLister,
)
from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import (
    CancelledError,
    ConfigurationError,
    EngineError,
    InternalError,
    InvalidInputError,
    ModelLoadError,
    ModelNotFoundError,
    NetworkError,
)
from abogen.tts_plugin.host_context import HttpClient, HostContext
from abogen.tts_plugin.manifest import (
    AudioFormatManifest,
    EngineManifest,
    EnumOption,
    GpuRequirement,
    ModelManifest,
    ParameterManifest,
    PluginManifest,
    RequirementManifest,
    VoiceManifest,
    VoiceSourceManifest,
)
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    EngineConfig,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)

# Plugin Manager and Compatibility
from abogen.tts_plugin.plugin_manager import get_plugin_manager, reset_plugin_manager
from abogen.tts_plugin.compat import create_backend

__all__ = [
    # Types
    "AudioFormat",
    "Duration",
    "VoiceSelection",
    "ParameterValues",
    "SynthesisRequest",
    "SynthesizedAudio",
    "EngineConfig",
    # Errors
    "EngineError",
    "ModelNotFoundError",
    "ModelLoadError",
    "NetworkError",
    "InvalidInputError",
    "ConfigurationError",
    "CancelledError",
    "InternalError",
    # Manifest
    "PluginManifest",
    "EngineManifest",
    "VoiceSourceManifest",
    "VoiceManifest",
    "ParameterManifest",
    "AudioFormatManifest",
    "EnumOption",
    "RequirementManifest",
    "GpuRequirement",
    "ModelManifest",
    # Engine
    "Engine",
    "EngineSession",
    # Capabilities
    "VoiceLister",
    "PreviewGenerator",
    "StreamingSynthesizer",
    "CancelableSession",
    # Host Context
    "HostContext",
    "HttpClient",
    # Plugin Manager
    "get_plugin_manager",
    "reset_plugin_manager",
    # Compatibility
    "create_backend",
]
