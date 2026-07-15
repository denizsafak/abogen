"""Chunk processing utilities.

Functions for grouping chunks, recording override usage, and selecting
text for TTS synthesis.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Mapping, Optional

from abogen.pronunciation_store import increment_usage


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def group_chunks_by_chapter(chunks: Iterable[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for entry in chunks or []:
        if not isinstance(entry, dict):
            continue
        try:
            chapter_index = int(entry.get("chapter_index", 0))
        except (TypeError, ValueError):
            chapter_index = 0
        grouped[chapter_index].append(dict(entry))

    for chapter_index, items in grouped.items():
        items.sort(key=lambda payload: safe_int(payload.get("chunk_index")))

    return grouped


def record_override_usage(
    job: Any,
    usage_counter: Mapping[str, int],
    token_map: Mapping[str, str],
) -> None:
    if not usage_counter:
        return

    language = getattr(job, "language", "") or "a"
    for normalized, amount in usage_counter.items():
        if amount <= 0:
            continue
        token_value = token_map.get(normalized, normalized)
        try:
            increment_usage(language=language, token=token_value, amount=int(amount))
        except Exception:  # pragma: no cover - defensive logging
            job.add_log(f"Failed to record usage for override {token_value}", level="warning")


def chunk_text_for_tts(entry: Mapping[str, Any]) -> str:
    """Choose the best source text for synthesis.

    We must prefer the raw chunk text (``text`` / ``original_text``) so
    manual/pronunciation overrides can match against the original tokens
    (e.g. censored words like ``Unfu*k``).  ``normalized_text`` may have
    already been run through ``normalize_for_pipeline``, which can remove
    punctuation and prevent overrides from triggering.
    """

    if not isinstance(entry, Mapping):
        return ""
    return str(
        entry.get("text")
        or entry.get("original_text")
        or entry.get("normalized_text")
        or ""
    ).strip()
