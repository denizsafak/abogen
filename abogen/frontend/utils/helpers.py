"""
Frontend-specific utilities for the Abogen Flet application.

Contains helpers for:
- Human-readable size / duration formatting
- Voice formula parsing and display
- File-type detection
- ETR (Estimated Time Remaining) formatting
- Path resolution that adapts to desktop vs. web context
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from abogen.constants import (
    LANGUAGE_DESCRIPTIONS,
    SUPPORTED_INPUT_FORMATS,
    SUPPORTED_SOUND_FORMATS,
    SUBTITLE_FORMATS,
    VOICES_INTERNAL,
)


# ---------------------------------------------------------------------------
# Size / duration helpers
# ---------------------------------------------------------------------------


def human_readable_size(size_bytes: int, decimal_places: int = 2) -> str:
    """
    Convert a byte count into a human-readable string.

    Args:
        size_bytes: Number of bytes.
        decimal_places: Significant decimal digits in the output.

    Returns:
        A string like ``"3.14 MB"`` or ``"1.00 KB"``.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.{decimal_places}f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.{decimal_places}f} PB"


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds as ``HH:MM:SS``.

    Args:
        seconds: Non-negative floating-point duration.

    Returns:
        A colon-delimited time string, e.g. ``"00:03:42"``.
    """
    total = max(0, int(seconds))
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_etr(etr_seconds: Optional[float]) -> str:
    """
    Format an estimated time remaining value for the UI.

    Args:
        etr_seconds: Seconds remaining, or None when unknown.

    Returns:
        Human-readable string such as ``"~3 min 42 sec"`` or ``"Calculating…"``.
    """
    if etr_seconds is None:
        return "Calculating…"
    total = max(0, int(etr_seconds))
    if total < 60:
        return f"~{total} sec"
    m, s = divmod(total, 60)
    if m < 60:
        return f"~{m} min {s} sec"
    h, m = divmod(m, 60)
    return f"~{h} h {m} min"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
    ".txt",
    ".epub",
    ".pdf",
    ".md",
    ".markdown",
    ".srt",
    ".ass",
    ".vtt",
)
"""All file extensions that the drop-zone accepts."""


def detect_file_type(file_path: str) -> str:
    """
    Return a normalised file-type token for the given path.

    Args:
        file_path: Absolute or relative path to the input file.

    Returns:
        One of ``'txt'``, ``'epub'``, ``'pdf'``, ``'markdown'``,
        ``'subtitle'``, or ``'unknown'``.
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".epub":
        return "epub"
    if ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext in (".srt", ".ass", ".vtt"):
        return "subtitle"
    if ext == ".txt":
        return "txt"
    return "unknown"


def is_supported_file(file_path: str) -> bool:
    """
    Return True when the file extension is in the supported set.

    Args:
        file_path: Path whose extension is inspected.
    """
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS


def is_book_type(file_type: str) -> bool:
    """
    Return True for file types that contain chapters / pages.

    Args:
        file_type: Token from ``detect_file_type()``.
    """
    return file_type in ("epub", "pdf", "markdown")


# ---------------------------------------------------------------------------
# Voice helpers
# ---------------------------------------------------------------------------


def voice_lang_code(voice: str) -> str:
    """
    Extract the language code character from a Kokoro voice name.

    The first character of every internal voice name encodes the language
    (e.g. ``'a'`` for American English, ``'b'`` for British English).

    Args:
        voice: Raw voice string like ``'af_heart'`` or a formula.

    Returns:
        Single lowercase character, defaulting to ``'a'`` on failure.
    """
    if not voice:
        return "a"
    # For plain voice IDs the first char is the language
    if voice[0].isalpha() and "_" in voice[:4]:
        return voice[0].lower()
    # Formula: extract first alpha char
    match = re.search(r"\b([a-z])", voice)
    return match.group(1) if match else "a"


def language_label(lang_code: str) -> str:
    """
    Return the human-readable label for a language code.

    Args:
        lang_code: Single-character code (``'a'``, ``'b'``, …).

    Returns:
        Display string, e.g. ``"American English"``.
    """
    return LANGUAGE_DESCRIPTIONS.get(lang_code, lang_code.upper())


def grouped_voices() -> List[Tuple[str, List[str]]]:
    """
    Return the internal voice list grouped by language for display.

    Returns:
        List of ``(language_label, [voice_id, …])`` tuples.
    """
    groups: dict[str, List[str]] = {}
    for v in VOICES_INTERNAL:
        lang = language_label(v[0])
        groups.setdefault(lang, []).append(v)
    return sorted(groups.items())


def voice_display_name(voice_id: str) -> str:
    """
    Convert a raw voice ID like ``'af_heart'`` to a prettier display name.

    Args:
        voice_id: Raw internal voice identifier.

    Returns:
        Formatted string, e.g. ``"af_heart"`` (unchanged; may be enhanced later).
    """
    return voice_id


def parse_voice_formula(formula: str) -> List[Tuple[str, float]]:
    """
    Parse a Kokoro voice mix formula into a list of ``(voice_id, weight)`` tuples.

    Example:
        ``"af_heart*0.7+am_adam*0.3"`` → ``[('af_heart', 0.7), ('am_adam', 0.3)]``

    Args:
        formula: Space- or ``+``-joined mix formula string.

    Returns:
        Parsed list; empty if parsing fails.
    """
    parts: List[Tuple[str, float]] = []
    for token in re.split(r"[+\s]+", formula.strip()):
        token = token.strip()
        if not token:
            continue
        if "*" in token:
            name, _, weight_str = token.partition("*")
            try:
                parts.append((name.strip(), float(weight_str.strip())))
            except ValueError:
                pass
        else:
            # Bare voice id — assume full weight
            if token in VOICES_INTERNAL:
                parts.append((token, 1.0))
    return parts


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------


def format_number(n: int) -> str:
    """
    Format an integer with thousands separators.

    Args:
        n: Integer value.

    Returns:
        Formatted string, e.g. ``"1,234,567"``.
    """
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def safe_basename(path: Optional[str]) -> str:
    """
    Return the basename of a path, or an empty string when path is None/empty.

    Args:
        path: Optional file-system path.
    """
    if not path:
        return ""
    return os.path.basename(path)


def output_format_label(fmt: str) -> str:
    """
    Return a display label for an audio output format key.

    Args:
        fmt: Lowercase format key (``'wav'``, ``'mp3'``, …).
    """
    labels = {
        "wav": "WAV (lossless)",
        "flac": "FLAC (lossless compressed)",
        "mp3": "MP3",
        "opus": "Opus (best compression)",
        "m4b": "M4B (with chapters)",
    }
    return labels.get(fmt, fmt.upper())


def subtitle_format_label(key: str) -> str:
    """
    Return the display label for a subtitle format key.

    Args:
        key: Internal subtitle format key (e.g. ``'ass_centered_narrow'``).
    """
    for k, label in SUBTITLE_FORMATS:
        if k == key:
            return label
    return key
