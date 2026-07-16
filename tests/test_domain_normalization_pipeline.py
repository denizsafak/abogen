"""Tests for domain/normalization.py — prepare_text_for_tts."""

import pytest
from unittest.mock import patch, MagicMock
from abogen.domain.normalization import prepare_text_for_tts, normalize_text_for_pipeline


class TestPrepareTextForTts:
    """Tests for the comprehensive TTS text preparation pipeline."""

    def test_empty_text(self):
        result = prepare_text_for_tts("")
        assert result == ""

    def test_none_text(self):
        result = prepare_text_for_tts(None)
        assert result == ""

    def test_passthrough_no_rules(self):
        result = prepare_text_for_tts("Hello world")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_heteronym_rules_applied(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [
            {
                "token": "read",
                "pronunciation": "red",
                "context": "past tense",
            }
        ]
        rules = compile_heteronym_sentence_rules(overrides)
        if rules:
            result = prepare_text_for_tts("I will read the book", heteronym_rules=rules)
            assert isinstance(result, str)

    def test_pronunciation_rules_applied(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [
            {
                "token": "epub",
                "pronunciation": "ee-pub",
                "normalized": "epub",
            }
        ]
        rules = compile_pronunciation_rules(overrides)
        result = prepare_text_for_tts(
            "This is an epub file",
            pronunciation_rules=rules,
        )
        assert "ee-pub" in result

    def test_usage_counter_tracks_pronunciation(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [
            {
                "token": "data",
                "pronunciation": "day-ta",
                "normalized": "data",
            }
        ]
        rules = compile_pronunciation_rules(overrides)
        counter = {}
        prepare_text_for_tts(
            "The data is here and the data is there",
            pronunciation_rules=rules,
            usage_counter=counter,
        )
        assert counter.get("data", 0) >= 1

    def test_combined_heteronym_and_pronunciation(self):
        from abogen.domain.pronunciation import (
            compile_heteronym_sentence_rules,
            compile_pronunciation_rules,
        )

        heteronym_overrides = [
            {
                "token": "lead",
                "pronunciation": "led",
                "context": "metal",
            }
        ]
        pronunciation_overrides = [
            {
                "token": "gif",
                "pronunciation": "jif",
                "normalized": "gif",
            }
        ]
        h_rules = compile_heteronym_sentence_rules(heteronym_overrides)
        p_rules = compile_pronunciation_rules(pronunciation_overrides)

        result = prepare_text_for_tts(
            "A lead gif",
            heteronym_rules=h_rules if h_rules else None,
            pronunciation_rules=p_rules,
        )
        assert isinstance(result, str)

    @patch("abogen.domain.normalization.get_runtime_settings")
    def test_normalization_overrides_passed_through(self, mock_settings):
        mock_settings.return_value = {
            "normalization_apostrophe_mode": "spacy",
            "normalization_enabled": True,
        }
        result = prepare_text_for_tts(
            "It's a test",
            normalization_overrides={"normalization_enabled": False},
        )
        assert isinstance(result, str)

    def test_pronunciation_rules_empty(self):
        result = prepare_text_for_tts("Hello", pronunciation_rules=[])
        assert isinstance(result, str)

    def test_heteronym_rules_empty(self):
        result = prepare_text_for_tts("Hello", heteronym_rules=[])
        assert isinstance(result, str)


class TestNormalizeTextForPipeline:
    """Tests for the simpler normalization function."""

    def test_basic_normalization(self):
        result = normalize_text_for_pipeline("It's a test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_text(self):
        result = normalize_text_for_pipeline("")
        assert result == ""

    @patch("abogen.domain.normalization.get_runtime_settings")
    def test_with_overrides(self, mock_settings):
        mock_settings.return_value = {
            "normalization_apostrophe_mode": "spacy",
        }
        result = normalize_text_for_pipeline(
            "It's a test",
            normalization_overrides={"normalization_apostrophe_mode": "spacy"},
        )
        assert isinstance(result, str)
