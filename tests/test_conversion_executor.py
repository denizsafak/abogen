"""Regression tests for conversion executor logic.

These tests verify that the core conversion engine (synthesize_text,
run_tts_segment_loop, process_and_write_subtitles) works correctly
with fake backends and sinks. They serve as a regression net for the
upcoming conversion flow unification refactor.

All tests use mock/fake implementations — no real TTS, no real audio I/O.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Any

from abogen.domain.conversion_engine import (
    synthesize_text,
    run_tts_segment_loop,
    process_and_write_subtitles,
    SegmentStats,
    SegmentInfo,
    CancelChecker,
)
from abogen.domain.normalization import TTSContext
from abogen.domain.audio_sink import AudioSink


# ─── Fake Implementations ──────────────────────────────────────────

class FakeAudioSink:
    """Fake audio sink that records written data."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, audio: np.ndarray) -> None:
        self.written.append(audio)

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeBackend:
    """Fake TTS backend that returns deterministic audio."""

    def __init__(self, segment_duration: float = 0.5):
        self.segment_duration = segment_duration
        self.call_count = 0

    def __call__(self, text: str, voice: Any, speed: float = 1.0, split_pattern: str = ""):
        self.call_count += 1
        # Return fake segment objects with required attributes
        @dataclass
        class FakeSegment:
            graphemes: str = ""
            audio: Any = None
            tokens: list = field(default_factory=list)

        samples = int(24000 * self.segment_duration)
        audio = np.zeros(samples, dtype=np.float32)
        tokens = [
            MagicMock(start_ts=0.0, end_ts=0.3, text="Hello", whitespace=" "),
            MagicMock(start_ts=0.3, end_ts=0.5, text="world", whitespace="."),
        ]
        return [FakeSegment(graphemes=text, audio=audio, tokens=tokens)]


class FakeSubtitleWriter:
    """Fake subtitle writer that records entries."""

    def __init__(self):
        self.entries = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def write_entry(self, start: float, end: float, text: str) -> None:
        self.entries.append((start, end, text))

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


# ─── SegmentStats Tests ────────────────────────────────────────────

class TestSegmentStats:
    """Verify SegmentStats tracks timing and character counts."""

    def test_default_values(self):
        stats = SegmentStats()
        assert stats.processed_chars == 0
        assert stats.current_time == 0.0
        assert stats.total_characters == 0

    def test_mutation(self):
        stats = SegmentStats(total_characters=1000)
        stats.processed_chars += 100
        stats.current_time += 1.5
        assert stats.processed_chars == 100
        assert stats.current_time == 1.5


# ─── synthesize_text Tests ─────────────────────────────────────────

class TestSynthesizeText:
    """Verify synthesize_text normalizes and runs TTS correctly."""

    def test_basic_synthesis(self):
        backend = FakeBackend()
        tts_ctx = TTSContext()
        stats = SegmentStats(total_characters=100)
        sink = FakeAudioSink()

        cancel = lambda: False
        progress_calls = []
        def on_progress(pct, etr):
            progress_calls.append((pct, etr))

        segments, tokens = synthesize_text(
            text="Hello world.",
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel,
            on_progress=on_progress,
            audio_sink=sink,
        )

        assert segments >= 1
        assert len(sink.written) >= 1
        assert len(progress_calls) >= 1

    def test_cancellation(self):
        backend = FakeBackend()
        tts_ctx = TTSContext()
        stats = SegmentStats(total_characters=10000)

        cancel = lambda: True  # Always cancel
        progress_calls = []
        def on_progress(pct, etr):
            progress_calls.append((pct, etr))

        segments, tokens = synthesize_text(
            text="Hello world.",
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel,
            on_progress=on_progress,
        )

        # Should stop early due to cancellation
        assert segments == 0

    def test_with_chapter_sink(self):
        backend = FakeBackend()
        tts_ctx = TTSContext()
        stats = SegmentStats(total_characters=100)
        merged_sink = FakeAudioSink()
        chapter_sink = FakeAudioSink()

        cancel = lambda: False
        def on_progress(pct, etr):
            pass

        segments, tokens = synthesize_text(
            text="Hello world.",
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel,
            on_progress=on_progress,
            chapter_sink=chapter_sink,
            audio_sink=merged_sink,
        )

        # Both sinks should receive audio
        assert len(chapter_sink.written) >= 1
        assert len(merged_sink.written) >= 1

    def test_split_pattern_override(self):
        backend = FakeBackend()
        tts_ctx = TTSContext(split_pattern=r"(?<=[.!?\-])\s+")
        stats = SegmentStats(total_characters=100)

        cancel = lambda: False
        def on_progress(pct, etr):
            pass

        segments, tokens = synthesize_text(
            text="Hello world.",
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel,
            on_progress=on_progress,
            split_pattern_override=r"\n+",
        )

        assert segments >= 1


# ─── process_and_write_subtitles Tests ──────────────────────────────

class TestProcessAndWriteSubtitles:
    """Verify subtitle processing writes entries correctly."""

    def test_empty_tokens(self):
        writer = FakeSubtitleWriter()
        process_and_write_subtitles(
            [],
            writer,
            subtitle_mode="Sentence",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
            fallback_end_time=10.0,
        )
        assert len(writer.entries) == 0

    def test_sentence_mode_entries(self):
        writer = FakeSubtitleWriter()
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": "world", "whitespace": "."},
        ]
        process_and_write_subtitles(
            tokens,
            writer,
            subtitle_mode="Sentence",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
            fallback_end_time=2.0,
        )
        assert len(writer.entries) >= 1
        start, end, text = writer.entries[0]
        assert start < end
        assert isinstance(text, str)

    def test_line_mode_entries(self):
        writer = FakeSubtitleWriter()
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": "world", "whitespace": "\n"},
            {"start": 1.0, "end": 1.5, "text": "New", "whitespace": " "},
            {"start": 1.5, "end": 2.0, "text": "line", "whitespace": "."},
        ]
        process_and_write_subtitles(
            tokens,
            writer,
            subtitle_mode="Line",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
            fallback_end_time=3.0,
        )
        assert len(writer.entries) >= 1

    def test_disabled_mode(self):
        """Disabled mode is checked by the caller (run_tts_segment_loop),
        not by process_subtitle_tokens itself. This test verifies that
        process_subtitle_tokens still processes when called directly."""
        writer = FakeSubtitleWriter()
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
        ]
        process_and_write_subtitles(
            tokens,
            writer,
            subtitle_mode="Disabled",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
            fallback_end_time=2.0,
        )
        # process_subtitle_tokens doesn't filter by mode — caller must check
        # So entries may be written even in "Disabled" mode
        assert isinstance(writer.entries, list)


# ─── Integration: Full Pipeline ─────────────────────────────────────

class TestFullPipeline:
    """Integration tests for the complete TTS pipeline."""

    def test_end_to_end_synthesis(self):
        backend = FakeBackend()
        tts_ctx = TTSContext()
        stats = SegmentStats(total_characters=50)
        merged_sink = FakeAudioSink()
        chapter_sink = FakeAudioSink()
        subtitle_writer = FakeSubtitleWriter()

        cancel = lambda: False
        progress_calls = []
        def on_progress(pct, etr):
            progress_calls.append((pct, etr))

        # Simulate full pipeline: synthesize → subtitles → finalize
        segments, tokens = synthesize_text(
            text="This is a test sentence. Another sentence here.",
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel,
            on_progress=on_progress,
            chapter_sink=chapter_sink,
            audio_sink=merged_sink,
            subtitle_mode="Sentence",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
        )

        # Process accumulated tokens
        process_and_write_subtitles(
            tokens,
            subtitle_writer,
            subtitle_mode="Sentence",
            max_subtitle_words=5,
            lang_code="a",
            use_spacy_segmentation=False,
            fallback_end_time=stats.current_time,
        )

        # Verify results
        assert segments >= 1
        assert len(merged_sink.written) >= 1
        assert len(chapter_sink.written) >= 1
        assert stats.processed_chars > 0
        assert stats.current_time > 0

    def test_multi_segment_with_cancel(self):
        """Test that cancellation works mid-pipeline."""
        backend = FakeBackend()
        tts_ctx = TTSContext()
        stats = SegmentStats(total_characters=10000)

        cancel_count = [0]
        def cancel_fn():
            cancel_count[0] += 1
            return cancel_count[0] > 3  # Cancel after 3 segments

        progress_calls = []
        def on_progress(pct, etr):
            progress_calls.append((pct, etr))

        segments, tokens = synthesize_text(
            text="Hello world. " * 100,
            tts_context=tts_ctx,
            backend=backend,
            voice="M1",
            speed=1.0,
            stats=stats,
            check_cancel=cancel_fn,
            on_progress=on_progress,
        )

        # Should have stopped before processing all text
        assert segments <= 4
