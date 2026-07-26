"""Tests for domain/conversion_pipeline.py — tts_segments, emit_text_segments."""

from dataclasses import dataclass, field
from typing import Any, List, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

from abogen.domain.conversion_pipeline import tts_segments, emit_text_segments, SegmentResult


@dataclass
class FakeSegment:
    graphemes: str
    audio: Any
    tokens: list = field(default_factory=list)


@dataclass
class FakeTokenObj:
    text: str
    start_ts: float
    end_ts: float
    whitespace: str = ""


def make_backend(segments):
    """Create a mock TTS backend that yields FakeSegments."""
    def backend(text, voice=None, speed=1.0, split_pattern=None):
        for seg in segments:
            yield seg
    return backend


class TestEmitTextSegments:
    def test_yields_segments(self):
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("Hello", audio)]
        results = list(emit_text_segments(
            "Hello world",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert len(results) == 1
        assert results[0].graphemes == "Hello"
        assert results[0].duration == 1.0

    def test_skips_empty_audio(self):
        segments = [
            FakeSegment("Hello", np.ones(24000, dtype="float32")),
            FakeSegment("", np.array([], dtype="float32")),
            FakeSegment("World", np.ones(12000, dtype="float32")),
        ]
        results = list(emit_text_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert len(results) == 2
        assert results[0].graphemes == "Hello"
        assert results[1].graphemes == "World"

    def test_chunk_start_increments(self):
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("A", audio), FakeSegment("B", audio)]
        results = list(emit_text_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
            current_time=5.0,
        ))
        assert results[0].chunk_start == 5.0
        assert results[1].chunk_start == 6.0

    def test_tokens_extracted(self):
        token = FakeTokenObj("Hello", 0.0, 0.5, " ")
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("Hello", audio, [token])]
        results = list(emit_text_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
            current_time=2.0,
        ))
        assert len(results[0].tokens) == 1
        assert results[0].tokens[0]["start"] == 2.0
        assert results[0].tokens[0]["end"] == 2.5
        assert results[0].tokens[0]["text"] == "Hello"

    def test_fake_token_fallback(self):
        """When no tokens provided, creates a single FakeToken for the segment."""
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("Hello", audio)]  # No tokens
        results = list(emit_text_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert len(results[0].tokens) == 1
        assert results[0].tokens[0]["text"] == "Hello"

    def test_empty_text(self):
        results = list(emit_text_segments(
            "",
            backend=make_backend([]),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert len(results) == 0

    def test_segment_result_fields(self):
        audio = np.ones(48000, dtype="float32")
        segments = [FakeSegment("Test", audio)]
        results = list(emit_text_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        seg = results[0]
        assert isinstance(seg, SegmentResult)
        assert seg.graphemes == "Test"
        assert seg.duration == 2.0
        assert len(seg.audio) == 48000


class TestTtsSegments:
    def test_yields_segments_from_normalized_text(self):
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("Hello", audio)]
        results = list(tts_segments(
            "Already normalized text",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert len(results) == 1
        assert results[0].graphemes == "Hello"

    def test_no_normalization_performed(self):
        """tts_segments should NOT normalize — it passes text directly to backend."""
        received_texts = []

        def capture_backend(text, voice=None, speed=1.0, split_pattern=None):
            received_texts.append(text)
            yield FakeSegment("ok", np.ones(24000, dtype="float32"))

        list(tts_segments(
            "Raw unnormalized text",
            backend=capture_backend,
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
        ))
        assert received_texts[0] == "Raw unnormalized text"

    def test_chunk_start_increments(self):
        audio = np.ones(24000, dtype="float32")
        segments = [FakeSegment("A", audio), FakeSegment("B", audio)]
        results = list(tts_segments(
            "test",
            backend=make_backend(segments),
            voice="A",
            speed=1.0,
            split_pattern=r"\s+",
            current_time=10.0,
        ))
        assert results[0].chunk_start == 10.0
        assert results[1].chunk_start == 11.0


class TestSpacyPreTtsSegmentation:
    """Tests for spacy_pre_tts_segmentation()."""

    def test_disabled_when_use_spacy_false(self):
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "Hello world",
            Language.EN_US,
            "Disabled",
            use_spacy_segmentation=False,
        )
        assert segments == ["Hello world"]
        assert isinstance(split, str)

    def test_disabled_for_disabled_subtitle_mode(self):
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "Hello world",
            Language.FR,
            "Disabled",
            use_spacy_segmentation=True,
        )
        assert segments == ["Hello world"]

    def test_disabled_for_line_subtitle_mode(self):
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "Hello world",
            Language.ES,
            "Line",
            use_spacy_segmentation=True,
        )
        assert segments == ["Hello world"]

    def test_disabled_for_subtitle_input(self):
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "Hello world",
            Language.FR,
            "Sentence",
            is_subtitle_input=True,
            use_spacy_segmentation=True,
        )
        assert segments == ["Hello world"]

    def test_english_excluded_from_pre_tts(self):
        """English uses spaCy only for post-TTS subtitles, not pre-TTS."""
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "Hello world. How are you?",
            Language.EN_US,
            "Sentence",
            use_spacy_segmentation=True,
        )
        # English should return single segment (no pre-TTS segmentation)
        assert len(segments) == 1

    def test_returns_at_least_one_segment(self):
        from abogen.domain.conversion_pipeline import spacy_pre_tts_segmentation
        from abogen.domain.enums import Language

        segments, split = spacy_pre_tts_segmentation(
            "",
            Language.FR,
            "Sentence",
            use_spacy_segmentation=True,
        )
        assert len(segments) >= 1
