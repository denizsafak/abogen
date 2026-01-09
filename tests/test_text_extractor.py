from unittest.mock import patch

import pytest
from pathlib import Path

from ebooklib import epub

from abogen.text_extractor import extract_from_path
from abogen.utils import calculate_text_length


@pytest.fixture
def sample_epub_path():
    return Path(__file__).parent / "fixtures" / "abogen_debug_tts_samples.epub"


def test_epub_character_counts_align_with_calculated_total(sample_epub_path):
    result = extract_from_path(sample_epub_path)

    combined_total = calculate_text_length(result.combined_text)
    chapter_total = sum(chapter.characters for chapter in result.chapters)

    assert result.total_characters == combined_total == chapter_total


def test_epub_metadata_composer_matches_artist(sample_epub_path):
    result = extract_from_path(sample_epub_path)

    composer = result.metadata.get("composer") or result.metadata.get("COMPOSER")
    artist = result.metadata.get("artist") or result.metadata.get("ARTIST")

    assert composer
    assert composer == artist
    assert composer != "Narrator"


def test_epub_series_metadata_extracted_from_opf_meta(tmp_path):
    book = epub.EpubBook()
    book.set_identifier("id")
    book.set_title("Example Title")
    book.set_language("en")
    book.add_author("Example Author")

    # Calibre-style series metadata
    # ebooklib stores this in memory correctly, but may not round-trip via disk in read_epub
    book.add_metadata(
        "OPF", "meta", None, {"name": "calibre:series", "content": "Example Saga"}
    )
    book.add_metadata(
        "OPF", "meta", None, {"name": "calibre:series_index", "content": "2"}
    )

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap_01.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Hello</p>"
    chapter.id = "chap_01"
    book.add_item(chapter)
    
    # We manually set the spine to match what ebooklib.read_epub produces (list of tuples),
    # since we are bypassing the serialization round-trip that normally converts it.
    # The 'nav' item is usually handled separately or implicitly, but for this test
    # we just need the chapter to be navigable via spine.
    book.spine = [("nav", "yes"), ("chap_01", "yes")]
    
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = tmp_path / "example.epub"
    epub.write_epub(str(path), book)

    # We mock read_epub to avoid serialization issues with custom metadata in ebooklib
    with patch("abogen.text_extractor.epub.read_epub", return_value=book):
        result = extract_from_path(path)

        assert result.metadata.get("series") == "Example Saga"
        assert result.metadata.get("series_index") == "2"

