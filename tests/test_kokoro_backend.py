"""Tests for KokoroBackend class."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from abogen.tts_backend import TTSBackendMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeSegment:
    graphemes: str
    audio: Any  # np.ndarray or torch-like tensor


class _FakePipeline:
    """Minimal mock for kokoro.KPipeline."""

    def __init__(self, *, lang_code: str, repo_id: str, device: str):
        self.lang_code = lang_code
        self.repo_id = repo_id
        self.device = device
        self._voices: dict[str, np.ndarray] = {}

    def __call__(
        self,
        text: str,
        *,
        voice: Any = "",
        speed: float = 1.0,
        split_pattern: str | None = None,
    ) -> Iterator[_FakeSegment]:
        yield _FakeSegment(graphemes=text, audio=np.zeros(100, dtype="float32"))

    def load_single_voice(self, name: str) -> np.ndarray:
        if name not in self._voices:
            self._voices[name] = np.ones((1, 256), dtype="float32") * 0.5
        return self._voices[name]


def _make_backend(**kwargs: Any):
    """Create KokoroBackend with mocked KPipeline."""
    with patch("abogen.tts_backends.kokoro._load_kpipeline") as load:
        load.return_value = _FakePipeline
        from abogen.tts_backends.kokoro import KokoroBackend

        return KokoroBackend(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKokoroBackendMetadata:
    def test_metadata_returns_tts_backend_metadata(self):
        backend = _make_backend(lang_code="a")
        meta = backend.metadata
        assert isinstance(meta, TTSBackendMetadata)

    def test_metadata_fields(self):
        backend = _make_backend(lang_code="a")
        meta = backend.metadata
        assert meta.id == "kokoro"
        assert meta.name == "Kokoro"
        assert "Kokoro" in meta.description


class TestKokoroBackendInit:
    def test_stores_lang_code(self):
        backend = _make_backend(lang_code="b")
        assert backend._lang_code == "b"

    def test_default_repo_id(self):
        with patch("abogen.tts_backends.kokoro._load_kpipeline") as load:
            load.return_value = _FakePipeline
            from abogen.tts_backends.kokoro import KokoroBackend

            b = KokoroBackend(lang_code="a")
            assert b._pipeline.repo_id == "hexgrad/Kokoro-82M"

    def test_custom_repo_id(self):
        backend = _make_backend(lang_code="a", repo_id="custom/repo")
        assert backend._pipeline.repo_id == "custom/repo"

    def test_default_device(self):
        backend = _make_backend(lang_code="a")
        assert backend._pipeline.device == "cpu"

    def test_custom_device(self):
        backend = _make_backend(lang_code="a", device="cuda")
        assert backend._pipeline.device == "cuda"


class TestKokoroBackendCall:
    def test_call_delegates_to_pipeline(self):
        backend = _make_backend(lang_code="a")
        results = list(backend("hello", voice="af_heart", speed=1.2, split_pattern=r"\n"))
        assert len(results) == 1
        assert results[0].graphemes == "hello"

    def test_call_returns_iterator(self):
        backend = _make_backend(lang_code="a")
        result = backend("test", voice="af_heart")
        assert hasattr(result, "__iter__")

    def test_call_with_voice_tensor(self):
        backend = _make_backend(lang_code="a")
        voice_tensor = np.ones((1, 256), dtype="float32")
        results = list(backend("test", voice=voice_tensor))
        assert len(results) == 1

    def test_call_default_speed(self):
        backend = _make_backend(lang_code="a")
        # Should not raise with default speed
        list(backend("text", voice="af_heart"))

    def test_call_default_split_pattern_is_none(self):
        backend = _make_backend(lang_code="a")
        # split_pattern defaults to None
        list(backend("text", voice="af_heart"))


class TestLoadSingleVoice:
    def test_load_single_voice_delegates(self):
        backend = _make_backend(lang_code="a")
        tensor = backend.load_single_voice("af_heart")
        assert isinstance(tensor, np.ndarray)
        assert tensor.shape == (1, 256)

    def test_load_single_voice_caches(self):
        backend = _make_backend(lang_code="a")
        t1 = backend.load_single_voice("af_heart")
        t2 = backend.load_single_voice("af_heart")
        assert t1 is t2  # same object


class TestSynthesize:
    def test_synthesize_returns_bytes(self):
        backend = _make_backend(lang_code="a")
        result = backend.synthesize("hello", voice="af_heart")
        assert isinstance(result, bytes)

    def test_synthesize_nonempty(self):
        backend = _make_backend(lang_code="a")
        result = backend.synthesize("hello", voice="af_heart")
        assert len(result) > 0

    def test_synthesize_with_speed(self):
        backend = _make_backend(lang_code="a")
        result = backend.synthesize("hello", voice="af_heart", speed=1.5)
        assert isinstance(result, bytes)

    def test_synthesize_empty_text(self):
        backend = _make_backend(lang_code="a")
        # Empty text produces no segments
        result = backend.synthesize("", voice="af_heart")
        assert isinstance(result, bytes)


class TestProtocolMethods:
    def test_get_available_voices(self):
        backend = _make_backend(lang_code="a")
        voices = backend.get_available_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0
        assert all(isinstance(v, str) for v in voices)

    def test_get_supported_formats(self):
        backend = _make_backend(lang_code="a")
        formats = backend.get_supported_formats()
        assert "pcm_float32" in formats

    def test_get_info(self):
        backend = _make_backend(lang_code="a")
        info = backend.get_info()
        assert info["id"] == "kokoro"
        assert info["name"] == "Kokoro"
        assert info["lang_code"] == "a"


class TestRegistration:
    def test_factory_creates_kokoro_backend(self):
        from abogen.tts_backends.kokoro import create_kokoro_backend, KokoroBackend

        with patch("abogen.tts_backends.kokoro._load_kpipeline") as load:
            load.return_value = _FakePipeline
            backend = create_kokoro_backend(lang_code="a")
            assert isinstance(backend, KokoroBackend)

    def test_registry_has_kokoro(self):
        import abogen.tts_backends  # noqa: F401
        from abogen.tts_backend_registry import _registry

        meta = _registry.get_metadata("kokoro")
        assert meta.id == "kokoro"
        assert meta.name == "Kokoro"

    def test_registry_factory_returns_kokoro_backend(self):
        import abogen.tts_backends  # noqa: F401
        from abogen.tts_backend_registry import _registry
        from abogen.tts_backends.kokoro import KokoroBackend

        factory = _registry._factories["kokoro"]
        with patch("abogen.tts_backends.kokoro._load_kpipeline") as load:
            load.return_value = _FakePipeline
            backend = factory(lang_code="a")
            assert isinstance(backend, KokoroBackend)
