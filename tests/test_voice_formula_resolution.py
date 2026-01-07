from __future__ import annotations

from abogen.webui.conversion_runner import _resolve_voice, _supertonic_voice_from_spec
from abogen.tts_supertonic import DEFAULT_SUPERTONIC_VOICES


def test_resolve_voice_formula_without_pipeline_does_not_crash() -> None:
    # This can happen when a previously-saved Kokoro mix formula is present
    # but the active provider is SuperTonic (no Kokoro pipeline object).
    formula = "af_heart*0.5+af_sky*0.5"
    resolved = _resolve_voice(None, formula, use_gpu=False)
    assert resolved == formula


def test_supertonic_voice_from_formula_falls_back_to_valid_voice() -> None:
    # When a stale Kokoro mix formula is present, SuperTonic should not receive it.
    chosen = _supertonic_voice_from_spec("af_heart*0.5+af_sky*0.5", "af_heart*1.0")
    assert chosen in DEFAULT_SUPERTONIC_VOICES
