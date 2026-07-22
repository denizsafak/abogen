"""Output path resolution utilities.

Pure functions for resolving output directories, building file paths,
and computing project folder layouts.
"""

from __future__ import annotations

import os
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from abogen.subtitle_utils import sanitize_name_for_os
from abogen.text_extractor import ExtractedChapter


_OUTPUT_SANITIZE_RE = re.compile(r"[^\w\-_.]+")

# OS-specific illegal characters for filenames
_WINDOWS_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_UNIX_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f]')
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def slugify(title: str, index: int) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", title.lower()).strip("_")
    if not sanitized:
        sanitized = f"chapter_{index:02d}"
    return sanitized[:80]


def sanitize_filename_for_chapter(title: str, index: int, max_len: int = 80) -> str:
    """Sanitize a chapter name for use as a filename component.

    Combines character sanitization, OS safety, and smart truncation
    at word boundaries. Prepends zero-padded index prefix.

    Args:
        title: Raw chapter title.
        index: 1-based chapter number for prefix.
        max_len: Maximum length of the sanitized portion (excluding prefix).

    Returns:
        Sanitized string like "01_the_beginning".
    """
    # Remove non-word/non-space/non-hyphen chars, then collapse spaces/hyphens
    sanitized = re.sub(r"[^\w\s\-]", "", title)
    sanitized = re.sub(r"[\s\-]+", "_", sanitized).strip("_")

    if not sanitized:
        sanitized = f"chapter_{index:02d}"

    # OS-specific sanitization
    system = platform.system()
    if system == "Windows":
        sanitized = _WINDOWS_ILLEGAL_CHARS_RE.sub("_", sanitized)
        sanitized = sanitized.rstrip(". ")
        base = sanitized.split(".")[0].upper()
        if base in _RESERVED_NAMES:
            sanitized = f"_{sanitized}"
    # Linux: only NUL is truly illegal, but control chars are problematic
    sanitized = _UNIX_CONTROL_CHARS_RE.sub("_", sanitized)

    # Smart truncation at word boundary
    if len(sanitized) > max_len:
        pos = sanitized[:max_len].rfind("_")
        sanitized = sanitized[: pos if pos > 0 else max_len].rstrip("_")

    return f"{index:02d}_{sanitized}"


def sanitize_output_stem(name: str, index: int = 0) -> str:
    base = Path(name or "").stem
    sanitized = _OUTPUT_SANITIZE_RE.sub("_", base).strip("_")
    return sanitized or "output"


def output_timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def build_output_path(directory: Path, original_name: str, extension: str) -> Path:
    sanitized = sanitize_output_stem(original_name)
    return directory / f"{sanitized}.{extension}"


def apply_newline_policy(chapters: List[ExtractedChapter], replace_single_newlines: bool) -> None:
    if not replace_single_newlines:
        return
    newline_regex = re.compile(r"(?<!\n)\n(?!\n)")
    for chapter in chapters:
        chapter.text = newline_regex.sub(" ", chapter.text)


from abogen.domain.enums import SaveMode


def resolve_output_directory(
    *,
    save_mode: str,
    stored_path: Path,
    output_folder: Optional[str],
    desktop_dir: Optional[Path],
    user_output_path: Optional[Path],
    user_cache_outputs: Optional[Path],
) -> Path:
    if save_mode in (SaveMode.SAVE_TO_DESKTOP, "Save to Desktop") and desktop_dir:
        return desktop_dir
    if save_mode in (SaveMode.SAVE_NEXT_TO_INPUT, "Save next to input file"):
        return stored_path.parent
    if save_mode in (SaveMode.CHOOSE_OUTPUT_FOLDER, "Choose output folder") and output_folder:
        return Path(output_folder)
    if save_mode in (SaveMode.DEFAULT_OUTPUT, "Use default save location") and user_output_path:
        return user_output_path
    return user_cache_outputs or Path(".")


def resolve_project_layout(
    *,
    original_filename: str,
    save_as_project: bool,
    base_dir: Path,
    timestamp_fn: Callable[[], str] = output_timestamp_token,
    sanitize_fn: Callable[[str, int], str] = sanitize_output_stem,
) -> Tuple[Path, Path, Path, Optional[Path]]:
    sanitized = sanitize_fn(original_filename, 0)
    folder_name = f"{timestamp_fn()}_{sanitized}"
    project_root = base_dir / folder_name
    project_root.mkdir(parents=True, exist_ok=True)

    if save_as_project:
        audio_dir = project_root / "audio"
        subtitle_dir = project_root / "subtitles"
        metadata_dir = project_root / "metadata"
        for directory in (audio_dir, subtitle_dir, metadata_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return project_root, audio_dir, subtitle_dir, metadata_dir

    return project_root, project_root, project_root, None


def resolve_unique_path(
    parent_dir: str,
    base_name: str,
    extension: str,
    allowed_extensions: Optional[set] = None,
) -> str:
    """Find a unique file path by appending _2, _3, etc. on collision.

    Args:
        parent_dir: Directory to check for collisions.
        base_name: Base filename (without extension).
        extension: File extension (without dot).
        allowed_extensions: Set of extensions to check against.
            If None, checks any existing file/dir with same name.

    Returns:
        Full path without extension (e.g. "/path/to/name_2").
    """
    sanitized = sanitize_name_for_os(base_name, is_folder=True)
    counter = 1
    while True:
        suffix = f"_{counter}" if counter > 1 else ""
        candidate = os.path.join(parent_dir, f"{sanitized}{suffix}")
        if allowed_extensions is not None:
            file_parts = (os.path.splitext(f) for f in os.listdir(parent_dir))
            clash = any(
                name == f"{sanitized}{suffix}"
                and ext[1:].lower() in allowed_extensions
                for name, ext in file_parts
            )
        else:
            clash = os.path.exists(candidate)
        if not clash:
            return candidate
        counter += 1
