"""Domain config types — shared contracts for domain functions.

These dataclasses group parameters that domain functions receive.
Domain defines them, app layer fills them.

Why here (domain) and not application:
- build_tts_context() is in domain → needs PronunciationConfig
- make_subtitle_writer() is in infrastructure → needs SubtitleConfig
- embed_m4b_metadata() is in infrastructure → needs CoverConfig
- Domain should not depend on application layer (DIP)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from abogen.domain.enums import SubtitleFormat, SubtitleMode


@dataclass(frozen=True)
class PronunciationConfig:
    """Pronunciation and normalization override settings.

    Used by build_tts_context() to compile override rules.
    """
    pronunciation_overrides: List[Dict[str, Any]] = field(default_factory=list)
    manual_overrides: List[Dict[str, Any]] = field(default_factory=list)
    heteronym_overrides: List[Dict[str, Any]] = field(default_factory=list)
    normalization_overrides: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SubtitleConfig:
    """Subtitle output settings.

    Used by make_subtitle_writer() and process_and_write_subtitles().
    """
    mode: SubtitleMode = SubtitleMode.DISABLED
    format: SubtitleFormat = SubtitleFormat.SRT
    max_words: int = 50


@dataclass(frozen=True)
class CoverConfig:
    """Cover image settings.

    Used by embed_m4b_metadata() and build_epub3_package().
    """
    path: Optional[Path] = None
    mime: Optional[str] = None
