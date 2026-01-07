from __future__ import annotations

import html
import re
import zipfile

from abogen.epub3.exporter import build_epub3_package
from abogen.text_extractor import ExtractedChapter, ExtractionResult


def _make_sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        chapters=[
            ExtractedChapter(title="Chapter 1", text="Hello world."),
            ExtractedChapter(title="Chapter 2", text="Another passage."),
        ],
        metadata={"title": "Sample Book", "artist": "Test Author", "language": "en"},
    )


def test_build_epub3_package_creates_expected_structure(tmp_path) -> None:
    extraction = _make_sample_extraction()
    chunks = [
        {
            "id": "chap0000_p0000",
            "chapter_index": 0,
            "chunk_index": 0,
            "text": "Hello world.",
            "speaker_id": "narrator",
        },
        {
            "id": "chap0001_p0000",
            "chapter_index": 1,
            "chunk_index": 0,
            "text": "Another passage.",
            "speaker_id": "narrator",
        },
    ]
    chunk_markers = [
        {"id": "chap0000_p0000", "chapter_index": 0, "chunk_index": 0, "start": 0.0, "end": 1.2},
        {"id": "chap0001_p0000", "chapter_index": 1, "chunk_index": 0, "start": 1.2, "end": 2.4},
    ]
    chapter_markers = [
        {"index": 1, "title": "Chapter 1", "start": 0.0, "end": 1.2},
        {"index": 2, "title": "Chapter 2", "start": 1.2, "end": 2.4},
    ]
    metadata_tags = {"title": "Sample Book", "artist": "Test Author", "language": "en"}

    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"ID3 test audio")

    output_path = tmp_path / "output.epub"
    result_path = build_epub3_package(
        output_path=output_path,
        book_id="job-123",
        extraction=extraction,
        metadata_tags=metadata_tags,
        chapter_markers=chapter_markers,
        chunk_markers=chunk_markers,
        chunks=chunks,
        audio_path=audio_path,
        speaker_mode="single",
    )

    assert result_path == output_path
    assert output_path.exists()

    with zipfile.ZipFile(output_path) as archive:
        names = set(archive.namelist())
        assert "mimetype" in names
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/audio/sample.mp3" in names
        chapter_doc = archive.read("OEBPS/text/chapter_0001.xhtml").decode("utf-8")
        assert "Hello world." in chapter_doc
        smil_doc = archive.read("OEBPS/smil/chapter_0001.smil").decode("utf-8")
        assert "clipBegin=\"00:00:00.000\"" in smil_doc
        opf_doc = archive.read("OEBPS/content.opf").decode("utf-8")
        assert "media-overlay" in opf_doc
        assert "media:duration" in opf_doc
        assert "abogen:speakerMode" in opf_doc


def test_build_epub3_package_handles_missing_markers(tmp_path) -> None:
    extraction = _make_sample_extraction()
    metadata_tags = {"title": "Sample Book", "artist": "Test Author", "language": "en"}
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"ID3 audio")
    output_path = tmp_path / "output.epub"

    result_path = build_epub3_package(
        output_path=output_path,
        book_id="job-456",
        extraction=extraction,
        metadata_tags=metadata_tags,
        chapter_markers=[],
        chunk_markers=[],
        chunks=[],
        audio_path=audio_path,
        speaker_mode="single",
    )

    with zipfile.ZipFile(result_path) as archive:
        nav_doc = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "Chapter 1" in nav_doc
        chapter_doc = archive.read("OEBPS/text/chapter_0001.xhtml").decode("utf-8")
        assert "Hello world." in chapter_doc


def test_epub3_preserves_original_whitespace(tmp_path) -> None:
    extraction = ExtractionResult(
        chapters=[
            ExtractedChapter(
                title="Intro",
                text="Line one  with  double spaces.\nSecond line\n\nThird paragraph.",
            )
        ],
        metadata={"title": "Sample", "artist": "Author", "language": "en"},
    )

    chunks = [
        {
            "id": "chap0000_p0000",
            "chapter_index": 0,
            "chunk_index": 0,
            "text": "Line one with double spaces.",
            "speaker_id": "narrator",
        },
        {
            "id": "chap0000_p0001",
            "chapter_index": 0,
            "chunk_index": 1,
            "text": "Second line",
            "speaker_id": "narrator",
        },
        {
            "id": "chap0000_p0002",
            "chapter_index": 0,
            "chunk_index": 2,
            "text": "Third paragraph.",
            "speaker_id": "narrator",
        },
    ]

    chunk_markers = [
        {"id": chunk["id"], "chapter_index": 0, "chunk_index": chunk["chunk_index"], "start": None, "end": None}
        for chunk in chunks
    ]

    metadata_tags = {"title": "Sample", "artist": "Author", "language": "en"}
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"ID3 audio")
    output_path = tmp_path / "output.epub"

    build_epub3_package(
        output_path=output_path,
        book_id="job-whitespace",
        extraction=extraction,
        metadata_tags=metadata_tags,
        chapter_markers=[],
        chunk_markers=chunk_markers,
        chunks=chunks,
        audio_path=audio_path,
        speaker_mode="single",
    )

    with zipfile.ZipFile(output_path) as archive:
        chapter_doc = archive.read("OEBPS/text/chapter_0001.xhtml").decode("utf-8")
    assert "Line one  with  double spaces." in chapter_doc

    chunk_section = chapter_doc.replace("        ", "")
    assert "Second line" in chunk_section
    assert "Third paragraph." in chunk_section

    match = re.search(r"<pre class=\"chapter-original\"[^>]*>(.*?)</pre>", chapter_doc, re.DOTALL)
    assert match is not None
    original_text = html.unescape(match.group(1))
    assert "Second line\n\nThird paragraph." in original_text


def test_epub3_sentence_chunks_render_as_paragraphs(tmp_path) -> None:
    extraction = ExtractionResult(
        chapters=[
            ExtractedChapter(
                title="Chapter 1",
                text="First sentence. Second sentence in same paragraph.\n\nNew paragraph starts here.",
            )
        ],
        metadata={"title": "Sample", "artist": "Author", "language": "en"},
    )

    chunks = [
        {
            "id": "chap0000_p0000_s0000",
            "chapter_index": 0,
            "chunk_index": 0,
            "text": "First sentence.",
            "level": "sentence",
            "speaker_id": "narrator",
        },
        {
            "id": "chap0000_p0000_s0001",
            "chapter_index": 0,
            "chunk_index": 1,
            "text": "Second sentence in same paragraph.",
            "level": "sentence",
            "speaker_id": "narrator",
        },
        {
            "id": "chap0000_p0001_s0000",
            "chapter_index": 0,
            "chunk_index": 2,
            "text": "New paragraph starts here.",
            "level": "sentence",
            "speaker_id": "narrator",
        },
    ]

    chunk_markers = [
        {"id": chunk["id"], "chapter_index": 0, "chunk_index": chunk["chunk_index"], "start": None, "end": None}
        for chunk in chunks
    ]

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"ID3 audio")
    output_path = tmp_path / "output.epub"

    build_epub3_package(
        output_path=output_path,
        book_id="job-paragraphs",
        extraction=extraction,
        metadata_tags={"title": "Sample", "artist": "Author", "language": "en"},
        chapter_markers=[],
        chunk_markers=chunk_markers,
        chunks=chunks,
        audio_path=audio_path,
        speaker_mode="single",
    )

    with zipfile.ZipFile(output_path) as archive:
        chapter_doc = archive.read("OEBPS/text/chapter_0001.xhtml").decode("utf-8")

    assert '<div class="chunk"' not in chapter_doc
    assert chapter_doc.count('<p class="chunk-group"') == 2
    assert 'First sentence.' in chapter_doc
    assert 'Second sentence in same paragraph.' in chapter_doc

    first_paragraph_start = chapter_doc.find('<p class="chunk-group"')
    first_paragraph_end = chapter_doc.find('</p>', first_paragraph_start)
    first_paragraph = chapter_doc[first_paragraph_start:first_paragraph_end]
    assert "First sentence." in first_paragraph
    assert "Second sentence in same paragraph." in first_paragraph