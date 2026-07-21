"""Output layout resolution service.

Determines where conversion outputs (audio, subtitles, metadata) should be written.
Extracted from conversion_planner.py as a standalone service per plan Stage 5.

Responsibilities:
- Resolve base output directory from save_mode and source_path
- Determine base filename from original_filename
- Find unique output path to avoid overwrites
- Resolve project layout (audio_dir, subtitle_dir, metadata_dir)
- Force merged output for m4b format
- Return OutputLayout dataclass
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from abogen.application.conversion_models import OutputLayout
from abogen.application.conversion_request import ConversionRequest
from abogen.domain.output_paths import (
    resolve_project_layout,
    resolve_unique_path,
    sanitize_output_stem,
)


def resolve_output_layout(request: ConversionRequest) -> OutputLayout:
    """Resolve output paths for a conversion request.

    This is the single entry point for output path resolution,
    used by both UIs and the conversion service.

    Args:
        request: Normalized conversion request

    Returns:
        OutputLayout with resolved paths
    """
    # Determine base output directory
    if request.save_mode == "custom_folder" and request.output_folder:
        parent_dir = Path(request.output_folder)
    elif request.source_path:
        parent_dir = request.source_path.parent
    else:
        parent_dir = Path.cwd()

    # Determine base name
    if request.original_filename:
        base_name = sanitize_output_stem(request.original_filename)
    elif request.source_path:
        base_name = sanitize_output_stem(request.source_path.stem)
    else:
        base_name = "output"

    # Find unique output path
    allowed_exts = {request.output_format, "srt", "ass", "vtt", "mp4", "m4b"}
    unique_base = resolve_unique_path(
        parent_dir, base_name, "", allowed_extensions=allowed_exts
    )

    # Resolve project layout
    project_root = None
    audio_dir = parent_dir
    subtitle_dir = None
    metadata_dir = None

    if request.save_as_project:
        project_root, audio_dir, subtitle_dir, metadata_dir = resolve_project_layout(
            original_filename=request.original_filename,
            save_as_project=True,
            base_dir=parent_dir,
        )

    return OutputLayout(
        parent_dir=parent_dir,
        project_root=project_root,
        audio_dir=audio_dir,
        subtitle_dir=subtitle_dir,
        metadata_dir=metadata_dir,
    )


def resolve_merged_path(
    layout: OutputLayout,
    request: ConversionRequest,
) -> Path:
    """Resolve the merged output audio file path.

    Args:
        layout: Resolved output layout
        request: Conversion request

    Returns:
        Path to the merged output file
    """
    base_name = sanitize_output_stem(
        request.original_filename or "output"
    )
    return layout.audio_dir / f"{base_name}.{request.output_format}"


def resolve_chapter_path(
    layout: OutputLayout,
    request: ConversionRequest,
    chapter_title: str,
    chapter_index: int,
) -> Path:
    """Resolve the output path for a separate chapter file.

    Args:
        layout: Resolved output layout
        request: Conversion request
        chapter_title: Chapter title for filename
        chapter_index: Chapter number (1-based)

    Returns:
        Path to the chapter output file
    """
    import re

    slug = re.sub(r'[^\w\s-]', '', chapter_title.lower())
    slug = re.sub(r'[\s_]+', '_', slug).strip('_')
    if not slug:
        slug = f"chapter_{chapter_index}"
    filename = f"{chapter_index:02d}_{slug}.{request.separate_chapters_format}"
    return layout.audio_dir / "chapters" / filename


def should_merge_output(request: ConversionRequest) -> bool:
    """Determine if merged output is required.

    Rules:
    - m4b format always forces merged output
    - If save_chapters_separately is False, merged is required
    - Otherwise, use merge_chapters_at_end setting

    Args:
        request: Conversion request

    Returns:
        True if merged output should be created
    """
    if request.output_format.lower() == "m4b":
        return True
    if not request.save_chapters_separately:
        return True
    return request.merge_chapters_at_end
