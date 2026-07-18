from __future__ import annotations

from unittest.mock import patch

from abogen.domain.voice_utils import (
    coerce_truthy,
    formula_from_kokoro_entry,
    infer_provider_from_spec,
    resolve_voice_target,
    split_speaker_reference,
    supertonic_voice_from_spec,
)


class TestSplitSpeakerReference:
    def test_speaker_prefix(self):
        assert split_speaker_reference("speaker:af_sarah") == ("af_sarah", "speaker:af_sarah")

    def test_profile_prefix(self):
        assert split_speaker_reference("profile:custom") == ("custom", "profile:custom")

    def test_no_prefix(self):
        assert split_speaker_reference("af_sarah") == (None, "af_sarah")

    def test_empty(self):
        assert split_speaker_reference("") == (None, "")

    def test_none(self):
        assert split_speaker_reference(None) == (None, "")

    def test_unknown_prefix(self):
        assert split_speaker_reference("unknown:name") == (None, "unknown:name")

    def test_empty_name_after_colon(self):
        assert split_speaker_reference("speaker:") == (None, "speaker:")


class TestSupertonicVoiceFromSpec:
    def test_uppercase_passthrough(self):
        assert supertonic_voice_from_spec("M1", "M1") == "M1"

    def test_lowercase_converted(self):
        assert supertonic_voice_from_spec("m1", "M1") == "M1"

    def test_empty_spec_uses_fallback(self):
        assert supertonic_voice_from_spec("", "F1") == "F1"

    def test_formula_spec_uses_fallback(self):
        assert supertonic_voice_from_spec("af_sarah*0.5+bf_emma*0.5", "M1") == "M1"

    def test_empty_both_gives_default(self):
        assert supertonic_voice_from_spec("", "") == "M1"


class TestFormulaFromKokoroEntry:
    def test_single_voice(self):
        entry = {"voices": [["af_sarah", 1.0]]}
        result = formula_from_kokoro_entry(entry)
        assert "af_sarah" in result
        assert "1.000000" in result

    def test_weighted_mix(self):
        entry = {"voices": [["af_sarah", 0.6], ["bf_emma", 0.4]]}
        result = formula_from_kokoro_entry(entry)
        assert "af_sarah" in result
        assert "bf_emma" in result
        assert "+" in result

    def test_empty_voices(self):
        assert formula_from_kokoro_entry({"voices": []}) == ""

    def test_missing_voices_key(self):
        assert formula_from_kokoro_entry({}) == ""

    def test_invalid_entries_filtered(self):
        entry = {"voices": [["af_sarah", "bad"], ["bf_emma", 0.5]]}
        result = formula_from_kokoro_entry(entry)
        assert "bf_emma" in result
        assert "af_sarah" not in result


class TestCoerceTruthy:
    def test_bool_passthrough(self):
        assert coerce_truthy(True) is True
        assert coerce_truthy(False) is False

    def test_string_true(self):
        assert coerce_truthy("yes") is True
        assert coerce_truthy("1") is True

    def test_string_false(self):
        assert coerce_truthy("false") is False
        assert coerce_truthy("0") is False
        assert coerce_truthy("") is False

    def test_none_default(self):
        assert coerce_truthy(None) is True
        assert coerce_truthy(None, False) is False

    def test_int(self):
        assert coerce_truthy(1) is True
        assert coerce_truthy(0) is False


class TestInferProviderFromSpec:
    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah", "bf_emma"])
    def test_known_kokoro_voice(self, _mock):
        assert infer_provider_from_spec("af_sarah") == "kokoro"

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_uppercase_supertonic(self, _mock):
        assert infer_provider_from_spec("M1") == "supertonic"

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_formula_kokoro(self, _mock):
        assert infer_provider_from_spec("af_sarah*0.5+bf_emma*0.5") == "kokoro"

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_empty_fallback(self, _mock):
        assert infer_provider_from_spec("", "kokoro") == "kokoro"

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_unknown_falls_back(self, _mock):
        assert infer_provider_from_spec("unknown_xyz", "supertonic") == "supertonic"


class TestResolveVoiceTarget:
    def test_empty_spec_kokoro_default(self):
        provider, spec, speed, steps = resolve_voice_target(
            "", {}, job_voice="af_sarah", job_tts_provider="kokoro",
        )
        assert provider == "kokoro"
        assert spec == ""

    def test_speaker_profile_kokoro(self):
        profiles = {
            "narrator": {
                "provider": "kokoro",
                "voices": [["af_sarah", 0.7], ["bf_emma", 0.3]],
            },
        }
        provider, spec, speed, steps = resolve_voice_target(
            "speaker:narrator", profiles,
        )
        assert provider == "kokoro"
        assert "af_sarah" in spec
        assert speed is None
        assert steps is None

    def test_speaker_profile_supertonic(self):
        profiles = {
            "narrator": {
                "provider": "supertonic",
                "voice": "F1",
                "speed": 1.2,
                "total_steps": 10,
            },
        }
        provider, spec, speed, steps = resolve_voice_target(
            "speaker:narrator", profiles,
            job_voice="M1", job_speed=1.0, job_supertonic_total_steps=5,
        )
        assert provider == "supertonic"
        assert spec == "F1"
        assert speed == 1.2
        assert steps == 10

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_direct_supertonic_spec(self, _mock):
        provider, spec, speed, steps = resolve_voice_target(
            "M1", {},
            job_voice="M1",
        )
        assert provider == "supertonic"
        assert spec == "M1"

    @patch("abogen.domain.voice_utils.get_voices", return_value=["af_sarah"])
    def test_direct_kokoro_spec(self, _mock):
        provider, spec, speed, steps = resolve_voice_target(
            "af_sarah", {},
            job_tts_provider="kokoro",
        )
        assert provider == "kokoro"
        assert spec == "af_sarah"

    def test_profile_missing_provider_defaults_kokoro(self):
        profiles = {
            "narrator": {
                "voices": [["af_sarah", 1.0]],
            },
        }
        provider, spec, speed, steps = resolve_voice_target(
            "speaker:narrator", profiles,
        )
        assert provider == "kokoro"
