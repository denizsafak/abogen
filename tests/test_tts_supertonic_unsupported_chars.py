import numpy as np

from abogen.tts_backends.supertonic import SupertonicBackend, SupertonicPipeline


class _DummyTTS:
    def get_voice_style(self, voice_name: str):
        return {"voice": voice_name}

    def synthesize(
        self,
        *,
        text: str,
        voice_style,
        total_steps: int,
        speed: float,
        max_chunk_length: int,
        silence_duration: float,
        verbose: bool,
    ):
        if "•" in text:
            raise ValueError("Found 1 unsupported character(s): ['•']")
        # Return 50ms of audio at 24kHz.
        sr = 24000
        audio = np.zeros(int(0.05 * sr), dtype="float32")
        return audio, 0.05


def _make_pipeline() -> SupertonicPipeline:
    pipeline = SupertonicPipeline.__new__(SupertonicPipeline)
    pipeline.sample_rate = 24000
    pipeline.total_steps = 5
    pipeline.max_chunk_length = 1000
    pipeline._tts = _DummyTTS()
    return pipeline


def _make_backend() -> SupertonicBackend:
    backend = SupertonicBackend.__new__(SupertonicBackend)
    backend._pipeline = _make_pipeline()
    return backend


def test_supertonic_pipeline_strips_unsupported_characters_and_retries():
    pipeline = _make_pipeline()

    segs = list(pipeline("Hello • world", voice="M1", speed=1.0))
    assert len(segs) == 1
    assert segs[0].graphemes == "Hello  world" or segs[0].graphemes == "Hello world"
    assert isinstance(segs[0].audio, np.ndarray)
    assert segs[0].audio.dtype == np.float32
    assert segs[0].audio.size > 0


def test_supertonic_pipeline_drops_chunk_if_only_unsupported_characters():
    pipeline = _make_pipeline()

    segs = list(pipeline("•", voice="M1", speed=1.0))
    assert segs == []


# --- SupertonicBackend tests ---


def test_backend_metadata():
    backend = _make_backend()
    meta = backend.metadata
    assert meta.id == "supertonic"
    assert meta.name == "SuperTonic"
    assert "SuperTonic" in meta.description


def test_backend_get_available_voices():
    backend = _make_backend()
    voices = backend.get_available_voices()
    assert isinstance(voices, list)
    assert "M1" in voices
    assert "F1" in voices


def test_backend_get_supported_formats():
    backend = _make_backend()
    formats = backend.get_supported_formats()
    assert "wav" in formats


def test_backend_get_info():
    backend = _make_backend()
    info = backend.get_info()
    assert info["sample_rate"] == 24000
    assert info["total_steps"] == 5
    assert isinstance(info["voices"], list)


def test_backend_call_delegates_to_pipeline():
    backend = _make_backend()
    segs = list(backend("Hello • world", voice="M1", speed=1.0))
    assert len(segs) == 1
    assert segs[0].audio.size > 0


def test_backend_synthesize_returns_wav_bytes():
    backend = _make_backend()
    wav_bytes = backend.synthesize("Hello world", voice="M1", speed=1.0)
    assert isinstance(wav_bytes, bytes)
    assert len(wav_bytes) > 0
    # WAV magic number
    assert wav_bytes[:4] == b"RIFF"
