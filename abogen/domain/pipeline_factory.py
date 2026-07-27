"""Pipeline creation, caching and lifecycle management.

Provides a unified interface for creating and managing TTS pipelines
across all UI layers (WebUI, PyQt, CLI).

Language handling: the engine owns the mapping between Language enum
and its internal format. Callers pass Language enum; the engine
converts internally. No engine-specific codes leak outside the engine.
"""

from __future__ import annotations

from typing import Any, Dict

from abogen.domain.device import select_device
from abogen.domain.enums import Language
from abogen.domain.voice_resolution import initialize_voice_cache
from abogen.tts_plugin.utils import create_pipeline, is_plugin_registered


def resolve_device(use_gpu: bool) -> str:
    """Determine compute device from job and global config flags."""
    from abogen.utils import load_config

    cfg = load_config()
    if use_gpu and cfg.get("use_gpu", True):
        return select_device()
    return "cpu"


def create_pipeline_for_job(
    provider: str,
    language: Language,
    use_gpu: bool,
) -> Any:
    """Create a TTS pipeline with proper device selection.

    Args:
        provider: TTS provider name ("kokoro" or "supertonic").
        language: Language enum (app-layer type, not engine-specific).
        use_gpu: Whether GPU acceleration is requested.
    """
    provider = str(provider or "kokoro").strip().lower() or "kokoro"
    if not is_plugin_registered(provider):
        provider = "kokoro"

    if provider == "supertonic":
        return create_pipeline("supertonic")

    device = resolve_device(use_gpu)
    return create_pipeline("kokoro", language=language, device=device)


def dispose_pipelines(pipelines: Dict[str, Any]) -> None:
    """Dispose all pipelines in a dict and clear it."""
    for p in pipelines.values():
        try:
            p.dispose()
        except Exception:
            pass
    pipelines.clear()


class PipelinePool:
    """Cache and manage TTS pipelines by provider.

    Usage::

        pool = PipelinePool()
        backend = pool.get("kokoro", Language.EN_US, use_gpu=True)
        # ... use backend ...
        pool.dispose_all()
    """

    def __init__(self) -> None:
        self._pipelines: Dict[str, Any] = {}
        self._voice_cache_initialized = False

    def get(
        self,
        provider: str,
        language: Language,
        use_gpu: bool,
        *,
        request: Any = None,
        events: Any = None,
    ) -> Any:
        """Get or create a cached pipeline for the given provider.

        Args:
            provider: TTS provider name ("kokoro" or "supertonic").
            language: Language enum (app-layer type).
            use_gpu: Whether GPU acceleration is requested.
            request: ConversionRequest for voice cache initialization.
            events: ConversionEvents for logging during cache init.
        """
        provider = str(provider or "kokoro").strip().lower() or "kokoro"
        if not is_plugin_registered(provider):
            provider = "kokoro"

        existing = self._pipelines.get(provider)
        if existing is not None:
            return existing

        pipeline = create_pipeline_for_job(provider, language, use_gpu)
        self._pipelines[provider] = pipeline

        if provider == "kokoro" and not self._voice_cache_initialized and request is not None:
            initialize_voice_cache(request, events=events)
            self._voice_cache_initialized = True

        return pipeline

    def dispose_all(self) -> None:
        """Dispose all cached pipelines."""
        dispose_pipelines(self._pipelines)
        self._voice_cache_initialized = False
