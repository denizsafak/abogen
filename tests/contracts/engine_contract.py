"""Base contract tests for Engine implementations.

Any new TTS plugin must inherit from these classes to verify
it satisfies the Engine/EngineSession protocol.

Usage:
    from tests.contracts.engine_contract import EngineContractMixin

    class TestMyEngine(EngineContractMixin):
        @pytest.fixture
        def engine(self):
            return create_my_engine()
"""

from __future__ import annotations

import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.types import (
    AudioFormat,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)


class EngineContractMixin:
    """Base contract tests for Engine implementations.

    Subclasses must define a module-level ``engine`` fixture returning
    a fully initialized Engine instance. The tests below will use it
    via pytest's standard fixture resolution.
    """

    def _req(self, text: str = "Hello", voice: str | None = None) -> SynthesisRequest:
        return SynthesisRequest(
            text=text,
            voice=VoiceSelection(source="builtin", key=voice or "default"),
            parameters=ParameterValues(values={}),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

    # ── Engine protocol ──────────────────────────────────────

    def test_engine_satisfies_protocol(self, engine: Engine) -> None:
        assert isinstance(engine, Engine)

    def test_create_session_returns_session(self, engine: Engine) -> None:
        session = engine.createSession()
        assert isinstance(session, EngineSession)
        session.dispose()

    def test_create_session_returns_new_instances(self, engine: Engine) -> None:
        s1 = engine.createSession()
        s2 = engine.createSession()
        assert s1 is not s2
        s1.dispose()
        s2.dispose()

    def test_dispose_is_idempotent(self, engine: Engine) -> None:
        engine.dispose()
        engine.dispose()

    def test_create_session_after_dispose_raises(self, engine: Engine) -> None:
        engine.dispose()
        with pytest.raises(EngineError):
            engine.createSession()

    # ── Session protocol ─────────────────────────────────────

    def test_session_satisfies_protocol(self, engine: Engine) -> None:
        session = engine.createSession()
        assert isinstance(session, EngineSession)
        session.dispose()
        engine.dispose()

    def test_session_synthesize_returns_audio(self, engine: Engine) -> None:
        session = engine.createSession()
        result = session.synthesize(self._req())
        assert isinstance(result, SynthesizedAudio)
        assert isinstance(result.data, bytes)
        assert len(result.data) > 0
        session.dispose()
        engine.dispose()

    def test_session_dispose_is_idempotent(self, engine: Engine) -> None:
        session = engine.createSession()
        session.dispose()
        session.dispose()
        engine.dispose()

    def test_session_synthesize_after_dispose_raises(self, engine: Engine) -> None:
        session = engine.createSession()
        session.dispose()
        with pytest.raises(EngineError):
            session.synthesize(self._req())
        engine.dispose()

    def test_session_multiple_synthesize(self, engine: Engine) -> None:
        session = engine.createSession()
        r1 = session.synthesize(self._req())
        r2 = session.synthesize(self._req())
        assert isinstance(r1.data, bytes)
        assert isinstance(r2.data, bytes)
        session.dispose()
        engine.dispose()

    # ── Lifecycle ────────────────────────────────────────────

    def test_full_lifecycle(self, engine: Engine) -> None:
        s1 = engine.createSession()
        s2 = engine.createSession()
        s1.synthesize(self._req())
        s2.synthesize(self._req())
        s1.dispose()
        s2.dispose()
        engine.dispose()
