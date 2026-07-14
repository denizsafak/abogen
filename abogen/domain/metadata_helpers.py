from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple


_SERIES_NAME_KEYS = (
    "series",
    "series_name",
    "series_title",
)
_SERIES_NUMBER_KEYS = (
    "series_index",
    "series_position",
    "series_sequence",
    "book_number",
    "series_number",
)
_SERIES_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def normalize_metadata_map(values: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    if not values:
        return normalized
    for key, value in values.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        normalized[str(key).casefold()] = text
    return normalized


def format_author_sentence(raw: Optional[str]) -> str:
    if raw is None:
        return ""
    normalized = str(raw).strip()
    if not normalized:
        return ""
    lowered = normalized.casefold()
    if lowered in {"unknown", "various"}:
        return ""

    working = normalized.replace("&", " and ")
    segments = [segment.strip() for segment in working.split(",") if segment.strip()]
    tokens: List[str] = []

    if segments:
        for segment in segments:
            parts = [part.strip() for part in re.split(r"\band\b", segment, flags=re.IGNORECASE) if part.strip()]
            if parts:
                tokens.extend(parts)
            else:
                tokens.append(segment)
    else:
        parts = [part.strip() for part in re.split(r"\band\b", working, flags=re.IGNORECASE) if part.strip()]
        tokens.extend(parts or [normalized])

    cleaned = [token for token in tokens if token and token.casefold() not in {"unknown", "various"}]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"By {cleaned[0]}"
    if len(cleaned) == 2:
        return f"By {cleaned[0]} and {cleaned[1]}"
    return f"By {', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def ensure_sentence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] in ".!?":
        return cleaned
    return f"{cleaned}."


def normalize_series_number(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace(",", ".")
    if candidate.replace(".", "", 1).isdigit():
        if "." in candidate:
            normalized = candidate.rstrip("0").rstrip(".")
            return normalized or "0"
        try:
            return str(int(candidate))
        except ValueError:
            pass
    match = _SERIES_NUMBER_RE.search(candidate)
    if not match:
        return None
    normalized = match.group(0)
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
        return normalized or "0"
    try:
        return str(int(normalized))
    except ValueError:
        return normalized


def extract_series_metadata(values: Mapping[str, str]) -> Tuple[Optional[str], Optional[str]]:
    series_name: Optional[str] = None
    for key in _SERIES_NAME_KEYS:
        raw = values.get(key)
        if raw:
            cleaned = str(raw).strip()
            if cleaned:
                series_name = cleaned
                break

    series_number: Optional[str] = None
    for key in _SERIES_NUMBER_KEYS:
        raw = values.get(key)
        if raw is None:
            continue
        normalized = normalize_series_number(raw)
        if normalized:
            series_number = normalized
            break

    return series_name, series_number


def format_series_sentence(series_name: Optional[str], series_number: Optional[str]) -> str:
    if not series_name or not series_number:
        return ""
    name = series_name.strip()
    number = series_number.strip()
    if not name or not number:
        return ""
    article = "the " if not name.lower().startswith("the ") else ""
    phrase = f"Book {number} of {article}{name}"
    return re.sub(r"\s+", " ", phrase).strip()
