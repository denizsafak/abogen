"""OPDS metadata normalization.

Normalizes metadata keys from various OPDS/Calibre sources into
a canonical set of overrides for the audiobook conversion pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping


def normalize_opds_metadata(metadata_payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize OPDS/Calibre metadata into canonical override keys.

    Takes a metadata payload with various key aliases (e.g. 'series'/'series_name',
    'tags'/'keywords', 'authors'/'creator') and returns a dict with canonical
    keys set.

    Args:
        metadata_payload: Raw metadata dict from OPDS/Calibre import.

    Returns:
        Dict with canonical metadata keys (series, series_index, tags,
        description, subtitle, publisher, authors).
    """
    metadata_overrides: Dict[str, Any] = {}

    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item is not None]
            return ", ".join(part for part in parts if part)
        return str(value).strip()

    raw_series = metadata_payload.get("series") or metadata_payload.get("series_name")
    series_name = str(raw_series or "").strip()
    if series_name:
        metadata_overrides["series"] = series_name
        metadata_overrides.setdefault("series_name", series_name)

    series_index_value = (
        metadata_payload.get("series_index")
        or metadata_payload.get("series_position")
        or metadata_payload.get("series_sequence")
        or metadata_payload.get("book_number")
    )
    if series_index_value is not None:
        series_index_text = str(series_index_value).strip()
        if series_index_text:
            metadata_overrides.setdefault("series_index", series_index_text)
            metadata_overrides.setdefault("series_position", series_index_text)
            metadata_overrides.setdefault("series_sequence", series_index_text)
            metadata_overrides.setdefault("book_number", series_index_text)

    tags_value = metadata_payload.get("tags") or metadata_payload.get("keywords")
    if tags_value:
        tags_text = _stringify(tags_value)
        if tags_text:
            metadata_overrides.setdefault("tags", tags_text)
            metadata_overrides.setdefault("keywords", tags_text)
            metadata_overrides.setdefault("genre", tags_text)

    description_value = metadata_payload.get("description") or metadata_payload.get("summary")
    if description_value:
        description_text = _stringify(description_value)
        if description_text:
            metadata_overrides.setdefault("description", description_text)
            metadata_overrides.setdefault("summary", description_text)

    subtitle_value = (
        metadata_payload.get("subtitle")
        or metadata_payload.get("sub_title")
        or metadata_payload.get("calibre_subtitle")
    )
    if subtitle_value:
        subtitle_text = _stringify(subtitle_value)
        if subtitle_text:
            metadata_overrides.setdefault("subtitle", subtitle_text)

    publisher_value = metadata_payload.get("publisher")
    if publisher_value:
        publisher_text = _stringify(publisher_value)
        if publisher_text:
            metadata_overrides.setdefault("publisher", publisher_text)

    authors_value = (
        metadata_payload.get("authors")
        or metadata_payload.get("author")
        or metadata_payload.get("creator")
        or metadata_payload.get("dc_creator")
    )
    if authors_value:
        authors_text = _stringify(authors_value)
        if authors_text:
            metadata_overrides.setdefault("authors", authors_text)
            metadata_overrides.setdefault("author", authors_text)

    return metadata_overrides
