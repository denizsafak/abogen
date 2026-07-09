"""Kokoro TTS Plugin for the TTS Plugin Architecture.

This plugin provides a Kokoro-based TTS engine that implements the
Plugin API contract. It wraps the existing Kokoro backend in the
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

from .engine import KokoroEngine


def _load_kpipeline() -> Any:
    """Lazy-load Kokoro dependencies."""
    from kokoro import KPipeline  # type: ignore[import-not-found]
    return KPipeline


PLUGIN_MANIFEST = PluginManifest(
    id="kokoro",
    name="Kokoro",
    version="0.9.4",
    api_version="1.0",
    description="Kokoro TTS engine - high quality multilingual text-to-speech",
    author="Kokoro Team",
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
                min=0.5,
                max=2.0,
                step=0.1,
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
    """Create a Kokoro engine instance.

    This function is the plugin entry point. It must be atomic:
    succeed fully or raise EngineError and clean up.

    Args:
        context: Host services (config dir, logger, http client).
        model_path: Resolved model path, or None for default.
        config: Engine initialization settings (device, etc.).

    Returns:
        A fully initialized KokoroEngine instance.

    Raises:
        EngineError: On failure. Cleans up partially created resources.
    """
    try:
        KPipeline = _load_kpipeline()

        # Determine repo_id from model_path or use default
        repo_id = "hexgrad/Kokoro-82M"
        if model_path is not None:
            # If a specific model path is provided, use it as repo_id
            repo_id = str(model_path)

        pipeline = KPipeline(
            lang_code="a",  # Default language code
            repo_id=repo_id,
            device=config.device,
        )

        engine = KokoroEngine(pipeline, lang_code="a")
        return engine
    except Exception as e:
        from abogen.tts_plugin.errors import EngineError as EngineErrorClass
        raise EngineErrorClass(f"Failed to create Kokoro engine: {e}") from e
