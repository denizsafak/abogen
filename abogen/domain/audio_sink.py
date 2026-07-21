"""Audio sink abstraction for unified audio output.

Provides a context-manager-based abstraction for writing audio data
to various output formats (WAV, FLAC via soundfile; compressed via ffmpeg).

Usage:
    with open_audio_sink(path, "wav") as sink:
        sink.write(audio_data)
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from abogen.domain.audio_buffer import SAMPLE_RATE
from abogen.domain.audio_helpers import build_ffmpeg_command


@dataclass(frozen=True)
class AudioSink:
    """Represents an open audio output target."""

    write: Callable[[np.ndarray], None]
    close: Callable[[], None]

    def __enter__(self) -> AudioSink:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def _ensure_ffmpeg() -> None:
    """Ensure static ffmpeg binaries are on PATH."""
    import static_ffmpeg  # type: ignore

    ffmpeg_cache_root = _get_ffmpeg_cache_root()
    platform_cache = os.path.join(ffmpeg_cache_root, sys.platform)
    os.makedirs(platform_cache, exist_ok=True)
    try:
        import static_ffmpeg.run as static_ffmpeg_run  # type: ignore

        static_ffmpeg_run.LOCK_FILE = os.path.join(ffmpeg_cache_root, "lock.file")
    except Exception:
        pass
    static_ffmpeg.add_paths(weak=True, download_dir=platform_cache)


def _get_ffmpeg_cache_root() -> str:
    from abogen.utils import get_internal_cache_path

    return get_internal_cache_path("ffmpeg")


def open_audio_sink(
    path: Path,
    fmt: str,
    *,
    metadata: Optional[dict[str, str]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    extra_ffmpeg_args: Optional[list[str]] = None,
    ffmpeg_cmd: Optional[list[str]] = None,
) -> AudioSink:
    """Open an audio output sink for writing raw float32 PCM samples.

    Args:
        path: Output file path.
        fmt: Output format ("wav", "flac", "mp3", "opus", "m4b").
        metadata: Optional metadata dict (ignored when ffmpeg_cmd is provided).
        cancel_check: Optional callable; if it returns True, writes are silently skipped.
        extra_ffmpeg_args: Optional extra args inserted after ffmpeg header (ignored when ffmpeg_cmd is provided).
        ffmpeg_cmd: Optional pre-built ffmpeg command list (for m4b with cover art etc.).

    Returns:
        AudioSink with write() and close() methods.
    """
    fmt = fmt.lower()

    if fmt in {"wav", "flac"}:
        import soundfile as sf

        soundfile_obj = sf.SoundFile(
            path,
            mode="w",
            samplerate=SAMPLE_RATE,
            channels=1,
            format=fmt.upper(),
        )

        def _write_wav(data: np.ndarray) -> None:
            if cancel_check and cancel_check():
                return
            soundfile_obj.write(data)

        def _close_wav() -> None:
            soundfile_obj.close()

        return AudioSink(write=_write_wav, close=_close_wav)

    # Compressed formats: pipe through ffmpeg
    _ensure_ffmpeg()

    if ffmpeg_cmd is not None:
        cmd = list(ffmpeg_cmd)
    else:
        cmd = build_ffmpeg_command(path, fmt, metadata=metadata)
        if extra_ffmpeg_args:
            cmd[2:2] = extra_ffmpeg_args

    process = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    def _write_compressed(data: np.ndarray) -> None:
        if (cancel_check and cancel_check()) or process.stdin is None or process.stdin.closed:
            return
        process.stdin.write(data.tobytes())

    def _close_compressed() -> None:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        process.wait()

    return AudioSink(write=_write_compressed, close=_close_compressed)
