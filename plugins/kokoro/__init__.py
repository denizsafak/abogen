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
    VoiceManifest,
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
    voices=(
        VoiceManifest(id="af_alloy", name="Alloy", tags=("en", "female")),
        VoiceManifest(id="af_aoede", name="Aoede", tags=("en", "female")),
        VoiceManifest(id="af_bella", name="Bella", tags=("en", "female")),
        VoiceManifest(id="af_heart", name="Heart", tags=("en", "female")),
        VoiceManifest(id="af_jessica", name="Jessica", tags=("en", "female")),
        VoiceManifest(id="af_kore", name="Kore", tags=("en", "female")),
        VoiceManifest(id="af_nicole", name="Nicole", tags=("en", "female")),
        VoiceManifest(id="af_nova", name="Nova", tags=("en", "female")),
        VoiceManifest(id="af_river", name="River", tags=("en", "female")),
        VoiceManifest(id="af_sarah", name="Sarah", tags=("en", "female")),
        VoiceManifest(id="af_sky", name="Sky", tags=("en", "female")),
        VoiceManifest(id="am_adam", name="Adam", tags=("en", "male")),
        VoiceManifest(id="am_echo", name="Echo", tags=("en", "male")),
        VoiceManifest(id="am_eric", name="Eric", tags=("en", "male")),
        VoiceManifest(id="am_fenrir", name="Fenrir", tags=("en", "male")),
        VoiceManifest(id="am_liam", name="Liam", tags=("en", "male")),
        VoiceManifest(id="am_michael", name="Michael", tags=("en", "male")),
        VoiceManifest(id="am_onyx", name="Onyx", tags=("en", "male")),
        VoiceManifest(id="am_puck", name="Puck", tags=("en", "male")),
        VoiceManifest(id="am_santa", name="Santa", tags=("en", "male")),
        VoiceManifest(id="bf_alice", name="Alice", tags=("en", "female")),
        VoiceManifest(id="bf_emma", name="Emma", tags=("en", "female")),
        VoiceManifest(id="bf_isabella", name="Isabella", tags=("en", "female")),
        VoiceManifest(id="bf_lily", name="Lily", tags=("en", "female")),
        VoiceManifest(id="bm_daniel", name="Daniel", tags=("en", "male")),
        VoiceManifest(id="bm_fable", name="Fable", tags=("en", "male")),
        VoiceManifest(id="bm_george", name="George", tags=("en", "male")),
        VoiceManifest(id="bm_lewis", name="Lewis", tags=("en", "male")),
        VoiceManifest(id="ef_dora", name="Dora", tags=("es", "female")),
        VoiceManifest(id="em_alex", name="Alex", tags=("es", "male")),
        VoiceManifest(id="em_santa", name="Santa", tags=("es", "male")),
        VoiceManifest(id="ff_siwis", name="Siwis", tags=("fr", "female")),
        VoiceManifest(id="hf_alpha", name="Alpha", tags=("hi", "female")),
        VoiceManifest(id="hf_beta", name="Beta", tags=("hi", "female")),
        VoiceManifest(id="hm_omega", name="Omega", tags=("hi", "male")),
        VoiceManifest(id="hm_psi", name="Psi", tags=("hi", "male")),
        VoiceManifest(id="if_sara", name="Sara", tags=("it", "female")),
        VoiceManifest(id="im_nicola", name="Nicola", tags=("it", "male")),
        VoiceManifest(id="jf_alpha", name="Alpha", tags=("ja", "female")),
        VoiceManifest(id="jf_gongitsune", name="Gongitsune", tags=("ja", "female")),
        VoiceManifest(id="jf_nezumi", name="Nezumi", tags=("ja", "female")),
        VoiceManifest(id="jf_tebukuro", name="Tebukuro", tags=("ja", "female")),
        VoiceManifest(id="jm_kumo", name="Kumo", tags=("ja", "male")),
        VoiceManifest(id="pf_dora", name="Dora", tags=("pt", "female")),
        VoiceManifest(id="pm_alex", name="Alex", tags=("pt", "male")),
        VoiceManifest(id="pm_santa", name="Santa", tags=("pt", "male")),
        VoiceManifest(id="zf_xiaobei", name="Xiaobei", tags=("zh", "female")),
        VoiceManifest(id="zf_xiaoni", name="Xiaoni", tags=("zh", "female")),
        VoiceManifest(id="zf_xiaoxiao", name="Xiaoxiao", tags=("zh", "female")),
        VoiceManifest(id="zf_xiaoyi", name="Xiaoyi", tags=("zh", "female")),
        VoiceManifest(id="zm_yunjian", name="Yunjian", tags=("zh", "male")),
        VoiceManifest(id="zm_yunxi", name="Yunxi", tags=("zh", "male")),
        VoiceManifest(id="zm_yunxia", name="Yunxia", tags=("zh", "female")),
        VoiceManifest(id="zm_yunyang", name="Yunyang", tags=("zh", "male")),
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
            lang_code=config.lang_code,
            repo_id=repo_id,
            device=config.device,
        )

        engine = KokoroEngine(pipeline)
        return engine
    except Exception as e:
        from abogen.tts_plugin.errors import EngineError as EngineErrorClass
        raise EngineErrorClass(f"Failed to create Kokoro engine: {e}") from e
