"""TTS Backend Compatibility Adapter

Provides a drop-in replacement for the old `create_backend()` function
that uses the new Plugin Architecture under the hood.

Usage:
    # Old way:
    from abogen.tts_backend_registry import create_backend
    pipeline = create_backend("kokoro", lang_code="a", device="cpu")

    # New way (same interface):
    from abogen.tts_plugin.compat import create_backend
    pipeline = create_backend("kokoro", lang_code="a", device="cpu")

The adapter wraps the new Engine/EngineSession into a callable that
matches the old TTSBackend protocol.
"""

from typing import Any, Callable, Iterable, Iterator, List, Mapping, Optional, Tuple

import numpy as np

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.plugin_manager import get_plugin_manager


class CompatBackend:
    """Compatibility wrapper that makes a new Engine look like the old TTSBackend.

    This adapter wraps the new Engine/EngineSession into a callable that
    matches the old Kokoro pipeline interface:
        pipeline(text, voice=..., speed=..., split_pattern=...) -> Iterator[Segment]
    """

    def __init__(self, engine: Engine, **engine_kwargs: Any) -> None:
        self._engine = engine
        self._engine_kwargs = engine_kwargs
        self._session: Optional[EngineSession] = None

    def _ensure_session(self) -> EngineSession:
        """Ensure we have an active session."""
        if self._session is None:
            self._session = self._engine.createSession()
        return self._session

    def __call__(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        split_pattern: str = r"\n+",
        **kwargs: Any,
    ) -> Iterator[Any]:
        """Call the backend like the old Kokoro pipeline.

        Returns an iterator of segment-like objects with .graphemes and .audio attributes.
        """
        session = self._ensure_session()

        # Build synthesis request using the new API types
        from abogen.tts_plugin.types import (
            AudioFormat,
            ParameterValues,
            SynthesisRequest,
            VoiceSelection,
        )

        # Convert voice string to VoiceSelection
        voice_selection = VoiceSelection(source="builtin", key=voice)

        # Convert speed and split_pattern to parameters
        parameters = ParameterValues(values={"speed": speed, "split_pattern": split_pattern})

        # Create request with default audio format
        request = SynthesisRequest(
            text=text,
            voice=voice_selection,
            parameters=parameters,
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

        # Synthesize
        result = session.synthesize(request)

        # Convert result to old-style segment iterator
        from dataclasses import dataclass

        @dataclass
        class Segment:
            graphemes: str
            audio: np.ndarray

        # Convert bytes back to numpy array
        audio_array = np.frombuffer(result.data, dtype=np.float32)

        # The new API returns a single audio result, but the old API returns
        # an iterator of segments. We need to split the text and audio accordingly.
        # For now, return a single segment with the full text and audio.
        yield Segment(
            graphemes=text,
            audio=audio_array,
        )

    def dispose(self) -> None:
        """Dispose the session."""
        if self._session is not None:
            try:
                self._session.dispose()
            except Exception:
                pass
            self._session = None

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        self.dispose()


def create_backend(backend_id: str, **kwargs: Any) -> Any:
    """Create a TTS backend using the new Plugin Architecture.

    This is a drop-in replacement for the old `create_backend()` function
    from `abogen.tts_backend_registry`.

    Args:
        backend_id: The backend/plugin ID (e.g., "kokoro")
        **kwargs: Arguments passed to the engine constructor

    Returns:
        A callable backend that matches the old TTSBackend protocol

    Raises:
        KeyError: If plugin_id is not found
        Exception: If engine creation fails
    """
    manager = get_plugin_manager()
    engine = manager.create_engine(backend_id, **kwargs)
    return CompatBackend(engine, **kwargs)

def get_metadata(backend_id: str) -> Any:
    """Get metadata for a specific backend using the new Plugin Architecture.

    This is a drop-in replacement for the old `get_metadata()` function
    from `abogen.tts_backend_registry`.

    Args:
        backend_id: The backend/plugin ID (e.g., "kokoro")

    Returns:
        TTSBackendMetadata-like object with voices attribute

    Raises:
        KeyError: If plugin_id is not found
    """
    from abogen.tts_backend import TTSBackendMetadata

    manager = get_plugin_manager()
    plugin_info = manager.get_plugin(backend_id)

    if plugin_info is None:
        raise KeyError(f"Unknown backend: {backend_id}")

    manifest = plugin_info["manifest"]

    # Import voice lists from plugin engines
    # This avoids creating an engine just to get the voice list
    voices: tuple[str, ...] = ()
    if backend_id == "kokoro":
        try:
            from plugins.kokoro.engine import _KOKORO_VOICES
            voices = _KOKORO_VOICES
        except ImportError:
            pass
    elif backend_id == "supertonic":
        try:
            from plugins.supertonic.engine import _SUPERTONIC_VOICES
            voices = _SUPERTONIC_VOICES
        except ImportError:
            pass

    return TTSBackendMetadata(
        id=manifest.id,
        name=manifest.name,
        description=manifest.description,
        voices=voices,
    )


def is_registered_backend(backend_id: str) -> bool:
    """Check if a backend is registered using the new Plugin Architecture.

    This is a drop-in replacement for the old `is_registered_backend()` function
    from `abogen.tts_backend_registry`.

    Args:
        backend_id: The backend/plugin ID (e.g., "kokoro")

    Returns:
        True if the plugin is loaded, False otherwise
    """
    manager = get_plugin_manager()
    return manager.has_plugin(backend_id)


def resolve_backend_for_voice(
    spec: str,
    fallback: str = "kokoro",
) -> str:
    """Determine which backend owns the given voice specification.

    This is a drop-in replacement for the old `resolve_backend_for_voice()` function
    from `abogen.tts_backend_registry`.

    Resolution rules:
    1. Empty spec -> fallback
    2. Kokoro formula (contains '*' or '+') -> "kokoro"
    3. Exact voice ID match against registered plugins -> plugin id
    4. Unknown voice -> fallback

    Args:
        spec: Voice specification (e.g., "af_nova", "M1", "af_nova*0.7+am_liam*0.3")
        fallback: Fallback backend ID if no match is found

    Returns:
        The backend/plugin ID that owns the voice
    """
    raw = str(spec or "").strip()
    if not raw:
        return fallback

    # Kokoro formula detection
    if "*" in raw or "+" in raw:
        return "kokoro"

    manager = get_plugin_manager()
    upper = raw.upper()

    # Check each plugin's voices
    for plugin_info in manager.list_plugins():
        manifest = plugin_info
        for voice_source in manifest.engine.voiceSources:
            if voice_source.type == "list" and isinstance(voice_source.config, dict):
                try:
                    engine = manager.create_engine(manifest.id)
                    if hasattr(engine, "listVoices"):
                        voice_manifests = engine.listVoices(voice_source.id)
                        voice_ids = [v.id.upper() for v in voice_manifests]
                        if upper in voice_ids:
                            engine.dispose()
                            return manifest.id
                    engine.dispose()
                except Exception:
                    continue

    return fallback


def get_default_voice(backend_id: str, fallback: str = "") -> str:
    """Return the first voice of a backend, or fallback if none.

    This is a drop-in replacement for the old `get_default_voice()` function
    from `abogen.tts_backend_registry`.

    Args:
        backend_id: The backend/plugin ID (e.g., "kokoro")
        fallback: Fallback voice if no voices are available

    Returns:
        The first voice ID, or fallback if none
    """
    try:
        metadata = get_metadata(backend_id)
        voices = metadata.voices
        return voices[0] if voices else fallback
    except KeyError:
        return fallback
