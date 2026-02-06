from __future__ import annotations

from types import SimpleNamespace

from abogen.chunking import chunk_text
from abogen.webui.conversion_runner import _chunk_voice_spec, _group_chunks_by_chapter


def test_group_chunks_by_chapter_orders_and_groups() -> None:
    chunks = [
        {"chapter_index": "0", "chunk_index": "5", "text": "tail"},
        {"chapter_index": 0, "chunk_index": 1, "text": "body"},
        {"chapter_index": 1, "chunk_index": 0, "text": "next"},
    ]

    grouped = _group_chunks_by_chapter(chunks)

    assert [entry["text"] for entry in grouped[0]] == ["body", "tail"]
    assert grouped[1][0]["text"] == "next"


def test_chunk_voice_spec_prefers_chunk_overrides() -> None:
    job = SimpleNamespace(voice="base_voice", speakers={})
    chunk = {"voice": "override_voice", "speaker_id": "narrator"}

    assert _chunk_voice_spec(job, chunk, "fallback") == "override_voice"


def test_chunk_voice_spec_falls_back_to_speaker_voice() -> None:
    job = SimpleNamespace(
        voice="base_voice", speakers={"narrator": {"voice": "speaker_voice"}}
    )
    chunk = {"speaker_id": "narrator"}

    assert _chunk_voice_spec(job, chunk, "fallback") == "speaker_voice"


def test_chunk_voice_spec_uses_fallback_when_no_overrides() -> None:
    job = SimpleNamespace(voice="base_voice", speakers={})
    chunk = {"speaker_id": "unknown"}

    assert _chunk_voice_spec(job, chunk, "fallback") == "fallback"


def test_chunk_text_merges_title_abbreviations() -> None:
    text = "Dr. Watson met Mr. Holmes at 5 p.m."

    chunks = chunk_text(
        chapter_index=0,
        chapter_title="Chapter 1",
        text=text,
        level="sentence",
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    text_value = str(chunk["text"])
    normalized_value = str(chunk.get("normalized_text") or "")
    assert normalized_value
    assert text_value.startswith("Dr.")
    assert "Doctor" in normalized_value
    display_value = str(chunk.get("display_text") or "")
    assert display_value.startswith("Dr.")
    original_value = str(chunk.get("original_text") or "")
    assert original_value.startswith("Dr.")


def test_chunk_text_display_preserves_whitespace() -> None:
    text = "Line one  with  double spaces.\nSecond line\n\nThird paragraph."

    chunks = chunk_text(
        chapter_index=0,
        chapter_title="Chapter 1",
        text=text,
        level="paragraph",
    )

    assert len(chunks) == 2
    first_display = str(chunks[0].get("display_text") or "")
    assert "  with  " in first_display
    assert first_display.endswith("\n\n")
    second_display = str(chunks[1].get("display_text") or "")
    assert second_display == "Third paragraph."
    first_original = str(chunks[0].get("original_text") or "")
    assert first_original.endswith("\n\n")
