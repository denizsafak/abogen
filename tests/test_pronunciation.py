"""Tests for abogen.domain.pronunciation — compile/apply pronunciation rules."""

from __future__ import annotations

import re
import pytest


# ---------------------------------------------------------------------------
# We import the domain functions.  The module must be created first.
# For now the tests are written against the expected public API so they can
# serve as the contract during extraction.
# ---------------------------------------------------------------------------


class TestCompilePronunciationRules:
    """compile_pronunciation_rules turns override dicts into regex-based rules."""

    def test_empty_input(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        assert compile_pronunciation_rules(None) == []
        assert compile_pronunciation_rules([]) == []

    def test_single_entry(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [{"token": "albeit", "pronunciation": "all be it"}]
        rules = compile_pronunciation_rules(overrides)
        assert len(rules) == 1
        assert rules[0]["replacement"] == "all be it"
        assert rules[0]["pattern"].search("albeit")

    def test_skips_entries_without_pronunciation(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [{"token": "hello"}]
        assert compile_pronunciation_rules(overrides) == []

    def test_skips_entries_without_token(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [{"pronunciation": "foo"}]
        assert compile_pronunciation_rules(overrides) == []

    def test_deduplication_by_casefold(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [
            {"token": "Albeit", "pronunciation": "all be it"},
            {"token": "ALBEIT", "pronunciation": "all be it"},
        ]
        rules = compile_pronunciation_rules(overrides)
        assert len(rules) == 1

    def test_longer_token_sorted_first(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [
            {"token": "ice cream", "pronunciation": "ice cream"},
            {"token": "ice", "pronunciation": "ais"},
        ]
        rules = compile_pronunciation_rules(overrides)
        assert len(rules) == 2
        assert len(rules[0]["token"]) >= len(rules[1]["token"])

    def test_normalized_fallback_to_entity_token(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [{"normalized": "USA", "pronunciation": "you ess ay"}]
        rules = compile_pronunciation_rules(overrides)
        assert len(rules) == 1

    def test_pattern_is_case_insensitive(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = [{"token": "hello", "pronunciation": "hi"}]
        rules = compile_pronunciation_rules(overrides)
        assert rules[0]["pattern"].search("Hello")
        assert rules[0]["pattern"].search("HELLO")

    def test_non_mapping_items_skipped(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules

        overrides = ["bad", None, 42]
        assert compile_pronunciation_rules(overrides) == []


class TestCompileHeteronymSentenceRules:
    """compile_heteronym_sentence_rules builds sentence-level replacements."""

    def test_empty_input(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        assert compile_heteronym_sentence_rules(None) == []
        assert compile_heteronym_sentence_rules([]) == []

    def test_basic_replacement(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [
            {
                "sentence": "I read the book",
                "choice": "past",
                "options": [
                    {"key": "present", "replacement_sentence": "I read the book"},
                    {"key": "past", "replacement_sentence": "I read the book"},
                ],
            }
        ]
        rules = compile_heteronym_sentence_rules(overrides)
        assert len(rules) == 1
        assert rules[0]["replacement"] == "I read the book"

    def test_skips_without_sentence(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [{"choice": "a", "options": []}]
        assert compile_heteronym_sentence_rules(overrides) == []

    def test_skips_without_choice(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [{"sentence": "hello", "options": []}]
        assert compile_heteronym_sentence_rules(overrides) == []

    def test_skips_when_no_matching_option(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [
            {
                "sentence": "I read the book",
                "choice": "past",
                "options": [{"key": "present", "replacement_sentence": "I read the book"}],
            }
        ]
        assert compile_heteronym_sentence_rules(overrides) == []

    def test_deduplication(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        entry = {
            "sentence": "I read the book",
            "choice": "past",
            "options": [{"key": "past", "replacement_sentence": "I red the book"}],
        }
        rules = compile_heteronym_sentence_rules([entry, entry])
        assert len(rules) == 1

    def test_longer_sentence_sorted_first(self):
        from abogen.domain.pronunciation import compile_heteronym_sentence_rules

        overrides = [
            {
                "sentence": "short",
                "choice": "a",
                "options": [{"key": "a", "replacement_sentence": "s"}],
            },
            {
                "sentence": "a longer sentence here",
                "choice": "b",
                "options": [{"key": "b", "replacement_sentence": "l"}],
            },
        ]
        rules = compile_heteronym_sentence_rules(overrides)
        assert len(rules[0]["pattern"].pattern) >= len(rules[1]["pattern"].pattern)


class TestApplyPronunciationRules:
    """apply_pronunciation_rules applies compiled token-level rules."""

    def test_empty_text(self):
        from abogen.domain.pronunciation import apply_pronunciation_rules

        assert apply_pronunciation_rules("", []) == ""

    def test_no_rules(self):
        from abogen.domain.pronunciation import apply_pronunciation_rules

        assert apply_pronunciation_rules("hello", []) == "hello"

    def test_basic_replacement(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules, apply_pronunciation_rules

        rules = compile_pronunciation_rules([{"token": "albeit", "pronunciation": "all be it"}])
        result = apply_pronunciation_rules("albeit it was raining", rules)
        assert result == "all be it it was raining"

    def test_possessive_preserved(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules, apply_pronunciation_rules

        rules = compile_pronunciation_rules([{"token": "dog", "pronunciation": "dawg"}])
        result = apply_pronunciation_rules("the dog's bone", rules)
        assert result == "the dawg's bone"

    def test_usage_counter_increments(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules, apply_pronunciation_rules

        rules = compile_pronunciation_rules([{"token": "hello", "pronunciation": "hi"}])
        counter: dict[str, int] = {}
        apply_pronunciation_rules("hello hello", rules, usage_counter=counter)
        assert counter.get("hello", 0) == 2

    def test_case_insensitive_match(self):
        from abogen.domain.pronunciation import compile_pronunciation_rules, apply_pronunciation_rules

        rules = compile_pronunciation_rules([{"token": "test", "pronunciation": "tst"}])
        result = apply_pronunciation_rules("This is a Test", rules)
        assert "tst" in result.lower()


class TestApplyHeteronymSentenceRules:
    """apply_heteronym_sentence_rules applies sentence-level replacements."""

    def test_empty_text(self):
        from abogen.domain.pronunciation import apply_heteronym_sentence_rules

        assert apply_heteronym_sentence_rules("", []) == ""

    def test_no_rules(self):
        from abogen.domain.pronunciation import apply_heteronym_sentence_rules

        assert apply_heteronym_sentence_rules("hello", []) == "hello"

    def test_basic_replacement(self):
        from abogen.domain.pronunciation import (
            compile_heteronym_sentence_rules,
            apply_heteronym_sentence_rules,
        )

        rules = compile_heteronym_sentence_rules(
            [
                {
                    "sentence": "I read the book",
                    "choice": "past",
                    "options": [{"key": "past", "replacement_sentence": "I read the book"}],
                }
            ]
        )
        result = apply_heteronym_sentence_rules("I read the book.", rules)
        assert result == "I read the book."

    def test_no_match_left_unchanged(self):
        from abogen.domain.pronunciation import (
            compile_heteronym_sentence_rules,
            apply_heteronym_sentence_rules,
        )

        rules = compile_heteronym_sentence_rules(
            [
                {
                    "sentence": "I read the book",
                    "choice": "past",
                    "options": [{"key": "past", "replacement_sentence": "I red the book"}],
                }
            ]
        )
        result = apply_heteronym_sentence_rules("something else entirely", rules)
        assert result == "something else entirely"


class TestMergePronunciationOverrides:
    """merge_pronunciation_overrides consolidates override sources."""

    def test_empty_job(self):
        from abogen.domain.pronunciation import merge_pronunciation_overrides

        class FakeJob:
            pronunciation_overrides = None
            speakers = None
            manual_overrides = None
            language = "en"

        result = merge_pronunciation_overrides(FakeJob())
        assert result == []

    def test_pronunciation_overrides_included(self):
        from abogen.domain.pronunciation import merge_pronunciation_overrides

        class FakeJob:
            pronunciation_overrides = [
                {"token": "hello", "pronunciation": "hi", "normalized": "hello"}
            ]
            speakers = None
            manual_overrides = None
            language = "en"

        result = merge_pronunciation_overrides(FakeJob())
        assert len(result) == 1
        assert result[0]["token"] == "hello"
        assert result[0]["source"] == "pronunciation"

    def test_manual_overrides_win(self):
        from abogen.domain.pronunciation import merge_pronunciation_overrides

        class FakeJob:
            pronunciation_overrides = [
                {"token": "hello", "pronunciation": "hi old", "normalized": "hello"}
            ]
            speakers = None
            manual_overrides = [
                {"token": "hello", "pronunciation": "hi new", "normalized": "hello"}
            ]
            language = "en"

        result = merge_pronunciation_overrides(FakeJob())
        assert len(result) == 1
        assert result[0]["pronunciation"] == "hi new"
        assert result[0]["source"] == "manual"

    def test_speaker_entries_included(self):
        from abogen.domain.pronunciation import merge_pronunciation_overrides

        class FakeJob:
            pronunciation_overrides = None
            speakers = {"narrator": {"token": "war", "pronunciation": "wɔːr"}}
            manual_overrides = None
            language = "en"

        result = merge_pronunciation_overrides(FakeJob())
        assert len(result) == 1
        assert result[0]["source"] == "speaker"

    def test_skips_empty_tokens(self):
        from abogen.domain.pronunciation import merge_pronunciation_overrides

        class FakeJob:
            pronunciation_overrides = [{"token": "", "pronunciation": "foo"}]
            speakers = None
            manual_overrides = None
            language = "en"

        result = merge_pronunciation_overrides(FakeJob())
        assert result == []
