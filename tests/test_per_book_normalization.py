"""Model-free native wizard normalization and cache regressions."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from werkzeug.datastructures import MultiDict

import abogen.chunking as chunking
from abogen.normalization_settings import get_runtime_settings
from abogen.webui.routes.utils import form as forms
from abogen.webui.service import ConversionService
from tests.test_wizard_chapter_selection_chunks import _selection_form, _plan_bodies


@pytest.fixture
def runtime(monkeypatch):
    settings = get_runtime_settings()
    settings.update(normalization_apostrophe_mode="off", normalization_numbers=False,
                    normalization_currency=False, normalization_footnotes=True)
    monkeypatch.setattr(chunking, "get_runtime_settings", lambda: dict(settings))
    monkeypatch.setattr(forms, "get_runtime_settings", lambda: dict(settings), raising=False)
    return settings


def build(tmp_path, runtime, level="paragraph", **overrides):
    text = "F1 FP2 Q3 RP20 W11. A synthetic note[12] costs 42 coins."
    (tmp_path / "synthetic.txt").write_text(text, encoding="utf-8")
    extraction = SimpleNamespace(chapters=[SimpleNamespace(title="Chapter One", text=text)],
                                 metadata={}, cover_image=None, total_characters=len(text))
    settings = forms.load_settings()
    settings.update(runtime)
    return forms.build_pending_job_from_extraction(
        stored_path=tmp_path / "synthetic.txt", original_name="synthetic.txt",
        extraction=extraction, form={"voice": "af_heart", "chunk_level": level, **overrides},
        settings=settings, profiles={}).pending


@pytest.mark.parametrize("level", ["paragraph", "sentence"])
def test_initial_speech_and_analysis_use_book_false(tmp_path, runtime, level):
    seen = []
    real = chunking.normalize_for_pipeline
    def capture(value, **kwargs):
        seen.append(kwargs["settings"]["normalization_footnotes"])
        return real(value, **kwargs)
    with patch.object(chunking, "normalize_for_pipeline", capture):
        pending = build(tmp_path, runtime, level, normalization_footnotes="false")
    assert pending.normalization_overrides["normalization_footnotes"] is False
    assert seen and not any(seen)
    assert "F1 FP2 Q3 RP20 W11" in " ".join(c["normalized_text"] for c in pending.chunks)
    assert "F1 FP2 Q3 RP20 W11" in _plan_bodies(pending)[0][1]
    assert runtime["normalization_footnotes"] is True


def test_toggle_rebuilds_raw_preserving_cast_and_custom_not_audio(tmp_path, runtime):
    pending = build(tmp_path, runtime)
    assert "[12]" not in pending.chunks[0]["normalized_text"]
    pending.chunks[0].update(speaker_id="hero", speaker_label="Hero", custom={"role": "pilot"},
                             audio_path="stale.wav", start=1, end=2)
    forms.apply_book_step_form(pending, MultiDict({"normalization_footnotes": "false"}),
                               settings={**forms.load_settings(), **runtime}, profiles={})
    selection = _selection_form(pending, {0})
    forms.apply_prepare_form(pending, selection)
    chunk = pending.chunks[0]
    assert "[12]" in chunk["normalized_text"]
    assert "F1 FP2 Q3 RP20 W11" in chunk["normalized_text"]
    assert chunk["speaker_id"] == "hero" and chunk["custom"] == {"role": "pilot"}
    assert not {"audio_path", "start", "end"} & chunk.keys()
    with patch.object(chunking, "normalize_for_pipeline", side_effect=AssertionError("cache miss")):
        forms.apply_prepare_form(pending, selection)
    assert "F1 FP2 Q3 RP20 W11" in _plan_bodies(pending)[0][1]


@pytest.mark.parametrize("missing", ["normalization_fingerprint", "normalized_text"])
def test_legacy_rebuild_once_and_service_round_trip(tmp_path, runtime, missing):
    pending = build(tmp_path, runtime, normalization_footnotes="false")
    pending.chunks = ConversionService._normalize_chunks(pending.chunks)
    pending.chunks[0].pop(missing, None)
    selection = _selection_form(pending, {0})
    with patch.object(chunking, "normalize_for_pipeline", wraps=chunking.normalize_for_pipeline) as spy:
        forms.apply_prepare_form(pending, selection)
        assert spy.call_count == 1
        pending.chunks = ConversionService._normalize_chunks(pending.chunks)
        forms.apply_prepare_form(pending, selection)
        assert spy.call_count == 1


def test_inherited_setting_invalidates_and_mapping_order_does_not(tmp_path, runtime):
    pending = build(tmp_path, runtime, normalization_footnotes="false")
    pending.normalization_overrides.pop("normalization_numbers")
    selection = _selection_form(pending, {0})
    runtime["normalization_numbers"] = True
    with patch.object(chunking, "normalize_for_pipeline", wraps=chunking.normalize_for_pipeline) as spy:
        forms.apply_prepare_form(pending, selection)
        assert spy.call_count == 1
        pending.normalization_overrides = dict(reversed(list(pending.normalization_overrides.items())))
        forms.apply_prepare_form(pending, selection)
        assert spy.call_count == 1


def test_empty_false_and_omitted_book_form_semantics(tmp_path, runtime):
    pending = build(tmp_path, runtime, normalization_footnotes="false", normalization_apostrophe_mode="off")
    settings = {**forms.load_settings(), **runtime}
    forms.apply_book_step_form(pending, MultiDict(), settings=settings, profiles={})
    assert pending.normalization_overrides["normalization_footnotes"] is False
    forms.apply_book_step_form(pending, MultiDict({"normalization_apostrophe_mode": ""}), settings=settings, profiles={})
    assert pending.normalization_overrides["normalization_apostrophe_mode"] == ""


def test_fingerprint_excludes_credentials_and_ui_values(runtime):
    from abogen.normalization_settings import normalization_fingerprint
    first = normalization_fingerprint(runtime)
    changed = {**runtime, "llm_api_key": "synthetic-credential", "llm_timeout": 99,
               "voice": "another", "output_format": "wav"}
    assert normalization_fingerprint(changed) == first
    assert normalization_fingerprint(dict(reversed(list(runtime.items())))) == first
    assert normalization_fingerprint({**runtime, "llm_model": "different"}) != first
    chunks = chunking.build_chunks_for_chapters(
        [{"id": "source", "text": "Synthetic prose."}], level="paragraph",
        normalization_settings=changed)
    assert "synthetic-credential" not in repr(chunks)
    assert "llm_api_key" not in repr(chunks)


def test_number_setting_recovers_raw_independent_of_footnote_rule(tmp_path, runtime):
    pending = build(tmp_path, runtime, normalization_footnotes="false", normalization_numbers="true")
    assert "forty" in pending.chunks[0]["normalized_text"]
    pending.normalization_overrides["normalization_numbers"] = False
    forms.apply_prepare_form(pending, _selection_form(pending, {0}))
    assert "42 coins" in pending.chunks[0]["normalized_text"]
    assert "42 coins" in _plan_bodies(pending)[0][1]


def test_reorder_subset_and_new_chapter_use_source_ids(runtime):
    settings = dict(runtime)
    chapters = [{"id": str(i), "text": f"Source {i} note[12]."} for i in range(3)]
    old = chunking.build_chunks_for_chapters(chapters[:2], level="paragraph", normalization_settings=settings)
    old[1]["speaker_id"] = "hero"
    with patch.object(chunking, "normalize_for_pipeline", wraps=chunking.normalize_for_pipeline) as spy:
        reordered = forms._resync_chunks(old, [chapters[1], chapters[0], chapters[2]], "paragraph",
                                         normalization_settings=dict(reversed(list(settings.items()))))
        assert spy.call_count == 1
    assert [c["id"] for c in reordered] == ["1_p0000", "0_p0000", "2_p0000"]
    assert [c["chapter_index"] for c in reordered] == [0, 1, 2]
    assert reordered[0]["speaker_id"] == "hero"
    with patch.object(chunking, "normalize_for_pipeline", side_effect=AssertionError("cache miss")):
        subset = forms._resync_chunks(reordered, [chapters[2], chapters[1]], "paragraph",
                                      normalization_settings=settings)
    assert [c["id"] for c in subset] == ["2_p0000", "1_p0000"]

