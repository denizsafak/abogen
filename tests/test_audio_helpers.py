"""Tests for audio helper utilities.

Tests import from domain/audio_helpers.py (new module).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# build_ffmpeg_command
# ---------------------------------------------------------------------------


class TestBuildFfmpegCommand:
    """build_ffmpeg_command builds ffmpeg argument list."""

    def test_base_structure(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out/audio.wav"), "wav")
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "pipe:0" in cmd
        assert str(Path("/out/audio.wav")) in cmd

    def test_mp3_codec(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out.mp3"), "mp3")
        assert "libmp3lame" in cmd

    def test_opus_codec(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out.opus"), "opus")
        assert "libopus" in cmd

    def test_m4b_codec(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out.m4b"), "m4b")
        assert "aac" in cmd
        assert "-q:a" in cmd
        assert "+faststart+use_metadata_tags" in cmd

    def test_wav_copy_codec(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out.wav"), "wav")
        assert "copy" in cmd

    def test_with_metadata(self):
        from abogen.domain.audio_helpers import build_ffmpeg_command

        cmd = build_ffmpeg_command(Path("/out.mp3"), "mp3", metadata={"album": "Test"})
        assert str(Path("/out.mp3")) in cmd


# ---------------------------------------------------------------------------
# to_float32
# ---------------------------------------------------------------------------


class TestToFloat32:
    """to_float32 converts audio to float32 numpy array."""

    def test_none_returns_empty(self):
        from abogen.domain.audio_helpers import to_float32

        result = to_float32(None)
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert len(result) == 0

    def test_numpy_array(self):
        from abogen.domain.audio_helpers import to_float32

        arr = np.array([1.0, 2.0, 3.0], dtype="float64")
        result = to_float32(arr)
        assert result.dtype == np.float32
        assert len(result) == 3

    def test_mock_tensor(self):
        from abogen.domain.audio_helpers import to_float32

        tensor = MagicMock()
        tensor.detach.return_value = tensor
        tensor.cpu.return_value = tensor
        tensor.numpy.return_value = np.array([1.0, 2.0])
        result = to_float32(tensor)
        assert result.dtype == np.float32
        assert len(result) == 2

    def test_list_input(self):
        from abogen.domain.audio_helpers import to_float32

        result = to_float32([1.0, 2.0])
        assert result.dtype == np.float32
        assert len(result) == 2


# ---------------------------------------------------------------------------
# apply_m4b_chapters_with_mutagen
# ---------------------------------------------------------------------------


class TestApplyM4bChaptersWithMutagen:
    """apply_m4b_chapters_with_mutagen writes chapter atoms to MP4."""

    def test_empty_chapters_returns_false(self):
        from abogen.domain.audio_helpers import apply_m4b_chapters_with_mutagen

        assert apply_m4b_chapters_with_mutagen(Path("/fake.m4b"), []) is False

    def test_missing_mutagen_raises(self):
        from abogen.domain.audio_helpers import apply_m4b_chapters_with_mutagen

        with patch.dict("sys.modules", {"mutagen": None, "mutagen.mp4": None}):
            with pytest.raises((ImportError, KeyError)):
                apply_m4b_chapters_with_mutagen(
                    Path("/fake.m4b"), [{"start": 0, "title": "Ch1"}]
                )
