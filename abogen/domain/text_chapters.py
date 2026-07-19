"""Chapter parsing from raw text.

Provides a unified function for splitting text by chapter markers,
used by both WebUI and PyQt conversion runners.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from abogen.subtitle_utils import clean_text


_CHAPTER_MARKER_RE = re.compile(r"<<CHAPTER_MARKER:(.*?)>>", re.IGNORECASE)


def parse_chapters_from_text(
    text: str,
    default_title: str = "text",
    clean: bool = True,
) -> List[Tuple[str, str]]:
    """Split raw text into chapters using chapter marker patterns.

    Preserves content before the first marker as "Introduction" if present.
    Optionally applies clean_text() to each chapter segment.

    Args:
        text: Raw text possibly containing <<CHAPTER_MARKER:Title>> markers.
        default_title: Fallback title when no markers are found.
        clean: Whether to apply clean_text() to each segment.

    Returns:
        List of (title, text) tuples.
    """
    matches = list(_CHAPTER_MARKER_RE.finditer(text))
    if not matches:
        cleaned = clean_text(text) if clean else text
        return [(default_title, cleaned)]

    chapters: List[Tuple[str, str]] = []

    # Preserve content before first marker as "Introduction"
    first_start = matches[0].start()
    if first_start > 0:
        intro_text = text[:first_start].strip()
        if intro_text:
            chapters.append(("Introduction", clean_text(intro_text) if clean else intro_text))

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chapter_name = match.group(1).strip() or default_title
        chapter_text = text[start:end].strip()
        if clean:
            chapter_text = clean_text(chapter_text)
        chapters.append((chapter_name, chapter_text))

    return chapters
