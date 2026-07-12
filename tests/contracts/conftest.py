"""Shared fixtures and stubs for contract tests.

This module provides minimal stub implementations that satisfy the public API
for testing purposes. These stubs do NOT contain real business logic.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import pytest

from abogen.tts_plugin.engine import Engine, EngineSession
from abogen.tts_plugin.host_context import HostContext
from abogen.tts_plugin.types import (
    AudioFormat,
    Duration,
    EngineConfig,
    ParameterValues,
    SynthesisRequest,
    SynthesizedAudio,
    VoiceSelection,
)


class FakeHttpClient:
    """Stub HTTP client that satisfies the HttpClient protocol."""

    def get(self, url: str, **kwargs: object) -> object:
        return None

    def post(self, url: str, **kwargs: object) -> object:
        return None


class FakeEngineSession:
    """Stub EngineSession for testing protocol compliance."""

    def __init__(self) -> None:
        self._disposed = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Session disposed")
        return SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )

    def dispose(self) -> None:
        self._disposed = True


class FakeStreamingSession:
    """Stub EngineSession with StreamingSynthesizer capability."""

    def __init__(self) -> None:
        self._disposed = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Session disposed")
        return SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )

    def synthesizeStream(self, request: SynthesisRequest) -> Iterator[bytes]:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Session disposed")
        for i in range(3):
            yield b"\x00" * 50

    def dispose(self) -> None:
        self._disposed = True


class FakeCancelableSession:
    """Stub EngineSession with CancelableSession capability."""

    def __init__(self) -> None:
        self._disposed = False
        self._cancelled = False

    def synthesize(self, request: SynthesisRequest) -> SynthesizedAudio:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Session disposed")
        if self._cancelled:
            from abogen.tts_plugin.errors import CancelledError

            raise CancelledError("Cancelled")
        return SynthesizedAudio(
            data=b"\x00" * 100,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=1.0),
        )

    def cancel(self) -> None:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Session disposed")
        self._cancelled = True

    def dispose(self) -> None:
        self._disposed = True


class FakeEngine:
    """Stub Engine for testing protocol compliance."""

    def __init__(self, session_class: type = FakeEngineSession) -> None:
        self._disposed = False
        self._session_class = session_class

    def createSession(self) -> EngineSession:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Engine disposed")
        return self._session_class()

    def dispose(self) -> None:
        self._disposed = True


class FakeVoiceListerEngine:
    """Stub Engine that also implements VoiceLister."""

    def __init__(self) -> None:
        self._disposed = False

    def createSession(self) -> EngineSession:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Engine disposed")
        return FakeEngineSession()

    def listVoices(self, sourceId: str) -> list:
        from abogen.tts_plugin.manifest import VoiceManifest

        return [
            VoiceManifest(id="voice1", name="Voice 1", tags=("en",)),
            VoiceManifest(id="voice2", name="Voice 2", tags=("es",)),
        ]

    def dispose(self) -> None:
        self._disposed = True


class FakePreviewEngine:
    """Stub Engine that also implements PreviewGenerator."""

    def __init__(self) -> None:
        self._disposed = False

    def createSession(self) -> EngineSession:
        if self._disposed:
            from abogen.tts_plugin.errors import EngineError

            raise EngineError("Engine disposed")
        return FakeEngineSession()

    def generatePreview(self, voice: VoiceSelection, text: str) -> SynthesizedAudio:
        return SynthesizedAudio(
            data=b"\x00" * 50,
            format=AudioFormat(mime="audio/wav", extension="wav"),
            duration=Duration(seconds=0.5),
        )

    def dispose(self) -> None:
        self._disposed = True


@pytest.fixture
def fake_http_client() -> FakeHttpClient:
    return FakeHttpClient()


@pytest.fixture
def host_context(tmp_path: Path, fake_http_client: FakeHttpClient) -> HostContext:
    return HostContext(
        config_dir=tmp_path,
        logger=logging.getLogger("test"),
        http_client=fake_http_client,
    )


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def fake_session() -> FakeEngineSession:
    return FakeEngineSession()


@pytest.fixture
def default_voice() -> VoiceSelection:
    return VoiceSelection(source="builtin", key="af_nova")


@pytest.fixture
def default_format() -> AudioFormat:
    return AudioFormat(mime="audio/wav", extension="wav")


@pytest.fixture
def default_request(
    default_voice: VoiceSelection, default_format: AudioFormat
) -> SynthesisRequest:
    return SynthesisRequest(
        text="Hello, world!",
        voice=default_voice,
        parameters=ParameterValues(values={}),
        format=default_format,
    )
