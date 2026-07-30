"""Tests for domain/text_utils.py."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.text_utils import calculate_text_length


class TestCalculateTextUtilsLength:
    def test_empty(self):
        assert calculate_text_length("") == 0

    def test_plain_text(self):
        assert calculate_text_length("Hello world") == 11

    def test_strips_newlines(self):
        assert calculate_text_length("Hello\nworld") == 10

    def test_strips_leading_trailing_spaces(self):
        assert calculate_text_length("  Hello  ") == 5

    def test_strips_chapter_markers(self):
        assert calculate_text_length("Hello<<CHAPTER_MARKER:intro>>world") == 10

    def test_strips_voice_markers(self):
        assert calculate_text_length("Hello<<VOICE:M1>>world") == 10

    def test_strips_metadata_tags(self):
        assert calculate_text_length("Hello<<METADATA_TITLE:My Book>>world") == 10

    def test_strips_multiple_markers(self):
        text = "<<CHAPTER_MARKER:ch1>>Hello<<VOICE:M1>> <<METADATA_TITLE:Book>>world"
        assert calculate_text_length(text) == 11

    def test_strips_mixed_content(self):
        text = "<<CHAPTER_MARKER:ch1>>\nHello\n<<VOICE:M1>>\nworld\n"
        assert calculate_text_length(text) == 10

    def test_preserves_internal_spaces(self):
        assert calculate_text_length("Hello world") == 11

    def test_only_markers(self):
        assert calculate_text_length("<<CHAPTER_MARKER:x>><<VOICE:y>>") == 0
