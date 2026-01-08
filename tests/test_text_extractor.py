from pathlib import Path

from ebooklib import epub

from abogen.text_extractor import extract_from_path
from abogen.utils import calculate_text_length


ASSET = Path(
    "test_assets/alexandre-dumas_the-count-of-monte-cristo_chapman-and-hall.epub"
)


def test_epub_character_counts_align_with_calculated_total():
    result = extract_from_path(ASSET)

    combined_total = calculate_text_length(result.combined_text)
    chapter_total = sum(chapter.characters for chapter in result.chapters)

    assert result.total_characters == combined_total == chapter_total


def test_epub_metadata_composer_matches_artist():
    result = extract_from_path(ASSET)

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
    book.add_metadata(
        "OPF", "meta", "", {"name": "calibre:series", "content": "Example Saga"}
    )
    book.add_metadata(
        "OPF", "meta", "", {"name": "calibre:series_index", "content": "2"}
    )

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap_01.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Hello</p>"
    book.add_item(chapter)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = tmp_path / "example.epub"
    epub.write_epub(str(path), book)

    result = extract_from_path(path)

    assert result.metadata.get("series") == "Example Saga"
    assert result.metadata.get("series_index") == "2"
