"""Tests for domain/title_builder.py."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.title_builder import build_title_intro_text, build_outro_text


class TestBuildTitleIntroText:
    def test_empty_metadata(self):
        result = build_title_intro_text({}, "book.epub")
        assert result == "book."

    def test_title_from_metadata(self):
        result = build_title_intro_text({"title": "My Book"}, "book.epub")
        assert result == "My Book."

    def test_title_fallback_basename(self):
        result = build_title_intro_text({}, "my_book.epub")
        assert result == "my_book."

    def test_with_author(self):
        result = build_title_intro_text({"title": "My Book", "author": "John Doe"}, "book.epub")
        assert result == "My Book. By John Doe."

    def test_with_subtitle(self):
        result = build_title_intro_text({"title": "My Book", "subtitle": "A Tale"}, "book.epub")
        assert result == "My Book. A Tale."

    def test_duplicate_title_subtitle(self):
        result = build_title_intro_text({"title": "My Book", "subtitle": "My Book"}, "book.epub")
        assert result == "My Book."

    def test_with_series(self):
        result = build_title_intro_text({"title": "My Book", "series": "Series", "series_index": "3"}, "book.epub")
        assert result == "Book 3 of the Series. My Book."


class TestBuildOutroText:
    def test_empty(self):
        result = build_outro_text({}, "book.epub")
        assert result == "The end of book."

    def test_title_only(self):
        result = build_outro_text({"title": "My Book"}, "book.epub")
        assert result == "The end of My Book."

    def test_author_only(self):
        result = build_outro_text({"author": "John Doe"}, "book.epub")
        assert result == "The end of book from John Doe."

    def test_title_and_author(self):
        result = build_outro_text({"title": "My Book", "author": "John Doe"}, "book.epub")
        assert result == "The end of My Book from John Doe."

    def test_with_series(self):
        result = build_outro_text({"title": "My Book", "series": "Series", "series_index": "3"}, "book.epub")
        assert "The end of My Book." in result
        assert "Book 3 of the Series." in result