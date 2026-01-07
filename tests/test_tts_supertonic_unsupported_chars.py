import numpy as np

from abogen.tts_supertonic import SupertonicPipeline


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


def test_supertonic_pipeline_strips_unsupported_characters_and_retries():
    # Avoid importing/initializing real supertonic by manually constructing the pipeline.
    pipeline = SupertonicPipeline.__new__(SupertonicPipeline)
    pipeline.sample_rate = 24000
    pipeline.total_steps = 5
    pipeline.max_chunk_length = 1000
    pipeline._tts = _DummyTTS()

    segs = list(pipeline("Hello • world", voice="M1", speed=1.0))
    assert len(segs) == 1
    assert segs[0].graphemes == "Hello  world" or segs[0].graphemes == "Hello world"
    assert isinstance(segs[0].audio, np.ndarray)
    assert segs[0].audio.dtype == np.float32
    assert segs[0].audio.size > 0


def test_supertonic_pipeline_drops_chunk_if_only_unsupported_characters():
    pipeline = SupertonicPipeline.__new__(SupertonicPipeline)
    pipeline.sample_rate = 24000
    pipeline.total_steps = 5
    pipeline.max_chunk_length = 1000
    pipeline._tts = _DummyTTS()

    segs = list(pipeline("•", voice="M1", speed=1.0))
    assert segs == []
