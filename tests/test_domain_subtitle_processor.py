"""Tests for domain/subtitle_processor.py — parse_subtitle_file, format_time_range, process_subtitle_entries."""

import os
import tempfile
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

from abogen.domain.subtitle_processor import (
    parse_subtitle_file,
    format_time_range,
    speed_up_audio,
    process_subtitle_entries,
)


# --- format_time_range tests ---

class TestFormatTimeRange:
    def test_basic_range(self):
        result = format_time_range(0.0, 5.0)
        assert result == "00:00:00 - 00:00:05"

    def test_with_milliseconds(self):
        result = format_time_range(1.5, 3.123)
        assert "00:00:01,500" in result
        assert "00:00:03,123" in result

    def test_auto_end(self):
        result = format_time_range(10.0, 15.0, is_auto_end=True)
        assert result == "00:00:10 - AUTO"

    def test_none_end(self):
        result = format_time_range(5.0, None)
        assert result == "00:00:05 - AUTO"

    def test_hours(self):
        result = format_time_range(3661.0, 3665.0)
        assert result == "01:01:01 - 01:01:05"


# --- parse_subtitle_file tests ---

class TestParseSubtitleFile:
    def test_parse_srt(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nWorld\n",
            encoding="utf-8",
        )
        result = parse_subtitle_file(str(srt))
        assert len(result) == 2
        assert result[0][2] == "Hello"
        assert result[1][2] == "World"

    def test_parse_vtt(self, tmp_path):
        vtt = tmp_path / "test.vtt"
        vtt.write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello\n\n"
            "00:00:04.000 --> 00:00:06.000\nWorld\n",
            encoding="utf-8",
        )
        result = parse_subtitle_file(str(vtt))
        assert len(result) == 2

    def test_parse_timestamp_text(self, tmp_path):
        ts = tmp_path / "test.txt"
        ts.write_text(
            "[00:00:01] Hello\n[00:00:04] World\n",
            encoding="utf-8",
        )
        result = parse_subtitle_file(str(ts), is_timestamp_text=True)
        assert len(result) >= 1


# --- speed_up_audio tests ---

class TestSpeedUpAudio:
    def test_no_change_below_threshold(self):
        audio = np.ones(24000, dtype="float32")
        result = speed_up_audio(audio, 0.8, method="ffmpeg")
        np.testing.assert_array_equal(result, audio)

    def test_empty_audio(self):
        result = speed_up_audio(np.array([], dtype="float32"), 2.0, method="ffmpeg")
        assert len(result) == 0


# --- process_subtitle_entries tests ---

@dataclass
class FakeResult:
    audio: np.ndarray


def fake_backend(text, voice=None, speed=1.0, split_pattern=None):
    length = int(len(text) * 2400 * speed)
    audio = np.random.randn(length).astype("float32") * 0.1
    return [FakeResult(audio=audio)]


class TestProcessSubtitleEntries:
    def test_empty_subtitles(self):
        result = process_subtitle_entries(
            [], backend=fake_backend, voice=None
        )
        assert len(result) == 0

    def test_single_entry(self):
        subtitles = [(0.0, 3.0, "Hello")]
        result = process_subtitle_entries(
            subtitles, backend=fake_backend, voice=None
        )
        assert len(result) > 0
        assert result.dtype == np.float32

    def test_cancel_check(self):
        subtitles = [(0.0, 5.0, "Hello"), (5.0, 10.0, "World")]
        counter = [0]

        def cancel():
            counter[0] += 1
            return counter[0] > 1

        result = process_subtitle_entries(
            subtitles, backend=fake_backend, voice=None,
            cancel_check=cancel,
        )
        # Buffer is pre-allocated but only first entry processed before cancel
        assert result is not None
        # Second entry should not have been mixed in (no audio at 5-10s)
        assert np.max(np.abs(result[int(5.0 * 24000):])) == 0.0

    def test_log_callback_called(self):
        subtitles = [(0.0, 3.0, "Hello")]
        logs = []
        process_subtitle_entries(
            subtitles, backend=fake_backend, voice=None,
            log_callback=logs.append,
        )
        assert len(logs) >= 1
        assert "Hello" in logs[0]

    def test_progress_callback_called(self):
        subtitles = [(0.0, 3.0, "Hello")]
        progress = []
        process_subtitle_entries(
            subtitles, backend=fake_backend, voice=None,
            progress_callback=lambda p, e: progress.append((p, e)),
        )
        assert len(progress) == 1
        assert progress[0][0] == 99

    def test_multiple_entries_mixed(self):
        subtitles = [
            (0.0, 2.0, "First"),
            (2.0, 4.0, "Second"),
            (4.0, 6.0, "Third"),
        ]
        result = process_subtitle_entries(
            subtitles, backend=fake_backend, voice=None
        )
        assert len(result) > 0
        # Buffer should be at least as long as the last subtitle end
        assert len(result) >= int(6.0 * 24000)
