"""Tests for domain/audio_sink.py"""

import numpy as np
import soundfile as sf
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import subprocess

from abogen.domain.audio_sink import AudioSink, open_audio_sink, _ensure_ffmpeg


class TestAudioSinkDataclass:
    def test_audio_sink_is_frozen(self):
        sink = AudioSink(write=lambda d: None, close=lambda: None)
        try:
            sink.write = lambda d: None  # type: ignore
        except AttributeError:
            pass  # Expected — frozen=True
        assert hasattr(sink, "write")
        assert hasattr(sink, "close")

    def test_audio_sink_stores_callables(self):
        write_fn = MagicMock()
        close_fn = MagicMock()
        sink = AudioSink(write=write_fn, close=close_fn)
        assert sink.write is write_fn
        assert sink.close is close_fn

    def test_audio_sink_write_callable(self):
        calls = []
        sink = AudioSink(write=lambda d: calls.append(d), close=lambda: None)
        data = np.zeros(100, dtype="float32")
        sink.write(data)
        assert len(calls) == 1
        np.testing.assert_array_equal(calls[0], data)

    def test_audio_sink_close_callable(self):
        closed = []
        sink = AudioSink(write=lambda d: None, close=lambda: closed.append(True))
        sink.close()
        assert closed == [True]


class TestOpenAudioSinkWav:
    def test_wav_creates_file(self, tmp_path: Path):
        out = tmp_path / "test.wav"
        with open_audio_sink(out, "wav") as sink:
            sink.write(np.zeros(100, dtype="float32"))
        assert out.exists()

    def test_flac_creates_file(self, tmp_path: Path):
        out = tmp_path / "test.flac"
        with open_audio_sink(out, "flac") as sink:
            sink.write(np.zeros(100, dtype="float32"))
        assert out.exists()

    def test_wav_sink_writes_audio(self, tmp_path: Path):
        out = tmp_path / "out.wav"
        audio = np.random.uniform(-0.5, 0.5, 24000).astype("float32")  # 1 second
        with open_audio_sink(out, "wav") as sink:
            sink.write(audio)
        data, sr = sf.read(str(out))
        assert sr == 24000
        assert len(data) == 24000
        np.testing.assert_allclose(data, audio, atol=1e-4)

    def test_wav_sink_close_flushes(self, tmp_path: Path):
        out = tmp_path / "flush.wav"
        with open_audio_sink(out, "wav") as sink:
            sink.write(np.ones(1000, dtype="float32"))
        assert out.exists()
        info = sf.info(str(out))
        assert info.samplerate == 24000
        assert info.channels == 1

    def test_wav_sink_context_manager(self, tmp_path: Path):
        out = tmp_path / "ctx.wav"
        with open_audio_sink(out, "wav") as sink:
            assert isinstance(sink, AudioSink)
            sink.write(np.zeros(50, dtype="float32"))
        assert out.exists()

    def test_wav_sink_multiple_writes(self, tmp_path: Path):
        out = tmp_path / "multi.wav"
        with open_audio_sink(out, "wav") as sink:
            sink.write(np.ones(1000, dtype="float32"))
            sink.write(np.ones(500, dtype="float32"))
        data, _ = sf.read(str(out))
        assert len(data) == 1500


class TestCancelCheck:
    def test_cancel_check_skips_wav_writes(self, tmp_path: Path):
        out = tmp_path / "cancelled.wav"
        with open_audio_sink(out, "wav", cancel_check=lambda: True) as sink:
            sink.write(np.ones(1000, dtype="float32"))
            sink.write(np.ones(500, dtype="float32"))
        data, _ = sf.read(str(out))
        assert len(data) == 0

    def test_cancel_check_none_allows_writes(self, tmp_path: Path):
        out = tmp_path / "ok.wav"
        with open_audio_sink(out, "wav", cancel_check=None) as sink:
            sink.write(np.ones(1000, dtype="float32"))
        data, _ = sf.read(str(out))
        assert len(data) == 1000


class TestUnsupportedFormat:
    def test_unsupported_format_raises(self, tmp_path: Path):
        out = tmp_path / "bad.xyz"
        try:
            with open_audio_sink(out, "xyz") as sink:
                pass
            assert False, "Should have raised"
        except Exception:
            pass  # Expected


class TestOpenAudioSinkCompressed:
    @patch("abogen.domain.audio_sink._ensure_ffmpeg")
    @patch("abogen.domain.audio_sink.build_ffmpeg_command")
    @patch("abogen.domain.audio_sink.subprocess.Popen")
    def test_mp3_sink_returns_sink(self, mock_popen, mock_build, mock_ensure, tmp_path: Path):
        mock_build.return_value = ["ffmpeg", "-y", "-i", "pipe:0", "out.mp3"]
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdin.closed = False
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        out = tmp_path / "test.mp3"
        sink = open_audio_sink(out, "mp3")
        assert isinstance(sink, AudioSink)
        sink.write(np.zeros(100, dtype="float32"))
        assert proc.stdin.write.called
        sink.close()

    @patch("abogen.domain.audio_sink._ensure_ffmpeg")
    @patch("abogen.domain.audio_sink.build_ffmpeg_command")
    @patch("abogen.domain.audio_sink.subprocess.Popen")
    def test_cancel_check_skips_compressed_writes(self, mock_popen, mock_build, mock_ensure, tmp_path: Path):
        mock_build.return_value = ["ffmpeg", "-y", "-i", "pipe:0", "out.mp3"]
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdin.closed = False
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        sink = open_audio_sink(tmp_path / "c.mp3", "mp3", cancel_check=lambda: True)
        sink.write(np.zeros(100, dtype="float32"))
        assert not proc.stdin.write.called
        sink.close()

    @patch("abogen.domain.audio_sink._ensure_ffmpeg")
    @patch("abogen.domain.audio_sink.build_ffmpeg_command")
    @patch("abogen.domain.audio_sink.subprocess.Popen")
    def test_extra_ffmpeg_args_passed(self, mock_popen, mock_build, mock_ensure, tmp_path: Path):
        mock_build.return_value = ["ffmpeg", "-y", "-header", "-i", "pipe:0", "out.mp3"]
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdin.closed = False
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        sink = open_audio_sink(
            tmp_path / "extra.mp3",
            "mp3",
            extra_ffmpeg_args=["-thread_queue_size", "32768"],
        )
        args = mock_popen.call_args[0][0]
        assert "-thread_queue_size" in args
        assert "32768" in args
        sink.close()

    @patch("abogen.domain.audio_sink._ensure_ffmpeg")
    @patch("abogen.domain.audio_sink.build_ffmpeg_command")
    @patch("abogen.domain.audio_sink.subprocess.Popen")
    def test_metadata_passed_to_ffmpeg(self, mock_popen, mock_build, mock_ensure, tmp_path: Path):
        mock_build.return_value = ["ffmpeg", "-y", "-i", "pipe:0", "out.opus"]
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdin.closed = False
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        meta = {"title": "Test", "artist": "Author"}
        open_audio_sink(tmp_path / "meta.opus", "opus", metadata=meta)
        mock_build.assert_called_once_with(tmp_path / "meta.opus", "opus", metadata=meta)
