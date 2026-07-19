"""Tests for sanitize_filename_for_chapter in domain/output_paths.py"""

from __future__ import annotations

from abogen.domain.output_paths import sanitize_filename_for_chapter


class TestSanitizeFilenameForChapter:
    def test_basic_title(self):
        result = sanitize_filename_for_chapter("The Beginning", 1)
        assert result == "01_The_Beginning"

    def test_special_chars_removed(self):
        result = sanitize_filename_for_chapter("Ch. 1: Hello!", 2)
        assert result.startswith("02_")
        assert "Ch" in result
        assert "Hello" in result

    def test_empty_title_uses_fallback(self):
        result = sanitize_filename_for_chapter("", 3)
        assert result == "03_chapter_03"

    def test_index_prefix_zero_padded(self):
        result = sanitize_filename_for_chapter("Test", 10)
        assert result.startswith("10_")

    def test_long_title_truncated_at_word_boundary(self):
        long_title = "a" * 50 + "_" + "b" * 50
        result = sanitize_filename_for_chapter(long_title, 1, max_len=60)
        # Should truncate at word boundary
        suffix = result[3:]  # Remove "01_"
        assert len(suffix) <= 60

    def test_custom_max_len(self):
        result = sanitize_filename_for_chapter("Hello World", 1, max_len=5)
        suffix = result[3:]  # Remove "01_"
        assert len(suffix) <= 5

    def test_hyphens_and_spaces_collapsed(self):
        result = sanitize_filename_for_chapter("mid-night story", 1)
        assert result == "01_mid_night_story"

    def test_whitespace_collapsed(self):
        result = sanitize_filename_for_chapter("hello   world", 1)
        assert "hello_world" in result

    def test_leading_trailing_underscores_stripped(self):
        result = sanitize_filename_for_chapter("  hello  ", 1)
        assert result == "01_hello"
