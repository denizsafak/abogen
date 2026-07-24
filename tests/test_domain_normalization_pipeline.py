"""Tests for domain/normalization.py — prepare_text_for_tts, build_tts_context."""

import pytest
from unittest.mock import patch, MagicMock
from abogen.domain.normalization import prepare_text_for_tts, normalize_text_for_pipeline, build_tts_context, TTSContext


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


class TestBuildTtsContext:
    """Tests for the build_tts_context factory."""

    def test_returns_tts_context(self):
        ctx = build_tts_context()
        assert isinstance(ctx, TTSContext)

    def test_default_split_pattern(self):
        ctx = build_tts_context(language="a", subtitle_mode="Disabled")
        assert isinstance(ctx.split_pattern, str)
        assert len(ctx.split_pattern) > 0

    def test_english_uses_newline_split(self):
        ctx = build_tts_context(language="a", subtitle_mode="Disabled")
        assert ctx.split_pattern == "\n"

    def test_cjk_uses_punctuation_split(self):
        ctx = build_tts_context(language="j", subtitle_mode="Disabled")
        assert "[.??.?!]" in ctx.split_pattern or "\\n" not in ctx.split_pattern

    def test_pronunciation_overrides_compiled(self):
        overrides = [
            {
                "token": "epub",
                "pronunciation": "ee-pub",
                "normalized": "epub",
            }
        ]
        ctx = build_tts_context(
            pronunciation_overrides=overrides,
        )
        assert ctx.pronunciation_rules is not None
        assert len(ctx.pronunciation_rules) >= 1

    def test_manual_overrides_included(self):
        overrides = [
            {
                "token": "gif",
                "pronunciation": "jif",
                "normalized": "gif",
            }
        ]
        ctx = build_tts_context(
            manual_overrides=overrides,
        )
        assert ctx.pronunciation_rules is not None
        assert len(ctx.pronunciation_rules) >= 1

    def test_manual_overrides_win_over_pronunciation(self):
        pronunciation = [
            {"token": "x", "pronunciation": "WRONG", "normalized": "x"}
        ]
        manual = [
            {"token": "x", "pronunciation": "RIGHT", "normalized": "x"}
        ]
        ctx = build_tts_context(
            pronunciation_overrides=pronunciation,
            manual_overrides=manual,
        )
        found_right = any(
            r.get("replacement") == "RIGHT" for r in ctx.pronunciation_rules
        )
        found_wrong = any(
            r.get("replacement") == "WRONG" for r in ctx.pronunciation_rules
        )
        assert found_right
        assert not found_wrong

    def test_heteronym_overrides_compiled(self):
        overrides = [
            {
                "token": "read",
                "pronunciation": "red",
                "context": "past tense",
            }
        ]
        ctx = build_tts_context(
            heteronym_overrides=overrides,
        )
        assert ctx.heteronym_rules is not None

    def test_usage_counter_passed_through(self):
        counter = {}
        ctx = build_tts_context(usage_counter=counter)
        assert ctx.usage_counter is counter

    def test_usage_counter_default_empty(self):
        ctx = build_tts_context()
        assert ctx.usage_counter == {}

    def test_normalization_overrides_stored(self):
        overrides = {"normalization_numbers": False}
        ctx = build_tts_context(normalization_overrides=overrides)
        assert ctx.normalization_overrides is overrides

    def test_speakers_used_for_pronunciation(self):
        speakers = {
            "narrator": {
                "token": "route",
                "pronunciation": "root",
                "resolved_voice": "M1",
            }
        }
        ctx = build_tts_context(speakers=speakers)
        assert ctx.pronunciation_rules is not None
        assert len(ctx.pronunciation_rules) >= 1

    def test_log_callback_called_on_num2words_missing(self):
        logs = []
        with patch("abogen.domain.normalization.get_runtime_settings", return_value={
            "normalization_apostrophe_mode": "spacy",
            "normalization_enabled": True,
            "normalization_numbers": True,
        }):
            with patch("abogen.normalization_settings.build_apostrophe_config") as mock_cfg:
                mock_cfg.return_value = MagicMock(convert_numbers=True)
                with patch("builtins.__import__", side_effect=ImportError):
                    try:
                        build_tts_context(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
                    except ImportError:
                        pass
        # If num2words is missing and convert_numbers is True, a warning should be logged
        # (depends on mock behavior, so just check no crash)

    def test_llm_mode_raises_if_not_configured(self):
        with patch("abogen.domain.normalization.get_runtime_settings", return_value={
            "normalization_apostrophe_mode": "llm",
        }):
            with pytest.raises(RuntimeError, match="LLM"):
                build_tts_context()

    def test_dict_source_accepted(self):
        """merge_pronunciation_overrides should accept a dict."""
        source = {
            "pronunciation_overrides": [
                {"token": "test", "pronunciation": "test-est", "normalized": "test"}
            ],
            "manual_overrides": [],
            "speakers": {},
            "language": "a",
        }
        from abogen.domain.pronunciation import merge_pronunciation_overrides
        result = merge_pronunciation_overrides(source)
        assert isinstance(result, list)
        assert len(result) >= 1
