"""Tests for domain/text_chapters.py"""

from __future__ import annotations

from abogen.domain.text_chapters import parse_chapters_from_text


class TestParseChaptersFromText:
    def test_no_markers_returns_single_chapter(self):
        result = parse_chapters_from_text("Hello world")
        assert len(result) == 1
        assert result[0][0] == "text"
        assert result[0][1] == "Hello world"

    def test_no_markers_custom_default_title(self):
        result = parse_chapters_from_text("Hello", default_title="intro")
        assert result[0][0] == "intro"

    def test_single_marker(self):
        text = "<<CHAPTER_MARKER:Chapter 1>>\nSome text here"
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 1
        assert result[0][0] == "Chapter 1"
        assert result[0][1] == "Some text here"

    def test_multiple_markers(self):
        text = (
            "<<CHAPTER_MARKER:Chapter 1>>\nText 1\n"
            "<<CHAPTER_MARKER:Chapter 2>>\nText 2\n"
        )
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 2
        assert result[0][0] == "Chapter 1"
        assert result[0][1] == "Text 1"
        assert result[1][0] == "Chapter 2"
        assert result[1][1] == "Text 2"

    def test_intro_preserved_before_first_marker(self):
        text = "Introduction text\n<<CHAPTER_MARKER:Chapter 1>>\nMain text"
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 2
        assert result[0][0] == "Introduction"
        assert result[0][1] == "Introduction text"
        assert result[1][0] == "Chapter 1"

    def test_empty_intro_not_added(self):
        text = "<<CHAPTER_MARKER:Chapter 1>>\nText"
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 1
        assert result[0][0] == "Chapter 1"

    def test_clean_text_applied_by_default(self):
        text = "<<CHAPTER_MARKER:Ch 1>>\n  some   messy   text  "
        result = parse_chapters_from_text(text, clean=True)
        # clean_text normalizes whitespace
        assert "some" in result[0][1]
        assert "messy" in result[0][1]

    def test_clean_disabled(self):
        text = "<<CHAPTER_MARKER:Ch 1>>\n  some   text  "
        result = parse_chapters_from_text(text, clean=False)
        assert result[0][1] == "some   text"

    def test_empty_marker_title_uses_default(self):
        text = "<<CHAPTER_MARKER:>>\nSome text"
        result = parse_chapters_from_text(text, clean=False)
        assert result[0][0] == "text"

    def test_case_insensitive_markers(self):
        text = "<<chapter_marker:Chapter 1>>\nText"
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 1
        assert result[0][0] == "Chapter 1"

    def test_empty_text(self):
        result = parse_chapters_from_text("")
        assert len(result) == 1
        assert result[0][0] == "text"
        assert result[0][1] == ""

    def test_only_markers_no_text(self):
        text = "<<CHAPTER_MARKER:Ch 1>><<CHAPTER_MARKER:Ch 2>>"
        result = parse_chapters_from_text(text, clean=False)
        assert len(result) == 2
        assert result[0][0] == "Ch 1"
        assert result[1][0] == "Ch 2"
