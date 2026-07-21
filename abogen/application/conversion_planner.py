"""Unified conversion planner.

Pure functions that take a ConversionRequest and produce a ConversionPlan.
No side effects, no I/O — all complexity from both UIs in one place.

This is Stage 2 of the conversion flow unification plan.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from abogen.application.conversion_models import (
    ChapterPlan,
    ConversionPlan,
    IntroOutroSpec,
    OutputLayout,
    SegmentPlan,
)
from abogen.application.conversion_request import ConversionRequest
from abogen.domain.chapter_overrides import apply_chapter_overrides
from abogen.domain.file_type import auto_select_relevant_chapters
from abogen.domain.intro_outro import resolve_intro, resolve_outro
from abogen.domain.metadata_extraction import extract_metadata_for_file
from abogen.domain.metadata_merge import merge_metadata
from abogen.domain.output_paths import (
    resolve_output_directory,
    resolve_project_layout,
    resolve_unique_path,
    sanitize_output_stem,
)
from abogen.subtitle_utils import split_text_by_voice_markers


def build_conversion_plan(request: ConversionRequest) -> ConversionPlan:
    """Build a complete conversion plan from a request.

    This is the single entry point that both UIs will call.
    It handles all the planning logic that was previously duplicated
    in both PyQt and WebUI conversion runners.

    Args:
        request: Normalized conversion request

    Returns:
        ConversionPlan with all chapters, segments, and output layout

    Raises:
        ValueError: If request is invalid (no source, no chapters, etc.)
    """
    # 1. Extract and validate source
    source_text = _extract_source_text(request)
    if not source_text or not source_text.strip():
        raise ValueError("No text content to convert")

    # 2. Extract metadata
    metadata = _extract_metadata(request)

    # 3. Parse chapters
    raw_chapters = _parse_chapters(source_text, request)

    # 4. Apply chapter selection/overrides
    selected_chapters = _apply_selection(raw_chapters, request)

    # 5. Build segments for each chapter
    chapters = _build_chapters(selected_chapters, request)

    # 6. Build intro/outro
    intro, outro = _build_intro_outro(metadata, request)

    # 7. Resolve output layout
    output_layout = _resolve_output_layout(request)

    return ConversionPlan(
        request=request,
        metadata=metadata,
        chapters=chapters,
        intro=intro,
        outro=outro,
        output_layout=output_layout,
    )


def _extract_source_text(request: ConversionRequest) -> Optional[str]:
    """Extract text from request source."""
    if request.direct_text:
        return request.direct_text
    if request.source_path and request.source_path.exists():
        from abogen.subtitle_utils import clean_text

        encoding = "utf-8"
        try:
            with open(request.source_path, "r", encoding=encoding, errors="replace") as f:
                text = f.read()
        except Exception:
            return None
        return clean_text(text)
    return None


def _extract_metadata(request: ConversionRequest) -> Dict[str, Any]:
    """Extract metadata from source file."""
    if request.direct_text:
        return dict(request.metadata_tags)

    if request.source_path and request.source_path.exists():
        try:
            extraction = extract_metadata_for_file(
                str(request.source_path), is_direct_text=False
            )
            metadata = dict(extraction.metadata) if extraction.metadata else {}
        except Exception:
            metadata = {}
        metadata = merge_metadata(metadata, request.metadata_tags)
        return metadata

    return dict(request.metadata_tags)


def _parse_chapters(
    source_text: str, request: ConversionRequest
) -> List[Tuple[str, str, str]]:
    """Parse source text into raw chapters.

    Returns list of (title, body_text, default_voice) tuples.
    """
    from abogen.domain.text_chapters import parse_chapters_from_text

    # For direct text, use the text as-is
    if request.direct_text:
        chapters = parse_chapters_from_text(source_text, default_title="text", clean=False)
    else:
        chapters = parse_chapters_from_text(source_text, default_title="text", clean=False)

    # Default voice from request
    default_voice = request.voice or "M1"

    return [(title, text, default_voice) for title, text in chapters]


def _apply_selection(
    raw_chapters: List[Tuple[str, str, str]], request: ConversionRequest
) -> List[Tuple[str, str, str]]:
    """Apply chapter selection and overrides."""
    from abogen.text_extractor import ExtractedChapter

    # Convert to ExtractedChapter objects for auto_select_relevant_chapters
    extracted = [
        ExtractedChapter(title=title, text=text)
        for title, text, _ in raw_chapters
    ]

    # If user specified chapters, apply overrides
    if request.chapter_overrides:
        selected, _, diagnostics = apply_chapter_overrides(extracted, request.chapter_overrides)
        if selected:
            # Map back to (title, text, voice) tuples
            result = []
            for ch in selected:
                # Find matching original chapter to get voice
                voice = request.voice or "M1"
                for orig_title, orig_text, orig_voice in raw_chapters:
                    if orig_title == ch.title:
                        voice = orig_voice
                        break
                result.append((ch.title, ch.text or "", voice))
            return result
        # If no chapters selected, fall through to auto-selection

    # Auto-select relevant chapters
    from abogen.domain.file_type import infer_file_type

    file_type = infer_file_type(request.source_path) if request.source_path else "text"
    result = auto_select_relevant_chapters(extracted, file_type)
    filtered = result.kept

    if filtered:
        # Map back to (title, text, voice) tuples
        result = []
        for ch in filtered:
            voice = request.voice or "M1"
            for orig_title, orig_text, orig_voice in raw_chapters:
                if orig_title == ch.title:
                    voice = orig_voice
                    break
            result.append((ch.title, ch.text or "", voice))
        return result

    # Fall back to all chapters
    return raw_chapters


def _build_chapters(
    selected_chapters: List[Tuple[str, str, str]], request: ConversionRequest
) -> List[ChapterPlan]:
    """Build ChapterPlan with SegmentPlan for each chapter."""
    chapters = []

    for idx, (title, body_text, default_voice) in enumerate(selected_chapters, 1):
        # Build segments for this chapter
        segments = _build_segments(body_text, default_voice, request)

        chapter = ChapterPlan(
            index=idx,
            title=title,
            original_title=title,
            body_text=body_text,
            segments=segments,
            voice_spec=default_voice,
        )
        chapters.append(chapter)

    return chapters


def _build_segments(
    body_text: str, default_voice: str, request: ConversionRequest
) -> List[SegmentPlan]:
    """Build SegmentPlan list for a chapter's body text.

    Handles voice markers (PyQt) and chunks (WebUI).
    """
    segments = []

    # Check for chunks (WebUI style)
    if request.chunks:
        # Group chunks by chapter (simplified — assume chunks are for current chapter)
        for chunk_idx, chunk in enumerate(request.chunks):
            chunk_text = chunk.get("normalized_text") or chunk.get("text", "")
            if not chunk_text or not chunk_text.strip():
                continue

            chunk_voice = _resolve_chunk_voice(chunk, default_voice, request)
            speaker_id = chunk.get("speaker_id", "narrator")

            segments.append(
                SegmentPlan(
                    text=chunk_text.strip(),
                    voice_spec=chunk_voice,
                    kind="body",
                    speaker_id=speaker_id,
                    chunk_id=chunk.get("id"),
                    chunk_index=chunk.get("chunk_index", chunk_idx),
                    level=chunk.get("level", request.chunk_level),
                    source="chunk",
                )
            )
        return segments

    # Check for voice markers (PyQt style)
    # Detect markers even if validation fails (voice names may not be loaded yet)
    from abogen.subtitle_utils import _VOICE_MARKER_SEARCH_PATTERN

    has_voice_markers = bool(_VOICE_MARKER_SEARCH_PATTERN.search(body_text))
    voice_segments, last_voice, valid_count, invalid_count = split_text_by_voice_markers(
        body_text, default_voice
    )

    if has_voice_markers or (len(voice_segments) > 1):
        # Voice markers were used
        for voice_name, segment_text in voice_segments:
            if not segment_text or not segment_text.strip():
                continue
            segments.append(
                SegmentPlan(
                    text=segment_text.strip(),
                    voice_spec=voice_name,
                    kind="body",
                    source="voice_marker",
                )
            )
        return segments

    # No voice markers — single segment for entire body
    if body_text and body_text.strip():
        segments.append(
            SegmentPlan(
                text=body_text.strip(),
                voice_spec=default_voice,
                kind="body",
                source="chapter",
            )
        )

    return segments


def _resolve_chunk_voice(
    chunk: Dict[str, Any], default_voice: str, request: ConversionRequest
) -> str:
    """Resolve voice for a chunk."""
    # Check for speaker-based voice
    speaker_id = chunk.get("speaker_id", "narrator")
    if speaker_id and speaker_id != "narrator" and request.speakers:
        speaker_config = request.speakers.get(speaker_id, {})
        if isinstance(speaker_config, dict):
            voice = speaker_config.get("voice")
            if voice:
                return voice

    # Check for direct voice field
    voice = chunk.get("voice")
    if voice:
        return voice

    return default_voice


def _build_intro_outro(
    metadata: Dict[str, Any], request: ConversionRequest
) -> Tuple[Optional[IntroOutroSpec], Optional[IntroOutroSpec]]:
    """Build intro and outro specs."""
    intro_spec = None
    outro_spec = None

    # Intro
    if request.read_title_intro:
        resolved = resolve_intro(
            metadata,
            request.original_filename,
            True,
            request.voice or "M1",
            request.voice or "M1",
            [],
        )
        if resolved.enabled:
            intro_spec = IntroOutroSpec(
                enabled=True,
                text=resolved.text,
                voice_spec=resolved.voice_spec,
                kind="intro",
            )

    # Outro
    if request.read_closing_outro:
        resolved = resolve_outro(
            metadata,
            request.original_filename,
            True,
            request.voice or "M1",
            request.voice or "M1",
            [],
        )
        if resolved.enabled:
            outro_spec = IntroOutroSpec(
                enabled=True,
                text=resolved.text,
                voice_spec=resolved.voice_spec,
                kind="outro",
            )

    return intro_spec, outro_spec


def _resolve_output_layout(request: ConversionRequest) -> OutputLayout:
    """Resolve output paths for the conversion."""
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
