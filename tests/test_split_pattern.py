"""Tests for split pattern logic (3 identical copies in codebase)."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from abogen.domain.split_pattern import get_split_pattern


# --- English always returns \n ---

class TestEnglish:
    def test_english_sentence(self):
        assert get_split_pattern("en-US", "Sentence") == "\n"

    def test_english_sentence_comma(self):
        assert get_split_pattern("en-US", "Sentence + Comma") == "\n"

    def test_english_line(self):
        assert get_split_pattern("en-US", "Line") == "\n"

    def test_english_disabled(self):
        assert get_split_pattern("en-US", "Disabled") == "\n"

    def test_english_gb(self):
        assert get_split_pattern("en-GB", "Sentence") == "\n"


# --- CJK languages ---

class TestCJK:
    def test_chinese_disabled(self):
        pattern = get_split_pattern("zh", "Disabled")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_chinese_line(self):
        pattern = get_split_pattern("zh", "Line")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_chinese_sentence(self):
        pattern = get_split_pattern("zh", "Sentence")
        assert r"\n+" in pattern

    def test_chinese_sentence_comma(self):
        pattern = get_split_pattern("zh", "Sentence + Comma")
        assert r"\n+" in pattern

    def test_japanese_disabled(self):
        pattern = get_split_pattern("ja", "Disabled")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_japanese_sentence(self):
        pattern = get_split_pattern("ja", "Sentence")
        assert r"\n+" in pattern


# --- Other languages ---

class TestOtherLanguages:
    def test_spanish_sentence(self):
        pattern = get_split_pattern("es", "Sentence")
        assert r"\n+" in pattern

    def test_spanish_line(self):
        assert get_split_pattern("es", "Line") == "\n"

    def test_spanish_disabled(self):
        # canonical: \n+ for non-CJK Disabled
        assert get_split_pattern("es", "Disabled") == r"\n+"

    def test_french_sentence_comma(self):
        pattern = get_split_pattern("fr", "Sentence + Comma")
        assert r"\n+" in pattern

    def test_unknown_lang(self):
        pattern = get_split_pattern("x", "Sentence")
        assert r"\n+" in pattern


# --- Pattern structure ---

class TestPatternStructure:
    def test_sentence_has_lookbehind(self):
        pattern = get_split_pattern("es", "Sentence")
        assert r"(?<=" in pattern

    def test_sentence_comma_has_comma_chars(self):
        pattern = get_split_pattern("es", "Sentence + Comma")
        assert "," in pattern

    def test_cjk_spacing_uses_star(self):
        pattern = get_split_pattern("zh", "Sentence")
        assert r"\s*" in pattern

    def test_non_cjk_spacing_uses_plus(self):
        pattern = get_split_pattern("es", "Sentence")
        assert r"\s+" in pattern
