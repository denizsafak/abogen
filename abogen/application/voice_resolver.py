"""AppVoiceResolver — voice resolution inside the application layer.

Resolves voice specs into loaded voices using profiles, pipeline pool,
and voice cache. Replaces UI-specific resolvers (WebUIVoiceResolver,
PyQtVoiceResolver) with a single app-layer implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from abogen.application.conversion_ports import ResolvedVoice, VoiceResolver
from abogen.application.conversion_request import ConversionRequest
from abogen.domain.pipeline_factory import PipelinePool
from abogen.domain.voice_loader import VoiceCache, resolve_voice
from abogen.domain.voice_utils import resolve_voice_target


class AppVoiceResolver:
    """App-layer implementation of VoiceResolver protocol.

    Uses ConversionRequest instead of Job. Loads profiles, creates
    resolver internally — UIs don't need to manage this.
    """

    def __init__(
        self,
        request: ConversionRequest,
        normalized_profiles: Dict[str, Dict[str, Any]],
        pool: PipelinePool,
        cache: VoiceCache,
    ):
        self._request = request
        self._profiles = normalized_profiles
        self._cache = cache
        self._pool = pool

    def resolve(self, voice_spec: str) -> ResolvedVoice:
        """Resolve a voice spec into a loaded voice."""
        provider, resolved, speed, steps = resolve_voice_target(
            voice_spec,
            self._profiles,
            job_voice=self._request.voice,
            job_tts_provider=self._request.tts_provider,
            job_supertonic_total_steps=self._request.supertonic_total_steps,
            job_speed=self._request.speed,
        )

        cache_key = f"{provider}:{resolved}" if resolved else provider
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ResolvedVoice(
                provider=provider,
                resolved_spec=resolved,
                voice=cached,
                speed=speed,
                supertonic_steps=steps or 0,
            )

        if provider == "kokoro":
            kokoro_backend = self._pool.get(
                "kokoro", self._request.language, self._request.use_gpu,
            )
            loaded = resolve_voice(
                resolved, kokoro_backend, self._request.use_gpu, cache=self._cache,
            )
        else:
            loaded = resolved

        self._cache.set(cache_key, loaded)
        return ResolvedVoice(
            provider=provider,
            resolved_spec=resolved,
            voice=loaded,
            speed=speed,
            supertonic_steps=steps or 0,
        )
