"""ConversionRequest — normalized input for a conversion job.

This is NOT a WebUI Job and NOT a PyQt ConversionThread state.
It describes the TASK, not the UI.

UI adapters are responsible for converting their respective state
into a ConversionRequest before calling ConversionService.run().
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from abogen.domain.enums import Language, OutputFormat, SaveMode, SubtitleFormat, SubtitleMode


class ConversionRequestError(ValueError):
    """Raised when ConversionRequest has invalid field values."""


# Numeric field constraints: attr -> (min, max)
_NUMERIC_CONSTRAINTS: dict[str, tuple[float, float | None]] = {
    "max_subtitle_words": (1, 500),
    "speed": (0.5, 3.0),
    "supertonic_total_steps": (2, 15),
    "silence_between_chapters": (0.0, None),
    "chapter_intro_delay": (0.0, None),
}

# Enum-like fields that must be in allowed set
_ENUM_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "chunk_level": ("paragraph", "sentence"),
    "speaker_mode": ("single", "multi"),
}


@dataclass
class ConversionRequest:
    """Normalized request for a conversion job.

    Only contains fields that describe the conversion task itself.
    UI-only fields (display, logging, user prompts) stay in adapters.

    Validation runs on creation via __post_init__:
    - None values → replaced with field default (from declaration)
    - Numeric fields → clamped to valid range
    - String enums → validated against allowed set
    """

    # --- Source ---
    source_path: Optional[Path] = None
    direct_text: Optional[str] = None
    original_filename: str = ""

    # --- TTS Settings ---
    language: Language = Language.EN_US
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

    def __post_init__(self) -> None:
        """Resolve None → default, then validate and clamp."""
        _apply_none_defaults(self)
        if not self.tts_provider:
            self.tts_provider = "kokoro"
        _clamp_numerics(self)
        _validate_enums(self)


def _apply_none_defaults(obj: ConversionRequest) -> None:
    """Replace None values with field defaults from dataclass declaration."""
    for f in dataclasses.fields(obj):
        if getattr(obj, f.name) is not None:
            continue
        if f.default is not dataclasses.MISSING:
            setattr(obj, f.name, f.default)
        elif f.default_factory is not dataclasses.MISSING:
            setattr(obj, f.name, f.default_factory())


def _clamp_numerics(obj: ConversionRequest) -> None:
    """Clamp numeric fields to valid ranges."""
    for attr, (min_v, max_v) in _NUMERIC_CONSTRAINTS.items():
        val = getattr(obj, attr)
        if val is None:
            continue
        if not isinstance(val, (int, float)):
            raise ConversionRequestError(
                f"{attr} must be a number, got {type(val).__name__}"
            )
        clamped = max(min_v, float(val))
        if max_v is not None:
            clamped = min(max_v, clamped)
        setattr(obj, attr, clamped)


def _validate_enums(obj: ConversionRequest) -> None:
    """Validate string enum fields against allowed values."""
    for attr, allowed in _ENUM_CONSTRAINTS.items():
        val = getattr(obj, attr)
        if val not in allowed:
            raise ConversionRequestError(
                f"{attr} must be one of {allowed}, got {val!r}"
            )
