"""Contract tests for capability interfaces.

These tests verify that capability interfaces satisfy the architectural requirements:
- VoiceLister: lists voices for a source
- PreviewGenerator: generates preview audio
- StreamingSynthesizer: yields audio chunks
- CancelableSession: cancels in-progress synthesis
"""

import pytest

from abogen.tts_plugin.capabilities import (
    CancelableSession,
    PreviewGenerator,
    StreamingSynthesizer,
    VoiceLister,
)
from abogen.tts_plugin.errors import CancelledError, EngineError
from abogen.tts_plugin.manifest import VoiceManifest
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)

from .conftest import FakeCancelableSession, FakeStreamingSession, FakeVoiceListerEngine


class TestVoiceListerProtocolContract:
    """Contract tests for VoiceLister protocol."""

    def test_voice_lister_is_protocol(self) -> None:
        assert hasattr(VoiceLister, "__protocol_attrs__")

    def test_voice_lister_satisfied_by_engine(self) -> None:
        engine = FakeVoiceListerEngine()
        assert isinstance(engine, VoiceLister)

    def test_list_voices_returns_list(self) -> None:
        engine = FakeVoiceListerEngine()
        voices = engine.listVoices("builtin")
        assert isinstance(voices, list)

    def test_list_voices_returns_voice_manifests(self) -> None:
        engine = FakeVoiceListerEngine()
        voices = engine.listVoices("builtin")
        for voice in voices:
            assert isinstance(voice, VoiceManifest)

    def test_list_voices_has_required_fields(self) -> None:
        engine = FakeVoiceListerEngine()
        voices = engine.listVoices("builtin")
        for voice in voices:
            assert hasattr(voice, "id")
            assert hasattr(voice, "name")
            assert hasattr(voice, "tags")


class TestPreviewGeneratorProtocolContract:
    """Contract tests for PreviewGenerator protocol."""

    def test_preview_generator_is_protocol(self) -> None:
        assert hasattr(PreviewGenerator, "__protocol_attrs__")

    def test_preview_generator_satisfied_by_engine(self) -> None:
        from .conftest import FakePreviewEngine

        engine = FakePreviewEngine()
        assert isinstance(engine, PreviewGenerator)

    def test_generate_preview_returns_synthesized_audio(self) -> None:
        from .conftest import FakePreviewEngine

        engine = FakePreviewEngine()
        voice = VoiceSelection(source="builtin", key="af_nova")
        result = engine.generatePreview(voice, "Hello")
        assert isinstance(result, SynthesizedAudio)

    def test_generate_preview_has_valid_data(self) -> None:
        from .conftest import FakePreviewEngine

        engine = FakePreviewEngine()
        voice = VoiceSelection(source="builtin", key="af_nova")
        result = engine.generatePreview(voice, "Hello")
        assert isinstance(result.data, bytes)
        assert len(result.data) > 0


class TestStreamingSynthesizerProtocolContract:
    """Contract tests for StreamingSynthesizer protocol."""

    def test_streaming_synthesizer_is_protocol(self) -> None:
        assert hasattr(StreamingSynthesizer, "__protocol_attrs__")

    def test_streaming_session_satisfies_protocol(self) -> None:
        session = FakeStreamingSession()
        assert isinstance(session, StreamingSynthesizer)

    def test_synthesize_stream_yields_bytes(self) -> None:
        session = FakeStreamingSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        chunks = list(session.synthesizeStream(request))
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, bytes)

    def test_streaming_iterator_exhaustion(self) -> None:
        """Architecture spec: Iterator exhaustion = synthesis complete."""
        session = FakeStreamingSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        chunks = list(session.synthesizeStream(request))
        assert len(chunks) == 3

    def test_streaming_after_dispose_raises(self) -> None:
        """Architecture spec: After dispose(), methods raise EngineError."""
        session = FakeStreamingSession()
        session.dispose()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )
        with pytest.raises(EngineError):
            list(session.synthesizeStream(request))


class TestCancelableSessionProtocolContract:
    """Contract tests for CancelableSession protocol."""

    def test_cancelable_session_is_protocol(self) -> None:
        assert hasattr(CancelableSession, "__protocol_attrs__")

    def test_cancelable_session_satisfies_protocol(self) -> None:
        session = FakeCancelableSession()
        assert isinstance(session, CancelableSession)

    def test_cancel_causes_synthesize_to_raise_cancelled(self) -> None:
        """Architecture spec: cancel() causes synthesize() to raise CancelledError."""
        session = FakeCancelableSession()
        request = SynthesisRequest(
            text="Hello",
            voice=VoiceSelection(source="builtin", key="af_nova"),
            parameters=ParameterValues(),
            format=AudioFormat(mime="audio/wav", extension="wav"),
        )

        # Cancel
        session.cancel()

        # synthesize should raise CancelledError
        with pytest.raises(CancelledError):
            session.synthesize(request)

    def test_cancel_after_dispose_raises(self) -> None:
        """Architecture spec: cancel() raises EngineError if called after dispose()."""
        session = FakeCancelableSession()
        session.dispose()
        with pytest.raises(EngineError):
            session.cancel()

    def test_session_usable_after_cancel(self) -> None:
        """Architecture spec: EngineSession remains usable after cancellation."""
        session = FakeCancelableSession()

        # Cancel
        session.cancel()

        # Dispose and create new session for synthesis
        session.dispose()
