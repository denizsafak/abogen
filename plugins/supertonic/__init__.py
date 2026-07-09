"""SuperTonic TTS Plugin for the TTS Plugin Architecture.

This plugin provides a SuperTonic-based TTS engine that implements the
Plugin API contract. It wraps the existing SuperTonic backend in the
new Engine/EngineSession architecture.

Exports:
    - PLUGIN_MANIFEST: PluginManifest
    - MODEL_REQUIREMENTS: list[ModelManifest]
    - create_engine: Factory function
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abogen.tts_plugin.engine import Engine
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.manifest import (
    AudioFormatManifest,
    EngineManifest,
    ModelManifest,
    ParameterManifest,
    PluginManifest,
    RequirementManifest,
    VoiceSourceManifest,
)
from abogen.tts_plugin.types import EngineConfig

from .engine import SuperTonicEngine


def _load_supertonic_pipeline(sample_rate: int = 24000, auto_download: bool = True, total_steps: int = 5) -> Any:
    """Lazy-load SuperTonic dependencies and create pipeline."""
    from abogen.tts_backends.supertonic import SupertonicPipeline

    return SupertonicPipeline(
        sample_rate=sample_rate,
        auto_download=auto_download,
        total_steps=total_steps,
    )


PLUGIN_MANIFEST = PluginManifest(
    id="supertonic",
    name="SuperTonic",
    version="0.1.0",
    api_version="1.0",
    description="SuperTonic TTS engine - fast high-quality text-to-speech",
    author="SuperTonic Team",
    capabilities=("voice_list",),
    requires=RequirementManifest(
        internet=False,
    ),
    engine=EngineManifest(
        voiceSources=(
            VoiceSourceManifest(
                id="builtin",
                name="Built-in Voices",
                type="list",
                config={"voices": "See listVoices()"},
            ),
        ),
        parameters=(
            ParameterManifest(
                id="speed",
                name="Speed",
                description="Speech speed multiplier",
                type="float",
                default=1.0,
                min=0.7,
                max=2.0,
                step=0.1,
            ),
            ParameterManifest(
                id="total_steps",
                name="Quality Steps",
                description="Inference steps (higher = better quality, slower)",
                type="int",
                default=5,
                min=2,
                max=15,
                step=1,
            ),
        ),
        audioFormats=(
            AudioFormatManifest(mime="audio/wav", extension="wav"),
        ),
    ),
)

MODEL_REQUIREMENTS: list[ModelManifest] = []


def create_engine(
    context: HostContext,
    model_path: Path | None,
    config: EngineConfig,
) -> Engine:
    """Create a SuperTonic engine instance.

    This function is the plugin entry point. It must be atomic:
    succeed fully or raise EngineError and clean up.

    Args:
        context: Host services (config dir, logger, http client).
        model_path: Resolved model path, or None for default.
        config: Engine initialization settings (device, etc.).

    Returns:
        A fully initialized SuperTonicEngine instance.

    Raises:
        EngineError: On failure. Cleans up partially created resources.
    """
    try:
        pipeline = _load_supertonic_pipeline()
        engine = SuperTonicEngine(pipeline)
        return engine
    except Exception as e:
        from abogen.tts_plugin.errors import EngineError as EngineErrorClass
        raise EngineErrorClass(f"Failed to create SuperTonic engine: {e}") from e
