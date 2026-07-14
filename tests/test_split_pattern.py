"""Tests for split pattern logic (3 identical copies in codebase)."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from abogen.domain.split_pattern import get_split_pattern


# --- English always returns \n ---

class TestEnglish:
    def test_english_sentence(self):
        assert get_split_pattern("a", "Sentence") == "\n"

    def test_english_sentence_comma(self):
        assert get_split_pattern("a", "Sentence + Comma") == "\n"

    def test_english_line(self):
        assert get_split_pattern("a", "Line") == "\n"

    def test_english_disabled(self):
        assert get_split_pattern("a", "Disabled") == "\n"

    def test_english_b(self):
        assert get_split_pattern("b", "Sentence") == "\n"


# --- CJK languages ---

class TestCJK:
    def test_chinese_disabled(self):
        pattern = get_split_pattern("z", "Disabled")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_chinese_line(self):
        pattern = get_split_pattern("z", "Line")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_chinese_sentence(self):
        pattern = get_split_pattern("z", "Sentence")
        assert r"\n+" in pattern

    def test_chinese_sentence_comma(self):
        pattern = get_split_pattern("z", "Sentence + Comma")
        assert r"\n+" in pattern

    def test_japanese_disabled(self):
        pattern = get_split_pattern("j", "Disabled")
        assert pattern != "\n"
        assert r"\n+" in pattern

    def test_japanese_sentence(self):
        pattern = get_split_pattern("j", "Sentence")
        assert r"\n+" in pattern


# --- Other languages ---

class TestOtherLanguages:
    def test_spanish_sentence(self):
        pattern = get_split_pattern("e", "Sentence")
        assert r"\n+" in pattern

    def test_spanish_line(self):
        assert get_split_pattern("e", "Line") == "\n"

    def test_spanish_disabled(self):
        # canonical: \n+ for non-CJK Disabled
        assert get_split_pattern("e", "Disabled") == r"\n+"

    def test_french_sentence_comma(self):
        pattern = get_split_pattern("f", "Sentence + Comma")
        assert r"\n+" in pattern

    def test_unknown_lang(self):
        pattern = get_split_pattern("x", "Sentence")
        assert r"\n+" in pattern


# --- Pattern structure ---

class TestPatternStructure:
    def test_sentence_has_lookbehind(self):
        pattern = get_split_pattern("e", "Sentence")
        assert r"(?<=" in pattern

    def test_sentence_comma_has_comma_chars(self):
        pattern = get_split_pattern("e", "Sentence + Comma")
        assert "," in pattern

    def test_cjk_spacing_uses_star(self):
        pattern = get_split_pattern("z", "Sentence")
        assert r"\s*" in pattern

    def test_non_cjk_spacing_uses_plus(self):
        pattern = get_split_pattern("e", "Sentence")
        assert r"\s+" in pattern
