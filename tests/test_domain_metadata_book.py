"""Tests for domain/metadata_extraction.py — format_metadata_tags, extract_book_metadata_*."""

import os

import pytest

from abogen.domain.metadata_extraction import (
    extract_book_metadata_markdown,
    format_metadata_tags,
    _save_cover_to_cache,
)


class TestFormatMetadataTags:
    def test_basic_epub(self):
        metadata = {
            "title": "My Book",
            "authors": ["Author One", "Author Two"],
            "publication_year": "2023",
        }
        result = format_metadata_tags(metadata, "fallback", 10, "epub")
        assert "<<METADATA_TITLE:My Book>>" in result
        assert "<<METADATA_ARTIST:Author One, Author Two>>" in result
        assert "<<METADATA_ALBUM:My Book (10 Chapters)>>" in result
        assert "<<METADATA_YEAR:2023>>" in result
        assert "<<METADATA_GENRE:Audiobook>>" in result

    def test_pdf_uses_pages(self):
        metadata = {"title": "PDF Doc", "authors": ["Writer"]}
        result = format_metadata_tags(metadata, "doc", 50, "pdf")
        assert "50 Pages" in result

    def test_markdown_uses_chapters(self):
        metadata = {"title": "MD Doc"}
        result = format_metadata_tags(metadata, "doc", 3, "markdown")
        assert "3 Chapters" in result

    def test_fallback_title(self):
        metadata = {}
        result = format_metadata_tags(metadata, "fallback_name", 1, "epub")
        assert "<<METADATA_TITLE:fallback_name>>" in result

    def test_unknown_authors(self):
        metadata = {"authors": []}
        result = format_metadata_tags(metadata, "file", 1, "epub")
        assert "<<METADATA_ARTIST:Unknown>>" in result

    def test_cover_bytes_saved(self, tmp_path):
        metadata = {"title": "With Cover"}
        cover = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Fake image bytes
        result = format_metadata_tags(
            metadata, "file", 1, "epub",
            cover_bytes=cover, cache_dir=str(tmp_path),
        )
        assert "<<METADATA_COVER_PATH:" in result
        # Verify file was created
        cover_files = list(tmp_path.glob("cover_*.jpg"))
        assert len(cover_files) == 1
        assert cover_files[0].read_bytes() == cover

    def test_no_cover_bytes(self):
        metadata = {"title": "No Cover"}
        result = format_metadata_tags(metadata, "file", 1, "epub")
        assert "METADATA_COVER_PATH" not in result

    def test_authors_as_string(self):
        metadata = {"authors": "Single Author"}
        result = format_metadata_tags(metadata, "file", 1, "epub")
        assert "<<METADATA_ARTIST:Single Author>>" in result


class TestSaveCoverToCache:
    def test_saves_file(self, tmp_path):
        data = b"\x89PNG" + b"\x00" * 50
        result = _save_cover_to_cache(data, str(tmp_path))
        assert result is not None
        assert os.path.exists(result)
        assert open(result, "rb").read() == data

    def test_none_bytes(self, tmp_path):
        assert _save_cover_to_cache(None, str(tmp_path)) is None

    def test_none_cache_dir(self):
        assert _save_cover_to_cache(b"data", None) is None

    def test_returns_normalized_path(self, tmp_path):
        result = _save_cover_to_cache(b"data", str(tmp_path))
        assert result == os.path.normpath(result)


class TestExtractBookMetadataMarkdown:
    def test_frontmatter(self):
        text = "---\ntitle: Test Title\nauthor: Test Author\ndate: 2024\n---\n\nBody"
        result = extract_book_metadata_markdown(text)
        assert result["title"] == "Test Title"
        assert result["authors"] == ["Test Author"]
        assert result["publication_year"] == "2024"

    def test_fallback_to_h1(self, ):
        text = "# My Heading\n\nSome content"
        toc = [{"level": 1, "name": "My Heading"}]
        result = extract_book_metadata_markdown(text, toc)
        assert result["title"] == "My Heading"

    def test_empty_text(self):
        result = extract_book_metadata_markdown("")
        assert result["title"] is None
        assert result["authors"] == []

    def test_frontmatter_with_quotes(self):
        text = '---\ntitle: "Quoted Title"\nauthor: \'Quoted Author\'\n---\n\nBody'
        result = extract_book_metadata_markdown(text)
        assert result["title"] == "Quoted Title"
        assert result["authors"] == ["Quoted Author"]
