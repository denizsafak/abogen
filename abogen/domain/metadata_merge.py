from __future__ import annotations

from typing import Any, Dict, Optional


def merge_metadata(
    extracted: Optional[Dict[str, Any]],
    overrides: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    if extracted:
        for key, value in extracted.items():
            if value is None:
                continue
            merged[str(key)] = str(value)
    if overrides:
        for key, value in overrides.items():
            key_str = str(key)
            if value is None:
                merged.pop(key_str, None)
            else:
                merged[key_str] = str(value)
    return merged