"""ConversionRequest — normalized input for a conversion job.

This is NOT a WebUI Job and NOT a PyQt ConversionThread state.
It describes the TASK, not the UI.

UI adapters are responsible for converting their respective state
into a ConversionRequest before calling ConversionService.run().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from abogen.domain.enums import OutputFormat, SaveMode, SubtitleFormat, SubtitleMode


@dataclass
class ConversionRequest:
    """Normalized request for a conversion job.

    Only contains fields that describe the conversion task itself.
    UI-only fields (display, logging, user prompts) stay in adapters.
    """

    # --- Source ---
    source_path: Optional[Path] = None
    direct_text: Optional[str] = None
    original_filename: str = ""

    # --- TTS Settings ---
    language: str = "a"
    tts_provider: str = "kokoro"
    voice: str = "M1"
    voice_profile: Optional[str] = None
    speed: float = 1.0
    use_gpu: bool = True
    supertonic_total_steps: int = 5

    # --- Output Format ---
    output_format: OutputFormat = OutputFormat.WAV
    subtitle_mode: SubtitleMode = SubtitleMode.DISABLED
    subtitle_format: SubtitleFormat = SubtitleFormat.SRT
    max_subtitle_words: int = 50

    # --- Save Options ---
    save_mode: SaveMode = SaveMode.SAVE_NEXT_TO_INPUT
    output_folder: Optional[Path] = None
    save_chapters_separately: bool = False
    merge_chapters_at_end: bool = True
    separate_chapters_format: OutputFormat = OutputFormat.WAV
    save_as_project: bool = False

    # --- Timing ---
    silence_between_chapters: float = 2.0
    chapter_intro_delay: float = 0.0

    # --- Content Processing ---
    replace_single_newlines: bool = False
    read_title_intro: bool = False
    read_closing_outro: bool = True
    auto_prefix_chapter_titles: bool = True
    normalize_chapter_opening_caps: bool = False

    # --- Pronunciation / Normalization ---
    pronunciation_overrides: List[Dict[str, Any]] = field(default_factory=list)
    manual_overrides: List[Dict[str, Any]] = field(default_factory=list)
    heteronym_overrides: List[Dict[str, Any]] = field(default_factory=list)
    normalization_overrides: Optional[Dict[str, Any]] = None

    # --- Chapter/Chunk Configuration ---
    chapter_overrides: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    chunk_level: str = "paragraph"
    speaker_mode: str = "single"
    speakers: Dict[str, Any] = field(default_factory=dict)

    # --- Metadata ---
    metadata_tags: Dict[str, Any] = field(default_factory=dict)

    # --- Artifacts ---
    cover_image_path: Optional[Path] = None
    cover_image_mime: Optional[str] = None
    generate_epub3: bool = False
