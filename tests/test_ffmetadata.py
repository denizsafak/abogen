from __future__ import annotations

from pathlib import Path

from abogen.webui.conversion_runner import _render_ffmetadata, _write_ffmetadata_file


def test_render_ffmetadata_includes_chapters(tmp_path):
    metadata = {
        "title": "Sample Book",
        "artist": "Author Name",
        "comment": "Line one\nLine two",
        "publisher": "ACME=Corp",
    }
    chapters = [
        {"start": 0.0, "end": 5.0, "title": "Intro", "voice": "voice_a"},
        {"start": 5.0, "end": 12.345, "title": "Chapter 2"},
    ]

    rendered = _render_ffmetadata(metadata, chapters)

    assert ";FFMETADATA1" in rendered
    assert "title=Sample Book" in rendered
    assert "artist=Author Name" in rendered
    assert "comment=Line one\\nLine two" in rendered
    assert "publisher=ACME\\=Corp" in rendered
    assert rendered.count("[CHAPTER]") == 2
    assert "START=0" in rendered
    assert "END=5000" in rendered
    assert "voice=voice_a" in rendered

    audio_path = tmp_path / "book.m4b"
    metadata_path = _write_ffmetadata_file(audio_path, metadata, chapters)
    assert metadata_path is not None
    assert metadata_path.exists()

    content = metadata_path.read_text(encoding="utf-8")
    assert "END=12345" in content

    metadata_path.unlink()
