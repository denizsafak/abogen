"""Tests for domain/metadata_helpers.py."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.metadata_helpers import (
    normalize_metadata_map,
    expand_metadata_aliases,
    format_author_sentence,
    ensure_sentence,
    normalize_series_number,
    extract_series_metadata,
    format_series_sentence,
    build_metadata_payload,
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


class TestBuildMetadataPayload:
    def test_empty(self):
        result = build_metadata_payload()
        assert result == {
            "metadata": {},
            "chapters": [],
            "chunks": [],
            "chunk_level": None,
            "speaker_mode": None,
            "speakers": {},
            "generate_epub3": False,
        }

    def test_with_metadata(self):
        result = build_metadata_payload(metadata={"title": "Book", "artist": "Author"})
        assert result["metadata"] == {"title": "Book", "artist": "Author"}

    def test_metadata_is_copy(self):
        original = {"title": "Book"}
        result = build_metadata_payload(metadata=original)
        result["metadata"]["title"] = "Changed"
        assert original["title"] == "Book"

    def test_with_chapters(self):
        chapters = [{"title": "Ch1", "start": 0.0, "end": 10.0}]
        result = build_metadata_payload(chapter_markers=chapters)
        assert result["chapters"] == chapters

    def test_with_all_fields(self):
        result = build_metadata_payload(
            metadata={"title": "Book"},
            chapter_markers=[{"title": "Ch1", "start": 0.0, "end": 10.0}],
            chunk_markers=[{"start": 0.0, "end": 5.0}],
            chunk_level="chunk",
            speaker_mode="multi",
            speakers={"narrator": "M1"},
            generate_epub3=True,
        )
        assert result["metadata"] == {"title": "Book"}
        assert len(result["chapters"]) == 1
        assert len(result["chunks"]) == 1
        assert result["chunk_level"] == "chunk"
        assert result["speaker_mode"] == "multi"
        assert result["speakers"] == {"narrator": "M1"}
        assert result["generate_epub3"] is True

    def test_speakers_is_copy(self):
        original = {"narrator": "M1"}
        result = build_metadata_payload(speakers=original)
        result["speakers"]["narrator"] = "M2"
        assert original["narrator"] == "M1"


class TestExpandMetadataAliases:
    def test_empty(self):
        assert expand_metadata_aliases({}) == {}

    def test_none(self):
        assert expand_metadata_aliases(None) == {}  # type: ignore

    def test_series_expansion(self):
        result = expand_metadata_aliases({"series": "My Series"})
        assert result["series"] == "My Series"
        assert result["series_name"] == "My Series"
        assert result["seriesname"] == "My Series"
        assert result["series_title"] == "My Series"
        assert result["seriestitle"] == "My Series"

    def test_series_name_variant(self):
        result = expand_metadata_aliases({"series_name": "Test"})
        assert result["series"] == "Test"
        assert result["series_name"] == "Test"
        assert result["series_title"] == "Test"

    def test_series_index_expansion(self):
        result = expand_metadata_aliases({"series_index": "3"})
        assert result["series_index"] == "3"
        assert result["series_sequence"] == "3"
        assert result["series_position"] == "3"
        assert result["book_number"] == "3"

    def test_series_index_variant(self):
        result = expand_metadata_aliases({"series_sequence": "5"})
        assert result["series_index"] == "5"
        assert result["series_sequence"] == "5"

    def test_author_expansion(self):
        result = expand_metadata_aliases({"author": "John"})
        assert result["author"] == "John"
        assert result["authors"] == "John"

    def test_authors_variant(self):
        result = expand_metadata_aliases({"authors": "Jane"})
        assert result["author"] == "Jane"
        assert result["authors"] == "Jane"

    def test_description_expansion(self):
        result = expand_metadata_aliases({"description": "A book"})
        assert result["description"] == "A book"
        assert result["summary"] == "A book"

    def test_summary_variant(self):
        result = expand_metadata_aliases({"summary": "Summary text"})
        assert result["description"] == "Summary text"
        assert result["summary"] == "Summary text"

    def test_tags_expansion(self):
        result = expand_metadata_aliases({"tags": "sci-fi"})
        assert result["tags"] == "sci-fi"
        assert result["keywords"] == "sci-fi"
        assert result["genre"] == "sci-fi"

    def test_keywords_variant(self):
        result = expand_metadata_aliases({"keywords": "fantasy"})
        assert result["tags"] == "fantasy"
        assert result["keywords"] == "fantasy"
        assert result["genre"] == "fantasy"

    def test_passthrough_non_alias_keys(self):
        result = expand_metadata_aliases({"title": "My Book", "publisher": "Pub"})
        assert result["title"] == "My Book"
        assert result["publisher"] == "Pub"

    def test_mixed_concepts(self):
        result = expand_metadata_aliases({
            "series": "My Series",
            "series_index": "3",
            "author": "John",
            "title": "Book",
        })
        assert result["series"] == "My Series"
        assert result["series_name"] == "My Series"
        assert result["series_index"] == "3"
        assert result["series_sequence"] == "3"
        assert result["author"] == "John"
        assert result["authors"] == "John"
        assert result["title"] == "Book"

    def test_skips_none_values(self):
        result = expand_metadata_aliases({"series": None, "author": "John"})
        assert "series" not in result
        assert result["author"] == "John"

    def test_skips_empty_values(self):
        result = expand_metadata_aliases({"series": "", "author": "John"})
        assert "series" not in result
        assert result["author"] == "John"

    def test_none_key_converted_to_string(self):
        result = expand_metadata_aliases({None: "value"})
        assert result["none"] == "value"

    def test_case_insensitive_keys(self):
        result = expand_metadata_aliases({"Series": "Test", "AUTHOR": "John"})
        assert result["series"] == "Test"
        assert result["author"] == "John"

    def test_list_value_preserved(self):
        result = expand_metadata_aliases({"tags": ["a", "b"]})
        assert result["tags"] == ["a", "b"]
        assert result["keywords"] == ["a", "b"]
        assert result["genre"] == ["a", "b"]
