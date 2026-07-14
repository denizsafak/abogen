from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from abogen.text_extractor import ExtractedChapter


_SIGNIFICANT_LENGTH_THRESHOLDS: Dict[str, int] = {"epub": 1000, "markdown": 500}
_MIN_SHORT_CONTENT: Dict[str, int] = {"epub": 240, "markdown": 160}
_STRUCTURAL_KEYWORDS = (
    "preface",
    "prologue",
    "introduction",
    "foreword",
    "epilogue",
    "afterword",
    "appendix",
    "acknowledgment",
    "acknowledgement",
)
_STRUCTURAL_MIN_LENGTH = 120
_MAX_SHORT_CHAPTERS = 2


@dataclass
class ChapterFilterResult:
    kept: List[ExtractedChapter]
    skipped: List[Tuple[str, int]]


def infer_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return "epub"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".txt":
        return "text"
    return suffix.lstrip(".") or "text"


def looks_structural(title: str) -> bool:
    lowered = title.strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in _STRUCTURAL_KEYWORDS)


def chapter_label(file_type: str) -> str:
    return "chapters" if file_type.lower() in {"epub", "markdown"} else "pages"


def auto_select_relevant_chapters(
    chapters: List[ExtractedChapter],
    file_type: str,
) -> ChapterFilterResult:
    if not chapters:
        return ChapterFilterResult(kept=[], skipped=[])

    normalized = file_type.lower()
    threshold = _SIGNIFICANT_LENGTH_THRESHOLDS.get(normalized, 0)
    min_short = _MIN_SHORT_CONTENT.get(normalized, 0)

    kept: List[ExtractedChapter] = []
    skipped: List[Tuple[str, int]] = []
    short_kept = 0

    for chapter in chapters:
        stripped = chapter.text.strip()
        length = len(stripped)
        if length == 0:
            skipped.append((chapter.title, length))
            continue

        keep = False
        if threshold == 0:
            keep = True
        elif length >= threshold:
            keep = True
        elif not kept:
            keep = True
        elif min_short and length >= min_short and short_kept < _MAX_SHORT_CHAPTERS:
            keep = True
            short_kept += 1
        elif looks_structural(chapter.title) and length >= _STRUCTURAL_MIN_LENGTH:
            keep = True

        if keep:
            kept.append(chapter)
        else:
            skipped.append((chapter.title, length))

    if kept:
        return ChapterFilterResult(kept=kept, skipped=skipped)

    longest_idx = None
    longest_length = 0
    for idx, chapter in enumerate(chapters):
        stripped = chapter.text.strip()
        if stripped and len(stripped) > longest_length:
            longest_length = len(stripped)
            longest_idx = idx

    if longest_idx is not None:
        longest = chapters[longest_idx]
        fallback_skipped = [
            (chapter.title, len(chapter.text.strip()))
            for idx, chapter in enumerate(chapters)
            if idx != longest_idx and chapter.text.strip()
        ]
        return ChapterFilterResult(kept=[longest], skipped=fallback_skipped)

    return ChapterFilterResult(kept=[], skipped=skipped)


def update_metadata_for_chapter_count(
    metadata: Dict[str, Any], count: int, file_type: str
) -> None:
    if not metadata or count <= 0:
        return

    label = "Chapters" if file_type.lower() in {"epub", "markdown"} else "Pages"
    metadata["chapter_count"] = str(count)

    pattern = re.compile(r"\(\d+\s+(Chapters?|Pages?)\)")
    replacement = f"({count} {label})"
    for key in ("album", "ALBUM"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        metadata[key] = pattern.sub(replacement, value)
