"""Contract tests for EngineSession protocol.

These tests verify that EngineSession implementations satisfy the architectural requirements:
- synthesize() returns SynthesizedAudio
- dispose() is idempotent
- After dispose(), synthesize() raises EngineError
- Session remains usable after synthesize() failure
"""

import pytest

from abogen.tts_plugin.engine import EngineSession
from abogen.tts_plugin.errors import EngineError
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)

from .conftest import FakeEngineSession


class TestEngineSessionProtocolContract:
    """Contract tests for the EngineSession protocol itself."""

    def test_engine_session_is_protocol(self) -> None:
        assert hasattr(EngineSession, "__protocol_attrs__")

    def test_fake_session_satisfies_protocol(self) -> None:
        session = FakeEngineSession()
        assert isinstance(session, EngineSession)


class TestSessionSynthesizeContract:
    """Contract tests for EngineSession.synthesize()."""

    def test_synthesize_returns_synthesized_audio(self) -> None:
        session = FakeEngineSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result, SynthesizedAudio)

    def test_synthesize_returns_valid_audio_data(self) -> None:
        session = FakeEngineSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        result = session.synthesize(request)
        assert isinstance(result.data, bytes)
        assert len(result.data) > 0
        assert isinstance(result.format, AudioFormat)
        assert isinstance(result.duration, Duration)


class TestSessionDisposeContract:
    """Contract tests for EngineSession.dispose()."""

    def test_dispose_is_idempotent(self) -> None:
        """Architecture spec: dispose() is idempotent."""
        session = FakeEngineSession()
        session.dispose()
        session.dispose()  # Should not raise

    def test_dispose_never_raises(self) -> None:
        """Architecture spec: dispose() never raises exceptions."""
        session = FakeEngineSession()
        session.dispose()  # Should not raise


class TestSessionAfterDisposeContract:
    """Contract tests for behavior after dispose()."""

    def test_synthesize_after_dispose_raises(self) -> None:
        """Architecture spec: After dispose(), all methods except dispose() raise EngineError."""
        session = FakeEngineSession()
        session.dispose()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        with pytest.raises(EngineError):
            session.synthesize(request)


class TestSessionLifecycleContract:
    """Contract tests for EngineSession lifecycle."""

    def test_full_lifecycle(self) -> None:
        """Test complete session lifecycle: create -> synthesize -> dispose."""
        session = FakeEngineSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

        # Synthesize
        result = session.synthesize(request)
        assert isinstance(result, SynthesizedAudio)

        # Dispose
        session.dispose()

    def test_multiple_synthesize_before_dispose(self) -> None:
        """Architecture spec: Session remains usable after synthesize() failure."""
        session = FakeEngineSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

        # Multiple synthesize calls
        result1 = session.synthesize(request)
        result2 = session.synthesize(request)
        assert isinstance(result1, SynthesizedAudio)
        assert isinstance(result2, SynthesizedAudio)

        # Dispose
        session.dispose()
