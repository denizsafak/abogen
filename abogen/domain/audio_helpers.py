"""Audio helper utilities.

Functions for building ffmpeg commands, converting audio formats,
and applying chapter metadata to MP4 files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


SAMPLE_RATE = 24000


def build_ffmpeg_command(path: Path, fmt: str, metadata: Optional[Dict[str, str]] = None) -> list[str]:
    from abogen.infrastructure.exporters import ExportService

    base = [
        "ffmpeg",
        "-y",
        "-f",
        "f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-i",
        "pipe:0",
    ]
    if fmt == "mp3":
        base += ["-c:a", "libmp3lame", "-qscale:a", "2"]
    elif fmt == "opus":
        base += ["-c:a", "libopus", "-b:a", "24000"]
    elif fmt == "m4b":
        base += ["-c:a", "aac", "-q:a", "2", "-movflags", "+faststart+use_metadata_tags"]
    else:
        base += ["-c:a", "copy"]

    if metadata:
        svc = ExportService()
        base.extend(svc._metadata_to_ffmpeg_args(metadata))
    base.append(str(path))
    return base


def to_float32(audio_segment) -> np.ndarray:
    if audio_segment is None:
        return np.zeros(0, dtype="float32")

    tensor = audio_segment
    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        try:
            tensor = tensor.cpu()
        except Exception:
            pass
    if hasattr(tensor, "numpy"):
        return np.asarray(tensor.numpy(), dtype="float32").reshape(-1)
    return np.asarray(tensor, dtype="float32").reshape(-1)


def apply_m4b_chapters_with_mutagen(
    audio_path: Path,
    chapters: List[Dict[str, Any]],
) -> bool:
    """Apply chapter atoms to an MP4/M4B file using mutagen.

    Returns True if chapters were written, False otherwise.
    Raises ImportError if mutagen is not installed.
    """
    if not chapters:
        return False

    from fractions import Fraction
    from mutagen.mp4 import MP4, MP4Chapter  # type: ignore[import]

    mp4 = MP4(str(audio_path))

    chapter_objects: List[MP4Chapter] = []
    for index, entry in enumerate(sorted(chapters, key=lambda item: float(item.get("start") or 0.0))):
        start_raw = entry.get("start")
        if start_raw is None:
            continue
        try:
            start_seconds = max(0.0, float(start_raw))
        except (TypeError, ValueError):
            continue

        title_value = entry.get("title")
        title_text = str(title_value) if title_value else f"Chapter {index + 1}"

        start_fraction = Fraction(int(round(start_seconds * 1000)), 1000)
        chapter_atom = MP4Chapter(start_fraction, title_text)

        end_raw = entry.get("end")
        if end_raw is not None:
            try:
                end_seconds = float(end_raw)
            except (TypeError, ValueError):
                end_seconds = None
            if end_seconds is not None and end_seconds > start_seconds:
                chapter_atom.end = Fraction(int(round(end_seconds * 1000)), 1000)

        chapter_objects.append(chapter_atom)

    if not chapter_objects:
        return False

    from typing import cast

    mp4.chapters = cast(Any, chapter_objects)
    mp4.save()

    return True
