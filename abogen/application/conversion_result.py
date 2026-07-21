"""ConversionResult — output of a successful conversion.

Returned by ConversionService.run() after all synthesis and finalization.
UI adapters consume this to update their respective state (Job, signals, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ConversionResult:
    """Output of a successful conversion job."""

    # --- Primary outputs ---
    audio_path: Optional[Path] = None
    subtitle_paths: List[Path] = field(default_factory=list)
    chapter_paths: List[Path] = field(default_factory=list)

    # --- Markers (for metadata/audiobookshelf) ---
    chapter_markers: List[Dict[str, Any]] = field(default_factory=list)
    chunk_markers: List[Dict[str, Any]] = field(default_factory=list)

    # --- Metadata ---
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- Artifacts ---
    artifacts: Dict[str, Path] = field(default_factory=dict)
    project_root: Optional[Path] = None
    epub_path: Optional[Path] = None

    # --- Stats ---
    total_chapters: int = 0
    total_segments: int = 0
    total_characters: int = 0


@dataclass
class ConversionError:
    """Error information when conversion fails."""

    message: str
    details: Optional[str] = None
    is_cancelled: bool = False
