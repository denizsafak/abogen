from __future__ import annotations

import json
import math
import re
from pathlib import Path
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


_PEOPLE_SPLIT_RE = re.compile(r"[;,/&]|\band\b", re.IGNORECASE)
_LIST_SPLIT_RE = re.compile(r"[;,\n]")
_SERIES_SEQUENCE_TAG_KEYS: Tuple[str, ...] = (
    "series_index",
    "series_position",
    "series_sequence",
    "series_number",
    "seriesnumber",
    "book_number",
    "booknumber",
)


def normalize_metadata_casefold(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not values:
        return normalized
    for key, value in values.items():
        if value is None:
            continue
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        if isinstance(value, (list, tuple, set)):
            normalized[key_text] = value
        else:
            text = str(value).strip()
            if text:
                normalized[key_text] = text
    return normalized


def split_people_field(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        results: List[str] = []
        for item in raw:
            results.extend(split_people_field(item))
        return results
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = [_token.strip() for _token in _PEOPLE_SPLIT_RE.split(text) if _token.strip()]
    seen: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def split_simple_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        results: List[str] = []
        for item in raw:
            results.extend(split_simple_list(item))
        return results
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = [_token.strip() for _token in _LIST_SPLIT_RE.split(text) if _token.strip()]
    seen: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def first_nonempty(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            if not items:
                continue
            value = items[0]
        text = str(value).strip()
        if text:
            return text
    return None


def extract_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if 0 < parsed < 3000:
        return parsed
    return None


def normalize_series_sequence(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return None
        text = str(raw)
    else:
        text = str(raw).strip()
    if not text:
        return None
    candidate = text.replace(",", ".")
    match = _SERIES_NUMBER_RE.search(candidate)
    if not match:
        return None
    normalized = match.group(0)
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
        if not normalized:
            normalized = "0"
        return normalized
    try:
        return str(int(normalized))
    except ValueError:
        cleaned = normalized.lstrip("0")
        return cleaned or "0"


def build_audiobookshelf_metadata(
    tags: Mapping[str, Any],
    *,
    language: str = "",
    filename: str = "",
) -> Dict[str, Any]:
    normalized = normalize_metadata_casefold(tags)
    title = first_nonempty(
        normalized.get("title"),
        normalized.get("book_title"),
        normalized.get("name"),
        normalized.get("album"),
        filename,
    )
    authors = split_people_field(
        normalized.get("authors")
        or normalized.get("author")
        or normalized.get("album_artist")
        or normalized.get("artist")
    )
    narrators = split_people_field(normalized.get("narrators") or normalized.get("narrator"))
    description = first_nonempty(
        normalized.get("description"), normalized.get("summary"), normalized.get("comment")
    )
    genres = split_simple_list(normalized.get("genre"))
    keywords = split_simple_list(normalized.get("tags") or normalized.get("keywords"))
    lang = first_nonempty(normalized.get("language"), normalized.get("lang")) or language or ""
    series_name = first_nonempty(
        normalized.get("series"),
        normalized.get("series_name"),
        normalized.get("seriesname"),
        normalized.get("series_title"),
        normalized.get("seriestitle"),
    )

    series_sequence = None
    for key in _SERIES_SEQUENCE_TAG_KEYS:
        raw_value = normalized.get(key)
        seq = normalize_series_sequence(raw_value)
        if seq:
            series_sequence = seq
            break
    if not series_name:
        series_sequence = None

    data: Dict[str, Any] = {
        "title": title,
        "subtitle": normalized.get("subtitle"),
        "authors": authors,
        "narrators": narrators,
        "description": description,
        "publisher": normalized.get("publisher"),
        "genres": genres,
        "tags": keywords,
        "language": lang,
        "publishedYear": extract_year(
            normalized.get("published")
            or normalized.get("publication_year")
            or normalized.get("date")
            or normalized.get("year")
        ),
        "seriesName": series_name,
        "seriesSequence": series_sequence,
        "isbn": first_nonempty(normalized.get("isbn"), normalized.get("asin")),
    }
    published_date = first_nonempty(
        normalized.get("published"), normalized.get("publication_date"), normalized.get("date")
    )
    if published_date:
        data["publishedDate"] = published_date

    rating_text = first_nonempty(normalized.get("rating"), normalized.get("my_rating"))
    if rating_text:
        try:
            data["rating"] = float(str(rating_text).strip())
        except ValueError:
            pass
        rating_max_text = first_nonempty(
            normalized.get("rating_max"), normalized.get("rating_scale")
        )
        if rating_max_text:
            try:
                data["ratingMax"] = float(str(rating_max_text).strip())
            except ValueError:
                pass

    cleaned: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        cleaned[key] = value
    return cleaned


def load_audiobookshelf_chapters(
    metadata_path: Path,
) -> Optional[List[Dict[str, Any]]]:
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        return None
    cleaned: List[Dict[str, Any]] = []
    for entry in chapters:
        if not isinstance(entry, Mapping):
            continue
        title = first_nonempty(entry.get("title"), entry.get("original_title"))
        start = entry.get("start")
        end = entry.get("end")
        if title and start is not None and end is not None:
            cleaned.append({"title": str(title), "start": start, "end": end})
    return cleaned or None
