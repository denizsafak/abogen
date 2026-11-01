"""Regression: changing the wizard chapter selection must re-sync speech chunks.

The initial upload builds chunks for the default (auto-preselected) chapters.
The planner groups those chunks by *selected ordinal*, so if the user later
enables front/back matter and the chunks are not rebuilt, every chapter body
shifts under the wrong heading and trailing chapters (e.g. Acknowledgements)
are emitted title-only.
"""

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
from werkzeug.datastructures import MultiDict

from abogen.application.conversion_config import ChapterChunkConfig
from abogen.chunking import build_chunks_for_chapters
from abogen.application.conversion_planner import build_conversion_plan
from abogen.application.conversion_request import ConversionRequest
from abogen.webui.routes.utils.form import (
    apply_prepare_form,
    build_pending_job_from_extraction,
    load_settings,
)


CHAPTERS = [
    ("Copyright", "Copyright 2024 Example Press. All rights reserved. ISBN 978-0-00-000000-0."),
    ("Dedication", "For my parents, who drove me to every race. DEDICATIONMARK."),
    ("Chapter One", "ONEMARK opening words. The first chapter body continues here at length."),
    ("Chapter Two", "TWOMARK second chapter body. It also continues for a while."),
    ("Chapter Three", "THREEMARK third chapter body. Final narrative chapter."),
    ("Acknowledgements", "Firstly, a huge thank you to everyone. ACKMARK."),
]

MARKERS = {
    "Dedication": "DEDICATIONMARK",
    "Chapter One": "ONEMARK",
    "Chapter Two": "TWOMARK",
    "Chapter Three": "THREEMARK",
    "Acknowledgements": "ACKMARK",
}


def _build_pending(tmp_path: Path, chapters=CHAPTERS):
    source = tmp_path / "book.txt"
    source.write_text("\n\n".join(text for _, text in chapters), encoding="utf-8")
    extraction = SimpleNamespace(
        chapters=[SimpleNamespace(title=title, text=text) for title, text in chapters],
        metadata={},
        cover_image=None,
        cover_mime=None,
        total_characters=sum(len(text) for _, text in chapters),
        combined_text="\n\n".join(text for _, text in chapters),
    )
    result = build_pending_job_from_extraction(
        stored_path=source,
        original_name=source.name,
        extraction=extraction,
        form={"voice": "af_heart", "language": "a"},
        settings=load_settings(),
        profiles={},
    )
    return result.pending


def _selection_form(pending, enabled_indices, **extra) -> MultiDict:
    form = MultiDict(extra)
    for index, chapter in enumerate(pending.chapters):
        if index in enabled_indices:
            form[f"chapter-{index}-enabled"] = "on"
        form[f"chapter-{index}-title"] = chapter.get("title") or ""
    return form


def _plan_bodies(pending) -> List[tuple]:
    request = ConversionRequest(
        source_path=Path(pending.stored_path),
        original_filename=pending.original_filename,
        voice=pending.voice,
        read_title_intro=False,
        read_closing_outro=False,
        normalize_chapter_opening_caps=False,
        chapter_chunk=ChapterChunkConfig(
            chapter_overrides=pending.chapters or [],
            chunks=pending.chunks or [],
            chunk_level=pending.chunk_level,
            speaker_mode=pending.speaker_mode,
            speakers=pending.speakers or {},
        ),
    )
    plan = build_conversion_plan(request)
    return [
        (chapter.title, " ".join(segment.text for segment in chapter.segments))
        for chapter in plan.chapters
    ]


def _assert_bodies_match_titles(bodies, expected_titles):
    assert [title for title, _ in bodies] == expected_titles
    for title, body in bodies:
        own = MARKERS.get(title)
        if own:
            assert own in body, f"{title!r} lost its own body: {body[:120]!r}"
        foreign = [m for t, m in MARKERS.items() if t != title and m in body]
        assert not foreign, f"{title!r} contains other chapters' text {foreign}"


def test_default_selection_excludes_front_and_back_matter(tmp_path):
    pending = _build_pending(tmp_path)
    enabled = [c["title"] for c in pending.chapters if c.get("enabled")]
    # Precondition for the regression: the initial chunks cover a subset.
    assert "Copyright" not in enabled
    assert "Chapter One" in enabled


def test_unchanged_selection_keeps_planned_text(tmp_path):
    pending = _build_pending(tmp_path)
    default_indices = {i for i, c in enumerate(pending.chapters) if c.get("enabled")}
    initial_chunk_texts = [c["text"] for c in pending.chunks]

    apply_prepare_form(pending, _selection_form(pending, default_indices))

    assert [c["text"] for c in pending.chunks] == initial_chunk_texts
    expected = [CHAPTERS[i][0] for i in sorted(default_indices)]
    _assert_bodies_match_titles(_plan_bodies(pending), expected)


def test_enabling_all_chapters_keeps_bodies_under_their_headings(tmp_path):
    pending = _build_pending(tmp_path)
    all_indices = set(range(len(CHAPTERS)))

    apply_prepare_form(pending, _selection_form(pending, all_indices))

    bodies = _plan_bodies(pending)
    _assert_bodies_match_titles(bodies, [title for title, _ in CHAPTERS])
    body_by_title = dict(bodies)
    assert body_by_title["Copyright"].startswith("Copyright")
    assert "Example Press" in body_by_title["Copyright"]
    assert "Firstly, a huge thank you" in body_by_title["Acknowledgements"]
    # No duplicated or lost chunk text.
    joined = " ".join(body for _, body in bodies)
    for marker in MARKERS.values():
        assert joined.count(marker) == 1


def test_disabling_a_default_chapter_drops_only_that_body(tmp_path):
    pending = _build_pending(tmp_path)
    keep = {1, 3, 4, 5}  # Dedication, Chapter Two, Chapter Three, Acknowledgements

    apply_prepare_form(pending, _selection_form(pending, keep))

    bodies = _plan_bodies(pending)
    _assert_bodies_match_titles(bodies, [CHAPTERS[i][0] for i in sorted(keep)])
    assert "ONEMARK" not in " ".join(body for _, body in bodies)


def test_finish_after_selection_change_is_idempotent(tmp_path):
    # /wizard/update then /wizard/finish both call apply_prepare_form.
    pending = _build_pending(tmp_path)
    form = _selection_form(pending, set(range(len(CHAPTERS))))

    apply_prepare_form(pending, form)
    apply_prepare_form(pending, form)

    _assert_bodies_match_titles(_plan_bodies(pending), [title for title, _ in CHAPTERS])


def test_chunk_level_change_rebuilds_chunks(tmp_path):
    pending = _build_pending(tmp_path)
    default_indices = {i for i, c in enumerate(pending.chapters) if c.get("enabled")}

    apply_prepare_form(pending, _selection_form(pending, default_indices, chunk_level="sentence"))

    assert pending.chunk_level == "sentence"
    assert pending.chunks
    assert all(chunk.get("level") == "sentence" for chunk in pending.chunks)


def _chunks_for(pending, marker):
    return [chunk for chunk in pending.chunks if marker in str(chunk.get("text"))]


def test_chunk_ids_follow_source_chapter_not_selected_ordinal(tmp_path):
    pending = _build_pending(tmp_path)
    initial_ids = {chunk["text"]: chunk["id"] for chunk in pending.chunks}

    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))

    for chunk in pending.chunks:
        if chunk["text"] in initial_ids:
            assert chunk["id"] == initial_ids[chunk["text"]]
    (two,) = _chunks_for(pending, "TWOMARK")
    assert two["id"].startswith("0003_")
    assert two["chapter_index"] == 3  # ordinal changed, identity did not


def test_prepared_chunk_fields_follow_source_chunk_across_toggles(tmp_path):
    pending = _build_pending(tmp_path)
    (two,) = _chunks_for(pending, "TWOMARK")
    two["speaker_id"] = "hero"
    two["speaker_label"] = "Hero"
    two["normalized_text"] = "TWOMARK edited narration."

    # Enable front/back matter (shifts ordinals), then drop Chapter One.
    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))
    apply_prepare_form(pending, _selection_form(pending, {0, 1, 3, 4, 5}))

    (two,) = _chunks_for(pending, "TWOMARK")
    assert (two["speaker_id"], two["speaker_label"]) == ("hero", "Hero")
    assert two["normalized_text"] == "TWOMARK edited narration."
    others = [chunk for chunk in pending.chunks if chunk is not two]
    assert all(chunk["speaker_id"] == "narrator" for chunk in others)
    body_by_title = dict(_plan_bodies(pending))
    assert body_by_title["Chapter Two"] == "TWOMARK edited narration."
    assert "edited" not in " ".join(b for t, b in body_by_title.items() if t != "Chapter Two")


def test_prepared_chunk_fields_not_restored_onto_different_text(tmp_path):
    pending = _build_pending(tmp_path)
    (two,) = _chunks_for(pending, "TWOMARK")
    two["text"] = "Some other source text."
    two["speaker_id"] = "hero"
    two["normalized_text"] = "Some other source text."

    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))

    (two,) = _chunks_for(pending, "TWOMARK")
    assert two["speaker_id"] == "narrator"
    assert "TWOMARK" in two["normalized_text"]


@pytest.fixture
def normalize_calls(monkeypatch):
    """Count chunk normalizations (LLM mode issues a completion per call)."""
    import abogen.chunking as chunking

    calls: List[str] = []
    real = chunking._normalize_chunk_text

    def counting(value):
        calls.append(value)
        return real(value)

    monkeypatch.setattr(chunking, "_normalize_chunk_text", counting)
    return calls


def _unavailable_normalizer(monkeypatch):
    import abogen.chunking as chunking

    def unavailable(value):
        raise RuntimeError("normalizer unavailable")

    monkeypatch.setattr(chunking, "_normalize_chunk_text", unavailable)


def _default_indices(pending):
    return {i for i, c in enumerate(pending.chapters) if c.get("enabled")}


def test_unchanged_update_and_finish_do_not_renormalize(tmp_path, normalize_calls):
    pending = _build_pending(tmp_path)
    initial_chunks = [dict(chunk) for chunk in pending.chunks]
    normalize_calls.clear()

    form = _selection_form(pending, _default_indices(pending))
    apply_prepare_form(pending, form)  # /wizard/update
    apply_prepare_form(pending, form)  # /wizard/finish

    assert normalize_calls == []
    assert pending.chunks == initial_chunks


def test_enabling_chapters_normalizes_only_new_source_chunks(tmp_path, normalize_calls):
    pending = _build_pending(tmp_path)
    initially_enabled = {c["id"] for c in pending.chapters if c.get("enabled")}
    normalize_calls.clear()

    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))

    new_chunks = [
        chunk for chunk in pending.chunks if chunk["id"].split("_p", 1)[0] not in initially_enabled
    ]
    assert new_chunks
    assert len(normalize_calls) == len(new_chunks)
    assert [chunk["chapter_index"] for chunk in pending.chunks] == sorted(
        chunk["chapter_index"] for chunk in pending.chunks
    )

    normalize_calls.clear()
    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))
    assert normalize_calls == []


def test_finish_prepared_unchanged_job_without_normalizer(tmp_path, monkeypatch):
    pending = _build_pending(tmp_path)
    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))
    prepared = [dict(chunk) for chunk in pending.chunks]

    _unavailable_normalizer(monkeypatch)
    apply_prepare_form(pending, _selection_form(pending, set(range(len(CHAPTERS)))))

    assert pending.chunks == prepared
    _assert_bodies_match_titles(_plan_bodies(pending), [title for title, _ in CHAPTERS])


def test_disabling_chapters_needs_no_normalizer(tmp_path, monkeypatch):
    pending = _build_pending(tmp_path)
    _unavailable_normalizer(monkeypatch)

    apply_prepare_form(pending, _selection_form(pending, {3, 4}))

    _assert_bodies_match_titles(_plan_bodies(pending), ["Chapter Two", "Chapter Three"])
    assert [chunk["chapter_index"] for chunk in pending.chunks] == [0, 1]


def test_retained_chapter_takes_its_new_voice_without_renormalizing(tmp_path, normalize_calls):
    pending = _build_pending(tmp_path)
    normalize_calls.clear()
    form = _selection_form(pending, _default_indices(pending))
    form["chapter-3-voice"] = "voice:am_liam"

    apply_prepare_form(pending, form)

    assert normalize_calls == []
    (two,) = _chunks_for(pending, "TWOMARK")
    assert two["voice"] == "am_liam"
    assert all(chunk["voice"] is None for chunk in pending.chunks if chunk is not two)


_REAL_EPUB = os.environ.get("ABOGEN_REGRESSION_EPUB")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", text.lower())


@pytest.mark.skipif(
    not _REAL_EPUB or not Path(_REAL_EPUB).is_file(),
    reason="set ABOGEN_REGRESSION_EPUB to a real EPUB to run",
)
def test_real_epub_select_all_keeps_each_body_under_its_heading(tmp_path):
    from abogen.text_extractor import extract_from_path

    epub_path = Path(_REAL_EPUB)
    extraction = extract_from_path(epub_path)
    pending = build_pending_job_from_extraction(
        stored_path=epub_path,
        original_name=epub_path.name,
        extraction=extraction,
        form={"voice": "bf_isabella", "language": "en-GB"},
        settings=load_settings(),
        profiles={},
    ).pending
    assert not all(c.get("enabled") for c in pending.chapters)

    apply_prepare_form(pending, _selection_form(pending, set(range(len(pending.chapters)))))

    bodies = _plan_bodies(pending)
    assert [title for title, _ in bodies] == [c["title"] for c in pending.chapters]
    for chapter, (title, body) in zip(pending.chapters, bodies):
        # Each heading must carry exactly the chunks of its own source text.
        own_chunks = build_chunks_for_chapters([chapter], level=pending.chunk_level)
        expected = " ".join(
            str(c.get("normalized_text") or c.get("text") or "").strip() for c in own_chunks
        )
        assert _squash(body) == _squash(expected), f"{title!r} body does not match its source"
        source_words = _words(chapter.get("text") or "")
        if source_words:
            assert _words(body)[:1] == source_words[:1], f"{title!r} opens with foreign text"
