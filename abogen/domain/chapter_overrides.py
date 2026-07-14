from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from abogen.text_extractor import ExtractedChapter


@dataclass
class ChapterOverrideResult:
    selected: List[ExtractedChapter]
    metadata_updates: Dict[str, str]
    diagnostics: List[str]


def apply_chapter_overrides(
    extracted: List[ExtractedChapter],
    overrides: List[Dict[str, Any]],
    coerce_truthy_fn,
) -> ChapterOverrideResult:
    if not overrides:
        return ChapterOverrideResult(selected=[], metadata_updates={}, diagnostics=[])

    selected: List[ExtractedChapter] = []
    metadata_updates: Dict[str, str] = {}
    diagnostics: List[str] = []

    for position, payload in enumerate(overrides):
        if not isinstance(payload, dict):
            diagnostics.append(
                f"Skipped chapter override at position {position + 1}: unsupported payload type {type(payload).__name__}."
            )
            continue

        enabled = coerce_truthy_fn(payload.get("enabled", True))
        payload["enabled"] = enabled
        if not enabled:
            continue

        metadata_payload = payload.get("metadata") or {}
        if isinstance(metadata_payload, dict):
            for key, value in metadata_payload.items():
                if value is None:
                    continue
                metadata_updates[str(key)] = str(value)

        base: Optional[ExtractedChapter] = None
        idx_candidate = payload.get("index")
        idx_normalized: Optional[int] = None
        if isinstance(idx_candidate, int):
            idx_normalized = idx_candidate
        elif isinstance(idx_candidate, str):
            try:
                idx_normalized = int(idx_candidate)
            except ValueError:
                idx_normalized = None
        if idx_normalized is not None and 0 <= idx_normalized < len(extracted):
            base = extracted[idx_normalized]
            payload["index"] = idx_normalized

        if base is None:
            source_title = payload.get("source_title")
            if isinstance(source_title, str):
                base = next((chapter for chapter in extracted if chapter.title == source_title), None)

        if base is None:
            candidate_title = payload.get("title")
            if isinstance(candidate_title, str):
                base = next((chapter for chapter in extracted if chapter.title == candidate_title), None)

        text_override = payload.get("text")
        if text_override is not None:
            text_value = str(text_override)
        elif base is not None:
            text_value = base.text
        else:
            diagnostics.append(
                f"Skipped chapter override at position {position + 1}: no text provided and no matching source chapter found."
            )
            continue

        title_override = payload.get("title")
        if title_override is not None:
            title_value = str(title_override)
        elif base is not None:
            title_value = base.title
        else:
            title_value = f"Chapter {position + 1}"

        if base and not payload.get("source_title"):
            payload["source_title"] = base.title

        payload["title"] = title_value
        payload["text"] = text_value
        payload["characters"] = len(text_value)
        payload.setdefault("order", payload.get("order", position))

        selected.append(ExtractedChapter(title=title_value, text=text_value))

    return ChapterOverrideResult(selected=selected, metadata_updates=metadata_updates, diagnostics=diagnostics)