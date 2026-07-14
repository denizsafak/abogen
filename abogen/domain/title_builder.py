from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .metadata_helpers import (
    ensure_sentence,
    extract_series_metadata,
    format_author_sentence,
    format_series_sentence,
    normalize_metadata_map,
)


def build_title_intro_text(
    metadata: Optional[Mapping[str, Any]],
    fallback_basename: str,
) -> str:
    """Build the title introduction text from metadata."""
    normalized = normalize_metadata_map(metadata)
    fallback_title = Path(fallback_basename).stem if fallback_basename else ""
    title = (
        normalized.get("title")
        or normalized.get("book_title")
        or normalized.get("album")
        or fallback_title
    )
    if not title:
        title = fallback_title
    subtitle = normalized.get("subtitle") or normalized.get("sub_title")
    if subtitle and title and subtitle.casefold() == title.casefold():
        subtitle = ""

    author_value = ""
    for candidate in ("artist", "album_artist", "author", "authors", "writer", "composer"):
        value = normalized.get(candidate)
        if value:
            author_value = value
            break

    series_name, series_number = extract_series_metadata(normalized)
    series_sentence = format_series_sentence(series_name, series_number)

    sentences: List[str] = []
    if series_sentence:
        sentences.append(ensure_sentence(series_sentence))
    if title:
        sentences.append(ensure_sentence(title))
    if subtitle:
        sentences.append(ensure_sentence(subtitle))
    author_sentence = format_author_sentence(author_value)
    if author_sentence:
        sentences.append(ensure_sentence(author_sentence))
    return " ".join(sentences).strip()


def build_outro_text(
    metadata: Optional[Mapping[str, Any]],
    fallback_basename: str,
) -> str:
    """Build the outro/closing text from metadata."""
    normalized = normalize_metadata_map(metadata)
    fallback_title = Path(fallback_basename).stem if fallback_basename else ""
    title = (
        normalized.get("title")
        or normalized.get("book_title")
        or normalized.get("album")
        or fallback_title
    )
    author_value = ""
    for candidate in ("authors", "author", "album_artist", "artist", "writer", "composer"):
        value = normalized.get(candidate)
        if value:
            author_value = value
            break
    author_sentence = format_author_sentence(author_value)
    authors_fragment = (
        author_sentence[3:].strip() if author_sentence.lower().startswith("by ") else author_sentence.strip()
    )

    if title and authors_fragment:
        closing_line = f"The end of {title} from {authors_fragment}"
    elif title:
        closing_line = f"The end of {title}"
    elif authors_fragment:
        closing_line = f"The end from {authors_fragment}"
    else:
        closing_line = "The end"

    series_name, series_number = extract_series_metadata(normalized)
    series_sentence = format_series_sentence(series_name, series_number)

    sentences: List[str] = [ensure_sentence(closing_line)]
    if series_sentence:
        sentences.append(ensure_sentence(series_sentence))

    return " ".join(sentence for sentence in sentences if sentence).strip()