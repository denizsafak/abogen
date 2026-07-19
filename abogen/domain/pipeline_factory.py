"""Pipeline creation, caching and lifecycle management.

Provides a unified interface for creating and managing TTS pipelines
across all UI layers (WebUI, PyQt, CLI).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from abogen.domain.device import select_device
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
    language: str,
    use_gpu: bool,
) -> Any:
    """Create a TTS pipeline with proper device selection.

    Handles provider validation, GPU decision, and plugin checks.
    """
    provider = str(provider or "kokoro").strip().lower() or "kokoro"
    if not is_plugin_registered(provider):
        provider = "kokoro"

    if provider == "supertonic":
        return create_pipeline("supertonic")

    device = resolve_device(use_gpu)
    return create_pipeline("kokoro", lang_code=language, device=device)


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
        backend = pool.get("kokoro", "en", use_gpu=True)
        # ... use backend ...
        pool.dispose_all()
    """

    def __init__(self) -> None:
        self._pipelines: Dict[str, Any] = {}
        self._voice_cache_initialized = False

    def get(
        self,
        provider: str,
        language: str,
        use_gpu: bool,
        *,
        job: Any = None,
    ) -> Any:
        """Get or create a cached pipeline for the given provider.

        Args:
            provider: TTS provider name ("kokoro" or "supertonic").
            language: Language code (for kokoro).
            use_gpu: Whether GPU acceleration is requested.
            job: Optional job object for voice cache initialization.
        """
        provider = str(provider or "kokoro").strip().lower() or "kokoro"
        if not is_plugin_registered(provider):
            provider = "kokoro"

        existing = self._pipelines.get(provider)
        if existing is not None:
            return existing

        pipeline = create_pipeline_for_job(provider, language, use_gpu)
        self._pipelines[provider] = pipeline

        if provider == "kokoro" and not self._voice_cache_initialized and job is not None:
            initialize_voice_cache(job)
            self._voice_cache_initialized = True

        return pipeline

    def dispose_all(self) -> None:
        """Dispose all cached pipelines."""
        dispose_pipelines(self._pipelines)
        self._voice_cache_initialized = False
