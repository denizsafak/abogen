"""OPDS metadata normalization.

Normalizes metadata keys from various OPDS/Calibre sources into
a canonical set of overrides for the audiobook conversion pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from abogen.domain.metadata_helpers import expand_metadata_aliases


def normalize_opds_metadata(metadata_payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize OPDS/Calibre metadata into canonical override keys.

    Takes a metadata payload with various key aliases (e.g. 'series'/'series_name',
    'tags'/'keywords', 'authors'/'creator') and returns a dict with all
    concept aliases expanded.

    Args:
        metadata_payload: Raw metadata dict from OPDS/Calibre import.

    Returns:
        Dict with all canonical metadata key aliases expanded.
    """
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [str(item).strip() for item in value if item is not None]
            return ", ".join(part for part in parts if part)
        return str(value).strip()

    # Map OPDS-specific keys to common concept keys before expansion
    normalized_input: Dict[str, Any] = {}
    for key, value in metadata_payload.items():
        if value is None:
            continue
        key_lower = str(key).strip().lower()
        if not key_lower:
            continue
        text = _stringify(value)
        if not text:
            continue

        # Map OPDS-specific author aliases
        if key_lower in ("creator", "dc_creator"):
            normalized_input["author"] = text
        # Map OPDS-specific subtitle aliases
        elif key_lower in ("sub_title", "calibre_subtitle"):
            normalized_input["subtitle"] = text
        else:
            normalized_input[key_lower] = text

    return expand_metadata_aliases(normalized_input)
