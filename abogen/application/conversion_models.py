"""Core models for conversion planning.

These dataclasses represent the structured plan for a conversion job.
They are UI-agnostic and describe WHAT to convert, not HOW to do it.

The planning flow:
    ConversionRequest -> ConversionPlan -> ConversionResult

    ConversionPlan contains:
    - ChapterPlan[]: chapters with their segments
    - SegmentPlan[]: individual text segments with voice specs
    - OutputLayout: where to write outputs
    - IntroOutroSpec: optional intro/outro
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from abogen.application.conversion_request import ConversionRequest


@dataclass
class SegmentPlan:
    """A single text segment with its voice specification.

    This is the unified model for:
    - Regular chapter body text
    - PyQt voice markers (<<VOICE:F1>>)
    - WebUI chunks with per-chunk voice/speaker
    - Intro/outro text
    - Chapter headings
    """

    text: str
    voice_spec: str
    kind: str = "body"  # intro, heading, body, outro
    speaker_id: str = "narrator"
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    level: Optional[str] = None  # chunk level (paragraph, sentence, etc.)
    source: str = "chapter"  # chapter, voice_marker, chunk


@dataclass
class ChapterPlan:
    """A chapter with its metadata and segments."""

    index: int
    title: str
    original_title: str
    body_text: str
    segments: List[SegmentPlan]
    voice_spec: str  # default voice for this chapter


@dataclass
class OutputLayout:
    """Resolved output paths for a conversion job."""

    parent_dir: Path
    merged_path: Optional[Path] = None
    chapter_dir: Optional[Path] = None
    project_root: Optional[Path] = None
    audio_dir: Optional[Path] = None
    subtitle_dir: Optional[Path] = None
    metadata_dir: Optional[Path] = None


@dataclass
class IntroOutroSpec:
    """Intro/outro specification with resolved text and voice."""

    enabled: bool = False
    text: str = ""
    voice_spec: str = ""
    kind: str = "intro"  # intro or outro


@dataclass
class ConversionPlan:
    """Complete plan for a conversion job.

    This is the output of the planning phase and input to the executor.
    """

    request: ConversionRequest
    metadata: Dict[str, Any]
    chapters: List[ChapterPlan]
    intro: Optional[IntroOutroSpec] = None
    outro: Optional[IntroOutroSpec] = None
    output_layout: Optional[OutputLayout] = None
