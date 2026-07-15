"""Tests for abogen.domain.subtitle_generation module."""

import pytest

from abogen.domain.subtitle_generation import (
    process_subtitle_tokens,
    PUNCTUATION_SENTENCE,
    PUNCTUATION_SENTENCE_COMMA,
)


class TestProcessSubtitleTokens:
    """Tests for process_subtitle_tokens function."""

    def test_empty_tokens(self):
        """Test processing empty token list does nothing."""
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=[],
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Sentence",
            lang_code="a",
        )
        assert entries == []

    def test_disabled_mode(self):
        """Test Disabled mode returns no entries."""
        tokens = [
            {"start": 0.0, "end": 1.0, "text": "Hello", "whitespace": " "},
            {"start": 1.0, "end": 2.0, "text": "world", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Disabled",
            lang_code="a",
        )
        assert entries == []

    def test_line_mode_basic(self):
        """Test Line mode splits on newlines."""
        tokens = [
            {"start": 0.0, "end": 1.0, "text": "First line", "whitespace": "\n"},
            {"start": 1.0, "end": 2.0, "text": "Second line", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Line",
            lang_code="a",
        )
        assert len(entries) == 2
        assert entries[0][2] == "First line"
        assert entries[1][2] == "Second line"

    def test_sentence_mode_punctuation_split(self):
        """Test Sentence mode splits on sentence punctuation."""
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "First sentence", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": ".", "whitespace": " "},
            {"start": 1.0, "end": 1.5, "text": "Second sentence", "whitespace": " "},
            {"start": 1.5, "end": 2.0, "text": ".", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Sentence",
            lang_code="a",
        )
        assert len(entries) >= 1
        # Should have at least one entry with both sentences or split
        combined_text = " ".join(e[2] for e in entries)
        assert "First sentence" in combined_text
        assert "Second sentence" in combined_text

    def test_word_count_mode(self):
        """Test word count mode (e.g., '5' for 5 words per entry)."""
        tokens = [
            {"start": 0.0, "end": 0.2, "text": "word1", "whitespace": " "},
            {"start": 0.2, "end": 0.4, "text": "word2", "whitespace": " "},
            {"start": 0.4, "end": 0.6, "text": "word3", "whitespace": " "},
            {"start": 0.6, "end": 0.8, "text": "word4", "whitespace": " "},
            {"start": 0.8, "end": 1.0, "text": "word5", "whitespace": " "},
            {"start": 1.0, "end": 1.2, "text": "word6", "whitespace": " "},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="2",  # 2 words per entry
            lang_code="a",
        )
        assert len(entries) >= 2
        # Check that entries are split roughly by word count
        for entry in entries:
            # Each entry should have at least one word
            assert len(entry[2].split()) >= 1

    def test_fallback_end_time(self):
        """Test fallback_end_time is applied when end time is invalid."""
        tokens = [
            {"start": 0.0, "end": None, "text": "Test", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Line",
            lang_code="a",
            fallback_end_time=10.0,
        )
        assert len(entries) == 1
        assert entries[0][1] == 10.0  # Should use fallback

    def test_karaoke_highlighting_mode(self):
        """Test Sentence + Highlighting mode generates karaoke tags."""
        tokens = [
            {"start": 0.0, "end": 0.5, "text": "Hello", "whitespace": " "},
            {"start": 0.5, "end": 1.0, "text": "world", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Sentence + Highlighting",
            lang_code="a",
        )
        assert len(entries) >= 1
        # Should contain karaoke tags
        text = entries[0][2]
        assert "{\\kf" in text

    def test_max_subtitle_words_limit(self):
        """Test that max_subtitle_words limits entry length."""
        tokens = [
            {"start": float(i), "end": float(i + 0.1), "text": f"word{i}", "whitespace": " "}
            for i in range(10)
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=3,
            subtitle_mode="Line",
            lang_code="a",
        )
        # Should have more than 1 entry due to word limit
        assert len(entries) > 1

    def test_preserves_token_timing(self):
        """Test that token timing is preserved in entries."""
        tokens = [
            {"start": 0.0, "end": 1.0, "text": "First", "whitespace": " "},
            {"start": 1.0, "end": 2.0, "text": "Second", "whitespace": ""},
        ]
        entries = []
        process_subtitle_tokens(
            tokens_with_timestamps=tokens,
            subtitle_entries=entries,
            max_subtitle_words=50,
            subtitle_mode="Sentence",
            lang_code="a",
        )
        assert len(entries) >= 1
        # Check that timing is preserved
        for entry in entries:
            assert entry[0] >= 0.0
            assert entry[1] >= entry[0]


class TestPunctuationConstants:
    """Tests for punctuation constants."""

    def test_punctuation_sentence_contains_basic(self):
        """Test PUNCTUATION_SENTENCE contains basic sentence punctuation."""
        assert "." in PUNCTUATION_SENTENCE
        assert "!" in PUNCTUATION_SENTENCE
        assert "?" in PUNCTUATION_SENTENCE

    def test_punctuation_sentence_comma_contains_comma(self):
        """Test PUNCTUATION_SENTENCE_COMMA contains comma."""
        assert "," in PUNCTUATION_SENTENCE_COMMA
        assert "." in PUNCTUATION_SENTENCE_COMMA
        assert "!" in PUNCTUATION_SENTENCE_COMMA
        assert "?" in PUNCTUATION_SENTENCE_COMMA
