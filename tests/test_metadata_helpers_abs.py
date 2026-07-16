"""Tests for domain/metadata_helpers.py Audiobookshelf helpers."""
from abogen.domain.metadata_helpers import (
    normalize_metadata_casefold,
    split_people_field,
    split_simple_list,
    first_nonempty,
    extract_year,
    normalize_series_sequence,
    build_audiobookshelf_metadata,
    load_audiobookshelf_chapters,
)


# --- normalize_metadata_casefold ---

def test_normalize_metadata_casefold_basic():
    result = normalize_metadata_casefold({"Title": "  Hello  ", "Author": None, "": "skip"})
    assert result == {"title": "Hello", "author": ""} or result == {"title": "Hello"}


def test_normalize_metadata_casefold_preserves_lists():
    result = normalize_metadata_casefold({"tags": ["a", "b"]})
    assert result["tags"] == ["a", "b"]


# --- split_people_field ---

def test_split_people_field_single():
    assert split_people_field("J.K. Rowling") == ["J.K. Rowling"]


def test_split_people_field_multiple():
    result = split_people_field("Tolkien, Lewis & Martin")
    assert "Tolkien" in result
    assert "Lewis" in result
    assert "Martin" in result


def test_split_people_field_deduplicates():
    result = split_people_field("Tolkien, tolkien, TOLKIEN")
    assert len(result) == 1


def test_split_people_field_none():
    assert split_people_field(None) == []


def test_split_people_field_list():
    result = split_people_field(["Author A", "Author B"])
    assert result == ["Author A", "Author B"]


# --- split_simple_list ---

def test_split_simple_list_basic():
    result = split_simple_list("fantasy, sci-fi; thriller")
    assert "fantasy" in result
    assert "sci-fi" in result
    assert "thriller" in result


def test_split_simple_list_none():
    assert split_simple_list(None) == []


# --- first_nonempty ---

def test_first_nonempty_basic():
    assert first_nonempty(None, "", "hello") == "hello"


def test_first_nonempty_first_wins():
    assert first_nonempty("first", "second") == "first"


def test_first_nonempty_none():
    assert first_nonempty(None, None) is None


def test_first_nonempty_list():
    assert first_nonempty(None, ["a", "b"]) == "a"


# --- extract_year ---

def test_extract_year_full_date():
    assert extract_year("Published on 2023-05-15") == 2023


def test_extract_year_plain():
    assert extract_year("2020") == 2020


def test_extract_year_none():
    assert extract_year(None) is None


def test_extract_year_invalid():
    assert extract_year("no year here") is None


# --- normalize_series_sequence ---

def test_normalize_series_sequence_int():
    assert normalize_series_sequence(3) == "3"


def test_normalize_series_sequence_float():
    assert normalize_series_sequence(2.5) == "2.5"


def test_normalize_series_sequence_string():
    assert normalize_series_sequence("  12  ") == "12"


def test_normalize_series_sequence_comma():
    assert normalize_series_sequence("1,5") == "1.5"


def test_normalize_series_sequence_none():
    assert normalize_series_sequence(None) is None


def test_normalize_series_sequence_nan():
    import math
    assert normalize_series_sequence(float("nan")) is None


# --- build_audiobookshelf_metadata ---

def test_build_audiobookshelf_metadata_basic():
    tags = {
        "title": "My Book",
        "author": "Author Name",
        "description": "A great book",
    }
    result = build_audiobookshelf_metadata(tags, language="en")
    assert result["title"] == "My Book"
    assert result["authors"] == ["Author Name"]
    assert result["language"] == "en"


def test_build_audiobookshelf_metadata_series():
    tags = {
        "title": "Book 2",
        "series": "My Series",
        "series_index": "2",
    }
    result = build_audiobookshelf_metadata(tags, language="en")
    assert result["seriesName"] == "My Series"
    assert result["seriesSequence"] == "2"


def test_build_audiobookshelf_metadata_fallback_title():
    tags = {"author": "Someone"}
    result = build_audiobookshelf_metadata(tags, language="en", filename="chapter1")
    assert result["title"] == "chapter1"


def test_build_audiobookshelf_metadata_empty():
    result = build_audiobookshelf_metadata({}, language="en")
    assert result["language"] == "en"
    assert "authors" not in result  # empty list stripped


def test_build_audiobookshelf_metadata_strips_empty():
    tags = {"title": "Book", "subtitle": "", "description": None}
    result = build_audiobookshelf_metadata(tags, language="en")
    assert "subtitle" not in result
    assert "description" not in result
