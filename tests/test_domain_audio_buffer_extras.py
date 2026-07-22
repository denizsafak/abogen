"""Tests for domain/audio_buffer.py — fit_audio_to_duration, ffmpeg_time_stretch."""

import numpy as np
import pytest
from unittest.mock import patch

from abogen.domain.audio_buffer import fit_audio_to_duration, ffmpeg_time_stretch, SAMPLE_RATE


class TestFitAudioToDuration:
  def test_exact_length(self):
    audio = np.ones(24000, dtype="float32")
    result = fit_audio_to_duration(audio, 1.0, SAMPLE_RATE)
    assert len(result) == 24000

  def test_shorter_pads_with_zeros(self):
    audio = np.ones(12000, dtype="float32")
    result = fit_audio_to_duration(audio, 1.0, SAMPLE_RATE)
    assert len(result) == 24000
    assert result[0] == 1.0
    assert result[12000] == 0.0

  def test_longer_trims(self):
    audio = np.ones(48000, dtype="float32")
    result = fit_audio_to_duration(audio, 1.0, SAMPLE_RATE)
    assert len(result) == 24000
    assert result[-1] == 1.0

  def test_empty_input(self):
    result = fit_audio_to_duration(np.array([], dtype="float32"), 0.5, SAMPLE_RATE)
    assert len(result) == 12000
    assert np.all(result == 0.0)

  def test_output_dtype(self):
    audio = np.ones(100, dtype="float32")
    result = fit_audio_to_duration(audio, 0.5, SAMPLE_RATE)
    assert result.dtype == np.float32


class TestFfmpegTimeStretch:
  def test_no_stretch_below_threshold(self):
    audio = np.ones(24000, dtype="float32")
    result = ffmpeg_time_stretch(audio, 0.8, SAMPLE_RATE)
    np.testing.assert_array_equal(result, audio)

  def test_no_stretch_at_exactly_one(self):
    audio = np.ones(24000, dtype="float32")
    result = ffmpeg_time_stretch(audio, 1.0, SAMPLE_RATE)
    np.testing.assert_array_equal(result, audio)

  def test_empty_audio(self):
    result = ffmpeg_time_stretch(np.array([], dtype="float32"), 2.0, SAMPLE_RATE)
    assert len(result) == 0

@patch("subprocess.Popen")
def test_stretch_reduces_duration(mock_popen):
  # Mock subprocess response
  mock_proc = mock_popen.return_value
  mock_proc.returncode = 0
  mock_proc.communicate.return_value = (b"\x00" * 400, b"")
  mock_proc.stdout.read.return_value = b"\x00" * 400

  audio = np.random.randn(48000).astype("float32")
  result = ffmpeg_time_stretch(audio, 2.0, SAMPLE_RATE)

  # Verify ffmpeg was called with correct args
  mock_popen.assert_called_once()
  args = mock_popen.call_args[0][0]
  assert "ffmpeg" in args[0]
  assert "-filter:a" in args
  assert any("atempo=" in arg for arg in args)

  # Verify result has reduced duration and correct dtype
  assert len(result) < len(audio)
  assert len(result) > 0
  assert result.dtype == np.float32
