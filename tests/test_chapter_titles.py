"""Tests for domain/chapter_titles.py."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.chapter_titles import (
    simplify_heading_text,
    headings_equivalent,
    strip_duplicate_heading_line,
    normalize_caps_word,
    normalize_chapter_opening_caps,
    format_spoken_chapter_title,
)


class TestSimplifyHeadingText:
    def test_empty(self):
        assert simplify_heading_text("") == ""

    def test_none(self):
        assert simplify_heading_text(None) == ""

    def test_chapter_prefix_removed(self):
        assert simplify_heading_text("Chapter 1") == "1"

    def test_lowercase(self):
        assert simplify_heading_text("Chapter 1: The Beginning") == "1thebeginning"

    def test_strips_special_chars(self):
        result = simplify_heading_text("Ch. 1")
        assert "1" in result
        assert "." not in result

    def test_no_chapter_prefix(self):
        result = simplify_heading_text("Part 2")
        assert "part" in result


class TestHeadingsEquivalent:
    def test_exact_match(self):
        assert headings_equivalent("Chapter 1", "Chapter 1")

    def test_prefix_match(self):
        assert headings_equivalent("Chapter 2", "Chapter 2: The Return")

    def test_reverse_prefix(self):
        assert headings_equivalent("Chapter 2: The Return", "Chapter 2")

    def test_different_numbers(self):
        assert not headings_equivalent("Chapter 1", "Chapter 2")

    def test_empty(self):
        assert not headings_equivalent("", "Chapter 1")

    def test_long_containment(self):
        assert headings_equivalent("Introduction", "Introduction to Everything")


class TestStripDuplicateHeadingLine:
    def test_removes_heading(self):
        text = "Chapter 1\n\nSome text here"
        result, removed = strip_duplicate_heading_line(text, "Chapter 1")
        assert removed is True
        assert "Chapter 1" not in result
        assert "Some text here" in result

    def test_no_heading(self):
        text = "Just some text"
        result, removed = strip_duplicate_heading_line(text, "Chapter 1")
        assert removed is False
        assert result == text

    def test_empty_text(self):
        result, removed = strip_duplicate_heading_line("", "Chapter 1")
        assert removed is False

    def test_strips_leading_empty_lines(self):
        text = "Chapter 1\n\n\n\nText"
        result, removed = strip_duplicate_heading_line(text, "Chapter 1")
        assert removed is True
        assert result.startswith("Text")


class TestNormalizeCapsWord:
    def test_acronym_kept(self):
        assert normalize_caps_word("TTS") == "TTS"

    def test_single_letter_kept(self):
        assert normalize_caps_word("A") == "A"

    def test_roman_numeral_kept(self):
        assert normalize_caps_word("IV") == "IV"

    def test_all_caps_converted(self):
        result = normalize_caps_word("HELLO")
        assert result == "Hello"

    def test_with_hyphen(self):
        result = normalize_caps_word("WELL-KNOWN")
        assert result == "Well-Known"


class TestNormalizeChapterOpeningCaps:
    def test_all_caps_words(self):
        text = "THIS IS A TEST"
        result, changed = normalize_chapter_opening_caps(text)
        assert changed is True
        assert result == "This Is A Test"

    def test_already_normal(self):
        text = "This is normal"
        result, changed = normalize_chapter_opening_caps(text)
        assert changed is False

    def test_empty(self):
        result, changed = normalize_chapter_opening_caps("")
        assert changed is False

    def test_mixed(self):
        text = "HELLO world"
        result, changed = normalize_chapter_opening_caps(text)
        assert changed is True


class TestFormatSpokenChapterTitle:
    def test_empty_no_prefix(self):
        assert format_spoken_chapter_title("", 1, False) == ""

    def test_empty_with_prefix(self):
        assert format_spoken_chapter_title("", 1, True) == "Chapter 1"

    def test_no_prefix_returns_base(self):
        assert format_spoken_chapter_title("My Chapter", 1, False) == "My Chapter"

    def test_already_has_chapter(self):
        assert format_spoken_chapter_title("Chapter 5", 1, True) == "Chapter 5"

    def test_number_prefix(self):
        result = format_spoken_chapter_title("3. The End", 1, True)
        assert result == "Chapter 3. The End"

    def test_number_only(self):
        result = format_spoken_chapter_title("7", 1, True)
        assert result == "Chapter 7"
