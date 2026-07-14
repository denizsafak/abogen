"""Tests for domain/voice_utils.py."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from abogen.domain.voice_utils import (
    infer_provider_from_spec,
    supertonic_voice_from_spec,
    split_speaker_reference,
    formula_from_kokoro_entry,
    coerce_truthy,
)


class TestInferProviderFromSpec:
    def test_empty_returns_fallback(self):
        assert infer_provider_from_spec("", "kokoro") == "kokoro"

    def test_supertonic_uppercase(self):
        assert infer_provider_from_spec("M1", "kokoro") == "supertonic"

    def test_kokoro_voice(self):
        assert infer_provider_from_spec("af_bella", "kokoro") == "kokoro"

    def test_custom_mix(self):
        assert infer_provider_from_spec("__custom_mix", "kokoro") == "kokoro"

    def test_formula(self):
        assert infer_provider_from_spec("af_bella*0.5+am_adam*0.5", "kokoro") == "kokoro"


class TestSupertonicVoiceFromSpec:
    def test_normal(self):
        assert supertonic_voice_from_spec("m1", "m2") == "M1"

    def test_empty_uses_fallback(self):
        assert supertonic_voice_from_spec("", "m2") == "M2"

    def test_formula_uses_fallback(self):
        assert supertonic_voice_from_spec("m1*0.5", "m2") == "M2"

    def test_both_empty_uses_default(self):
        assert supertonic_voice_from_spec("", "") == "M1"


class TestSplitSpeakerReference:
    def test_speaker(self):
        name, original = split_speaker_reference("speaker:John")
        assert name == "John"
        assert original == "speaker:John"

    def test_profile(self):
        name, original = split_speaker_reference("profile:Main")
        assert name == "Main"
        assert original == "profile:Main"

    def test_invalid_prefix(self):
        name, original = split_speaker_reference("voice:John")
        assert name is None
        assert original == "voice:John"

    def test_no_colon(self):
        name, original = split_speaker_reference("John")
        assert name is None
        assert original == "John"

    def test_empty(self):
        name, original = split_speaker_reference("")
        assert name is None
        assert original == ""


class TestFormulaFromKokoroEntry:
    def test_normal(self):
        entry = {"voices": [["af_bella", 0.5], ["am_adam", 0.5]]}
        result = formula_from_kokoro_entry(entry)
        assert "af_bella" in result
        assert "am_adam" in result

    def test_empty(self):
        assert formula_from_kokoro_entry({}) == ""

    def test_invalid_items(self):
        entry = {"voices": [["af_bella", "invalid"], ["am_adam", 0.5]]}
        result = formula_from_kokoro_entry(entry)
        assert "am_adam" in result
        assert "af_bella" not in result


class TestCoerceTruthy:
    def test_bool_true(self):
        assert coerce_truthy(True) is True

    def test_bool_false(self):
        assert coerce_truthy(False) is False

    def test_string_true(self):
        assert coerce_truthy("true") is True
        assert coerce_truthy("yes") is True
        assert coerce_truthy("1") is True
        assert coerce_truthy("on") is True

    def test_string_false(self):
        assert coerce_truthy("false") is False
        assert coerce_truthy("no") is False
        assert coerce_truthy("0") is False
        assert coerce_truthy("off") is False
        assert coerce_truthy("") is False

    def test_none_default_true(self):
        assert coerce_truthy(None, True) is True

    def test_none_default_false(self):
        assert coerce_truthy(None, False) is False

    def test_int(self):
        assert coerce_truthy(1) is True
        assert coerce_truthy(0) is False