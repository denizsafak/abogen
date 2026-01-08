"""Test package initialization.

Provides lightweight fallbacks for optional dependencies so unit tests can run
without the full runtime stack.
"""

from __future__ import annotations

import sys
from types import ModuleType


def _soundfile_write_stub(
    file_obj, data, samplerate, format="WAV", **_kwargs
):  # pragma: no cover - stub
    """Minimal stand-in for soundfile.write used in tests.

    The real library streams waveform data to disk. Our tests don't exercise
    audio synthesis, so it's safe to accept the call and write nothing.
    """

    if hasattr(file_obj, "write"):
        try:
            file_obj.write(b"")
        except Exception:
            # Ignore errors from exotic buffers; the real implementation would
            # write binary samples, so a no-op keeps behavior predictable.
            pass


if "soundfile" not in sys.modules:  # pragma: no cover - import guard
    stub = ModuleType("soundfile")
    stub.write = _soundfile_write_stub  # type: ignore[attr-defined]
    sys.modules["soundfile"] = stub


def _static_ffmpeg_add_paths_stub(*_args, **_kwargs) -> None:  # pragma: no cover - stub
    """Placeholder for static_ffmpeg.add_paths used in tests."""


if "static_ffmpeg" not in sys.modules:  # pragma: no cover - import guard
    ffmpeg_module = ModuleType("static_ffmpeg")
    ffmpeg_module.add_paths = _static_ffmpeg_add_paths_stub  # type: ignore[attr-defined]
    ffmpeg_run = ModuleType("static_ffmpeg.run")
    ffmpeg_run.LOCK_FILE = ""  # type: ignore[attr-defined]
    ffmpeg_module.run = ffmpeg_run  # type: ignore[attr-defined]
    sys.modules["static_ffmpeg"] = ffmpeg_module
    sys.modules["static_ffmpeg.run"] = ffmpeg_run
