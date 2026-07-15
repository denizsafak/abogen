"""Voice loading and caching utilities.

This module provides unified voice loading with caching support for both
PyQt and WebUI interfaces.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from abogen.voice_formulas import get_new_voice


class VoiceCache:
    """Thread-safe voice cache for loaded voice tensors."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
    
    def get(self, voice_spec: str) -> Optional[Any]:
        """Get cached voice by spec."""
        return self._cache.get(voice_spec)
    
    def set(self, voice_spec: str, voice: Any) -> None:
        """Cache a loaded voice."""
        self._cache[voice_spec] = voice
    
    def contains(self, voice_spec: str) -> bool:
        """Check if voice is in cache."""
        return voice_spec in self._cache
    
    def clear(self) -> None:
        """Clear all cached voices."""
        self._cache.clear()
    
    def __contains__(self, voice_spec: str) -> bool:
        return self.contains(voice_spec)


def resolve_voice(
    voice_spec: str,
    pipeline: Any,
    use_gpu: bool,
    cache: Optional[VoiceCache] = None,
) -> Any:
    """Resolve voice spec to actual voice tensor or name.
    
    If voice_spec contains '*' (formula), loads the voice using get_new_voice.
    Otherwise, returns the voice_spec as-is (it's a voice name).
    
    Uses optional cache to avoid reloading same voice multiple times.
    
    Args:
        voice_spec: Voice specification (name or formula string with '*').
        pipeline: TTS pipeline instance for loading formula voices.
        use_gpu: Whether to use GPU for voice loading.
        cache: Optional VoiceCache instance for caching loaded voices.
        
    Returns:
        Loaded voice tensor (for formulas) or voice name string.
    """
    # Check cache first
    if cache and cache.contains(voice_spec):
        return cache.get(voice_spec)
    
    # Load voice
    if "*" in voice_spec:
        if pipeline is None:
            return voice_spec
        loaded_voice = get_new_voice(pipeline, voice_spec, use_gpu)
    else:
        loaded_voice = voice_spec
    
    # Cache it
    if cache:
        cache.set(voice_spec, loaded_voice)
    
    return loaded_voice


def load_voice_cached(
    voice_name: str,
    pipeline: Any,
    use_gpu: bool,
    cache: Optional[Dict[str, Any]] = None,
) -> Any:
    """Load voice with caching (compatibility wrapper for PyQt).
    
    This function maintains backward compatibility with the PyQt interface
    while using the unified voice loading logic.
    
    Args:
        voice_name: Voice name or formula string.
        pipeline: TTS pipeline instance.
        use_gpu: Whether to use GPU.
        cache: Optional dict to use as cache (instead of VoiceCache).
        
    Returns:
        Loaded voice tensor or voice name string.
    """
    # Use dict cache if provided (for backward compatibility)
    if cache is not None:
        if voice_name in cache:
            return cache[voice_name]
    
    # Load voice
    if "*" in voice_name:
        loaded_voice = get_new_voice(pipeline, voice_name, use_gpu)
    else:
        loaded_voice = voice_name
    
    # Cache it
    if cache is not None:
        cache[voice_name] = loaded_voice
    
    return loaded_voice
