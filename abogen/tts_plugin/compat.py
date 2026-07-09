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
