"""Chapter selection helpers for the application layer.

Builds chapter payloads with smart defaults (preselection based on
supplement score) and character counts. Used by both WebUI and PyQt.
"""

from __future__ import annotations

from typing import Any, Dict, List

from abogen.domain.chapter_classification import (
    ensure_at_least_one_chapter_enabled,
    should_preselect_chapter,
)
from abogen.domain.text_utils import calculate_text_length


def build_chapter_payload(
    chapters: List[Any],
    source_name: str = "",
) -> List[Dict[str, Any]]:
    """Build a chapter payload with preselection and character counts.

    Args:
        chapters: List of chapter-like objects with ``title`` and ``text`` attributes.
        source_name: Fallback title for the placeholder chapter when *chapters* is empty.

    Returns:
        List of chapter dicts ready for ``PendingJob.chapters`` or ``ChapterChunkConfig``.
    """
    total = len(chapters)
    payload: List[Dict[str, Any]] = []

    for index, chapter in enumerate(chapters):
        title = getattr(chapter, "title", "") or ""
        text = getattr(chapter, "text", "") or ""
        enabled = should_preselect_chapter(title, text, index, total)
        payload.append(
            {
                "id": f"{index:04d}",
                "index": index,
                "title": title,
                "text": text,
                "characters": calculate_text_length(text),
                "enabled": enabled,
            }
        )

    if not payload:
        payload.append(
            {
                "id": "0000",
                "index": 0,
                "title": source_name,
                "text": "",
                "characters": 0,
                "enabled": True,
            }
        )

    ensure_at_least_one_chapter_enabled(payload)
    return payload
