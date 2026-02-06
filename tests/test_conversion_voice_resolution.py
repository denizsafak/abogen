from types import SimpleNamespace
from typing import cast

from abogen.constants import VOICES_INTERNAL
from abogen.webui.conversion_runner import (
    _chapter_voice_spec,
    _chunk_voice_spec,
    _collect_required_voice_ids,
)
from abogen.webui.service import Job


def _sample_job(formula: str) -> Job:
    return cast(
        Job,
        SimpleNamespace(
            voice="__custom_mix",
            speakers={
                "narrator": {
                    "resolved_voice": formula,
                }
            },
            chapters=[],
            chunks=[{}],
        ),
    )


def test_chapter_voice_spec_uses_resolved_formula():
    formula = "af_nova*0.7+am_liam*0.3"
    job = _sample_job(formula)

    assert _chapter_voice_spec(job, None) == formula


def test_chunk_voice_fallback_uses_resolved_formula():
    formula = "af_nova*0.7+am_liam*0.3"
    job = _sample_job(formula)

    result = _chunk_voice_spec(job, {}, "")

    assert result == formula


def test_voice_collection_includes_formula_components():
    formula = "af_nova*0.7+am_liam*0.3"
    job = _sample_job(formula)

    voices = _collect_required_voice_ids(job)

    assert {"af_nova", "am_liam"}.issubset(voices)
    assert voices.issuperset(VOICES_INTERNAL)
