"""Tests for domain/metadata_helpers.py."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.metadata_helpers import (
    normalize_metadata_map,
    format_author_sentence,
    ensure_sentence,
    normalize_series_number,
    extract_series_metadata,
    format_series_sentence,
)


class TestNormalizeMetadataMap:
    def test_empty(self):
        assert normalize_metadata_map({}) == {}

    def test_none(self):
        assert normalize_metadata_map(None) == {}

    def test_normalizes_keys(self):
        result = normalize_metadata_map({"Title": "My Book", "artist": "John"})
        assert "title" in result
        assert "artist" in result

    def test_skips_none_values(self):
        result = normalize_metadata_map({"title": None, "artist": "John"})
        assert "title" not in result

    def test_skips_empty_values(self):
        result = normalize_metadata_map({"title": "", "artist": "John"})
        assert "title" not in result


class TestFormatAuthorSentence:
    def test_none(self):
        assert format_author_sentence(None) == ""

    def test_empty(self):
        assert format_author_sentence("") == ""

    def test_unknown(self):
        assert format_author_sentence("Unknown") == ""

    def test_single(self):
        assert format_author_sentence("John Doe") == "By John Doe"

    def test_two(self):
        assert format_author_sentence("John, Jane") == "By John and Jane"

    def test_three(self):
        assert format_author_sentence("John, Jane, Bob") == "By John, Jane, and Bob"

    def test_ampersand(self):
        assert format_author_sentence("John & Jane") == "By John and Jane"


class TestEnsureSentence:
    def test_empty(self):
        assert ensure_sentence("") == ""

    def test_already_sentence(self):
        assert ensure_sentence("Hello.") == "Hello."

    def test_adds_period(self):
        assert ensure_sentence("Hello") == "Hello."

    def test_exclamation(self):
        assert ensure_sentence("Hello!") == "Hello!"


class TestNormalizeSeriesNumber:
    def test_empty(self):
        assert normalize_series_number("") is None

    def test_integer(self):
        assert normalize_series_number("3") == "3"

    def test_float(self):
        assert normalize_series_number("3.5") == "3.5"

    def test_float_trailing_zero(self):
        assert normalize_series_number("3.10") == "3.1"

    def test_comma_as_separator(self):
        assert normalize_series_number("3,5") == "3.5"

    def test_text_with_number(self):
        assert normalize_series_number("Book 3") == "3"

    def test_none(self):
        assert normalize_series_number(None) is None


class TestExtractSeriesMetadata:
    def test_empty(self):
        name, number = extract_series_metadata({})
        assert name is None
        assert number is None

    def test_series_name(self):
        name, number = extract_series_metadata({"series": "My Series"})
        assert name == "My Series"
        assert number is None

    def test_series_number(self):
        name, number = extract_series_metadata({"series_index": "3"})
        assert name is None
        assert number == "3"

    def test_both(self):
        name, number = extract_series_metadata({"series": "My Series", "series_index": "3"})
        assert name == "My Series"
        assert number == "3"


class TestFormatSeriesSentence:
    def test_empty(self):
        assert format_series_sentence(None, None) == ""

    def test_name_only(self):
        assert format_series_sentence("My Series", None) == ""

    def test_number_only(self):
        assert format_series_sentence(None, "3") == ""

    def test_both(self):
        assert format_series_sentence("My Series", "3") == "Book 3 of the My Series"

    def test_with_the(self):
        assert format_series_sentence("The Lord of the Rings", "1") == "Book 1 of The Lord of the Rings"
