from __future__ import annotations

import sys
import types


def _install_dependency_stubs() -> None:
    if "ebooklib" not in sys.modules:
        ebooklib_stub = types.ModuleType("ebooklib")
        epub_stub = types.ModuleType("ebooklib.epub")
        setattr(ebooklib_stub, "epub", epub_stub)
        sys.modules["ebooklib"] = ebooklib_stub
        sys.modules["ebooklib.epub"] = epub_stub

    if "dotenv" not in sys.modules:
        dotenv_stub = types.ModuleType("dotenv")

        def _noop(*_, **__):
            return None

        setattr(dotenv_stub, "load_dotenv", _noop)
        setattr(dotenv_stub, "find_dotenv", lambda *_, **__: "")
        sys.modules["dotenv"] = dotenv_stub

    if "numpy" not in sys.modules:
        numpy_stub = types.ModuleType("numpy")

        class _DummyArray(list):
            pass

        def _zeros(shape, dtype=None):
            size = 1
            if isinstance(shape, int):
                size = shape
            elif shape:
                size = 1
                for dimension in shape:
                    size *= int(dimension)
            return [0.0] * size

        setattr(numpy_stub, "ndarray", _DummyArray)
        setattr(numpy_stub, "zeros", _zeros)
        setattr(numpy_stub, "float32", "float32")
        setattr(numpy_stub, "array", lambda data, dtype=None: data)
        setattr(numpy_stub, "asarray", lambda data, dtype=None: data)
        setattr(
            numpy_stub,
            "concatenate",
            lambda seq, axis=0: sum((list(item) for item in seq), []),
        )
        sys.modules["numpy"] = numpy_stub

    if "soundfile" not in sys.modules:
        soundfile_stub = types.ModuleType("soundfile")

        class _DummySoundFile:
            def __init__(self, *_, **__):
                pass

            def write(self, *_args, **_kwargs):
                return None

            def close(self):
                return None

        setattr(soundfile_stub, "SoundFile", _DummySoundFile)
        setattr(soundfile_stub, "write", lambda *_args, **_kwargs: None)
        sys.modules["soundfile"] = soundfile_stub

    if "fitz" not in sys.modules:
        sys.modules["fitz"] = types.ModuleType("fitz")

    if "markdown" not in sys.modules:
        markdown_stub = types.ModuleType("markdown")

        class _DummyMarkdown:
            def __init__(self, *_, **__):
                pass

            def convert(self, text: str) -> str:
                return text

        setattr(markdown_stub, "Markdown", _DummyMarkdown)
        sys.modules["markdown"] = markdown_stub

    if "bs4" not in sys.modules:
        bs4_stub = types.ModuleType("bs4")

        class _DummySoup:
            def __init__(self, *_, **__):
                pass

            def select(self, *_, **__):
                return []

            def find_all(self, *_, **__):
                return []

        setattr(bs4_stub, "BeautifulSoup", _DummySoup)
        setattr(bs4_stub, "NavigableString", str)
        sys.modules["bs4"] = bs4_stub


_install_dependency_stubs()

from abogen.text_extractor import ExtractedChapter
from abogen.webui.conversion_runner import _apply_chapter_overrides, _merge_metadata


def _sample_chapters() -> list[ExtractedChapter]:
    return [
        ExtractedChapter(title="Chapter 1", text="Original one"),
        ExtractedChapter(title="Chapter 2", text="Original two"),
        ExtractedChapter(title="Chapter 3", text="Original three"),
    ]


def test_apply_chapter_overrides_with_custom_text() -> None:
    overrides = [
        {"index": 0, "enabled": True, "title": "Intro", "text": "Hello world"},
        {"index": 1, "enabled": False},
    ]

    selected, metadata, diagnostics = _apply_chapter_overrides(
        _sample_chapters(), overrides
    )

    assert len(selected) == 1
    assert selected[0].title == "Intro"
    assert selected[0].text == "Hello world"
    assert overrides[0]["characters"] == len("Hello world")
    assert metadata == {}
    assert diagnostics == []


def test_apply_chapter_overrides_uses_original_content_when_text_missing() -> None:
    overrides = [
        {"index": 1, "enabled": True},
    ]

    selected, metadata, diagnostics = _apply_chapter_overrides(
        _sample_chapters(), overrides
    )

    assert len(selected) == 1
    assert selected[0].title == "Chapter 2"
    assert selected[0].text == "Original two"
    assert overrides[0]["text"] == "Original two"
    assert overrides[0]["characters"] == len("Original two")
    assert metadata == {}
    assert diagnostics == []


def test_apply_chapter_overrides_collects_metadata_updates() -> None:
    overrides = [
        {
            "index": 2,
            "enabled": True,
            "metadata": {"artist": "Test Author", "year": 2024},
        }
    ]

    selected, metadata, diagnostics = _apply_chapter_overrides(
        _sample_chapters(), overrides
    )

    assert len(selected) == 1
    assert metadata == {"artist": "Test Author", "year": "2024"}
    assert diagnostics == []


def test_apply_chapter_overrides_reports_diagnostics_for_invalid_payload() -> None:
    overrides = [
        {"enabled": True, "title": "Missing"},
    ]

    selected, metadata, diagnostics = _apply_chapter_overrides(
        _sample_chapters(), overrides
    )

    assert selected == []
    assert metadata == {}
    assert diagnostics and "Skipped chapter override" in diagnostics[0]


def test_merge_metadata_prefers_overrides_and_drops_none_values() -> None:
    extracted = {"title": "Original", "artist": "Someone"}
    overrides = {"artist": "Another", "genre": "Fiction", "year": None}

    merged = _merge_metadata(extracted, overrides)

    assert merged["title"] == "Original"
    assert merged["artist"] == "Another"
    assert merged["genre"] == "Fiction"
    assert "year" not in merged
