"""Engine interfaces for the TTS Plugin Architecture.

This module defines the core Engine and EngineSession protocols.
These are the primary interfaces that plugin implementations must satisfy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from abogen.tts_plugin.types import SynthesisRequest, SynthesizedAudio


@runtime_checkable
class EngineSession(Protocol):
    """Protocol for a session that owns mutable execution state.

    An EngineSession is created by Engine.createSession() and owns
    mutable execution state isolated from other concurrent work.
    It is NOT thread-safe.

    Lifecycle:
        1. Created by Engine.createSession()
        2. Used for synthesis via synthesize()
        3. Disposed via dispose()

    After dispose(), all methods except dispose() raise EngineError.
    """

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        """Synthesize audio from text.

        Args:
            request: The synthesis request containing text, voice, parameters, and format.

        Returns:
            SynthesizedAudio with the synthesized audio data.

        Raises:
            EngineError: On synthesis failure. Session remains usable after error.
            EngineError: If called after dispose().
        """
        ...

    def dispose(self) -> None:
        """Release session resources.

        This method is idempotent and safe to call multiple times.
        It never raises exceptions (catches and logs internally).
        After dispose(), all methods except dispose() raise EngineError.
        """
        ...


@runtime_checkable
class Engine(Protocol):
    """Protocol for a TTS engine that creates sessions.

    An Engine is a factory for EngineSession instances. It is stateless
    and thread-safe for createSession().

    Lifecycle:
        1. Created via create_engine() (plugin contract)
        2. Sessions created via createSession()
        3. Disposed via dispose()

    Thread Safety:
        - createSession() is thread-safe and can be called from any thread.
        - dispose() must be called after all sessions are disposed.
        - Disposing engine while sessions are alive violates API contract.
    """

    def createSession(self) -> EngineSession:
        """Create a new session for synthesis.

        Returns:
            A new EngineSession instance. Ownership transfers to caller.

        Raises:
            EngineError: On failure. No partially initialized session is returned.
        """
        ...

    def dispose(self) -> None:
        """Release engine resources.

        Caller must ensure all sessions created by this engine are disposed
        before calling dispose(). Disposing an engine while any session is
        still alive violates the API contract; behavior is undefined.

        This method is idempotent and safe to call multiple times.
        It never raises exceptions (catches and logs internally).
        After dispose(), all methods except dispose() raise EngineError.
        """
        ...
