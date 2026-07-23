"""Feature config objects for ConversionRequest.

Each config object groups parameters for a specific feature.
If the object is None, the feature is disabled.

This keeps ConversionRequest clean: no boolean flags for feature toggles,
no scattered parameters across unrelated fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class WordSubstitutionConfig:
    """Word substitution settings.

    When present on ConversionRequest, word substitution is applied
    to the source text before chapter parsing.
    """
    substitutions_list: str = ""
    case_sensitive: bool = False
    replace_caps: bool = False
    replace_numerals: bool = False
    fix_punctuation: bool = False


@dataclass(frozen=True)
class SubtitleInputConfig:
    """Subtitle file input settings.

    When present on ConversionRequest, the source is treated as a
    subtitle file (.srt/.ass/.vtt) or timestamp text, and the
    subtitle-to-audio pipeline is used instead of normal text conversion.
    """
    is_timestamp_text: bool = False


@dataclass(frozen=True)
class Epub3ExportConfig:
    """EPUB3 export settings.

    When present on ConversionRequest, an EPUB3 package with
    synchronized audio narration is generated after conversion.
    """
    book_id: str = ""


@dataclass(frozen=True)
class PronunciationConfig:
    """Pronunciation and normalization override settings.

    Groups all pronunciation/heteronym/normalization overrides
    that are compiled into a TTSContext before conversion.
    """
    pronunciation_overrides: List[Dict[str, Any]] = field(default_factory=list)
    manual_overrides: List[Dict[str, Any]] = field(default_factory=list)
    heteronym_overrides: List[Dict[str, Any]] = field(default_factory=list)
    normalization_overrides: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ChapterChunkConfig:
    """Chapter and chunk configuration.

    Groups chapter overrides, chunk data, and speaker settings
    used by the planner to build segments.
    """
    chapter_overrides: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    chunk_level: str = "paragraph"
    speaker_mode: str = "single"
    speakers: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _VALID_CHUNK_LEVELS = ("paragraph", "sentence")
        _VALID_SPEAKER_MODES = ("single", "multi")
        if self.chunk_level not in _VALID_CHUNK_LEVELS:
            raise ValueError(
                f"chunk_level must be one of {_VALID_CHUNK_LEVELS}, got {self.chunk_level!r}"
            )
        if self.speaker_mode not in _VALID_SPEAKER_MODES:
            raise ValueError(
                f"speaker_mode must be one of {_VALID_SPEAKER_MODES}, got {self.speaker_mode!r}"
            )
