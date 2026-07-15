"""Output path resolution utilities.

Pure functions for resolving output directories, building file paths,
and computing project folder layouts.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from abogen.text_extractor import ExtractedChapter


_OUTPUT_SANITIZE_RE = re.compile(r"[^\w\-_.]+")


def slugify(title: str, index: int) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", title.lower()).strip("_")
    if not sanitized:
        sanitized = f"chapter_{index:02d}"
    return sanitized[:80]


def sanitize_output_stem(name: str) -> str:
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


def resolve_output_directory(
    *,
    save_mode: str,
    stored_path: Path,
    output_folder: Optional[str],
    desktop_dir: Optional[Path],
    user_output_path: Optional[Path],
    user_cache_outputs: Optional[Path],
) -> Path:
    if save_mode == "Save to Desktop" and desktop_dir:
        return desktop_dir
    if save_mode == "Save next to input file":
        return stored_path.parent
    if save_mode == "Choose output folder" and output_folder:
        return Path(output_folder)
    if save_mode == "Use default save location" and user_output_path:
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
