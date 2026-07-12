"""TTS Plugin Architecture — direct utility functions.

Provides helpers that replace the former compatibility adapter by
calling the Plugin Manager directly.
"""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np

from abogen.tts_plugin.plugin_manager import get_plugin_manager


def get_voices(plugin_id: str) -> tuple[str, ...]:
    """Return the voice-id tuple for *plugin_id*.

    Uses the official Plugin Architecture: PluginManager → Engine → VoiceLister.
    First checks plugin manifest for static voice catalog.
    """
    import logging
    import tempfile
    from pathlib import Path

    from abogen.tts_plugin.host_context import HostContext
    from abogen.tts_plugin.types import EngineConfig

    manager = get_plugin_manager()
    if not manager.has_plugin(plugin_id):
        return ()

    # Check manifest for static voice catalog
    plugin_info = manager.get_plugin(plugin_id)
    if plugin_info is not None:
        manifest = plugin_info.get("manifest")
        if manifest is not None and manifest.voices is not None:
            return tuple(v.id for v in manifest.voices)

    ctx = HostContext(
        config_dir=Path(tempfile.gettempdir()),
        logger=logging.getLogger(f"abogen.utils.{plugin_id}"),
        http_client=type("_StubHttpClient", (), {
            "get": staticmethod(lambda url, **kw: None),
            "post": staticmethod(lambda url, **kw: None),
        })(),
    )

    try:
        engine = manager.create_engine(
            plugin_id,
            context=ctx,
            model_path=None,
            config=EngineConfig(device="cpu"),
        )
    except Exception:
        return ()

    try:
        from abogen.tts_plugin.capabilities import VoiceLister

        if isinstance(engine, VoiceLister):
            manifests = engine.listVoices("builtin")
            return tuple(v.id for v in manifests)
        return ()
    except Exception:
        return ()
    finally:
        engine.dispose()


def get_default_voice(plugin_id: str, fallback: str = "") -> str:
    """Return the first voice of *plugin_id*, or *fallback*."""
    voices = get_voices(plugin_id)
    return voices[0] if voices else fallback


def is_plugin_registered(plugin_id: str) -> bool:
    """Check whether *plugin_id* is loaded by the Plugin Manager."""
    return get_plugin_manager().has_plugin(plugin_id)


def resolve_voice_to_plugin(spec: str, fallback: str = "kokoro") -> str:
    """Determine which plugin owns the given voice specification.

    Resolution rules:
    1. Empty spec -> fallback
    2. Kokoro formula (contains '*' or '+') -> "kokoro"
    3. Exact voice-id match against loaded plugins -> plugin id
    4. Unknown voice -> fallback
    """
    raw = str(spec or "").strip()
    if not raw:
        return fallback

    if "*" in raw or "+" in raw:
        return "kokoro"

    upper = raw.upper()
    manager = get_plugin_manager()

    for manifest in manager.list_plugins():
        for voice_source in manifest.engine.voiceSources:
            if voice_source.type == "list" and isinstance(voice_source.config, dict):
                try:
                    engine = manager.create_engine(manifest.id)
                    try:
                        if hasattr(engine, "listVoices"):
                            voice_manifests = engine.listVoices(voice_source.id)
                            voice_ids = [v.id.upper() for v in voice_manifests]
                            if upper in voice_ids:
                                return manifest.id
                    finally:
                        engine.dispose()
                except Exception:
                    continue

    return fallback


class Pipeline:
    """Callable wrapper around Engine / EngineSession.

    Presents the same interface that old callers expect::

        pipeline = create_pipeline("kokoro", lang_code="a", device="cpu")
        for segment in pipeline(text, voice="af_nova", speed=1.0):
            audio = segment.audio
    """

    def __init__(self, engine: Any, **engine_kwargs: Any) -> None:
        self._engine = engine
        self._engine_kwargs = engine_kwargs
        self._session: Any = None

    def _ensure_session(self) -> Any:
        if self._session is None:
            self._session = self._engine.createSession()
        return self._session

    def __call__(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        split_pattern: str | None = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        from abogen.tts_plugin.types import (
            AudioFormat,
            ParameterValues,
            SynthesisRequest,
            VoiceSelection,
        )

        session = self._ensure_session()

        params: dict[str, Any] = {"speed": speed}
        if split_pattern is not None:
            params["split_pattern"] = split_pattern
        params.update(kwargs)

        request = SynthesisRequest(
            text=text,
            voice=VoiceSelection(source="builtin", key=voice),
            parameters=ParameterValues(values=params),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

        result = session.synthesize(request)
        audio_array = np.frombuffer(result.data, dtype=np.float32)

        from dataclasses import dataclass

        @dataclass
        class Segment:
            graphemes: str
            audio: np.ndarray

        yield Segment(graphemes=text, audio=audio_array)

    def dispose(self) -> None:
        if self._session is not None:
            try:
                self._session.dispose()
            except Exception:
                pass
            self._session = None

    def __del__(self) -> None:
        self.dispose()


def create_pipeline(
    plugin_id: str,
    *,
    lang_code: str = "a",
    device: str = "cpu",
) -> Pipeline:
    """Create a callable TTS pipeline via the Plugin Architecture.

    Builds a proper HostContext and EngineConfig, then delegates to the
    PluginManager to create the engine. Returns a :class:`Pipeline` whose
    ``__call__`` interface matches the callable protocol used by consumers.

    Args:
        plugin_id: Plugin identifier (e.g., "kokoro", "supertonic").
        lang_code: Language code for the engine.
        device: Device to use (e.g., "cpu", "cuda:0").

    Returns:
        A callable Pipeline instance.
    """
    import logging
    import tempfile
    from pathlib import Path

    from abogen.tts_plugin.host_context import HostContext
    from abogen.tts_plugin.types import EngineConfig

    manager = get_plugin_manager()

    ctx = HostContext(
        config_dir=Path(tempfile.gettempdir()),
        logger=logging.getLogger(f"abogen.pipeline.{plugin_id}"),
        http_client=type("_StubHttpClient", (), {
            "get": staticmethod(lambda url, **kw: None),
            "post": staticmethod(lambda url, **kw: None),
        })(),
    )

    config = EngineConfig(device=device, lang_code=lang_code)

    engine = manager.create_engine(plugin_id, context=ctx, model_path=None, config=config)
    return Pipeline(engine)
