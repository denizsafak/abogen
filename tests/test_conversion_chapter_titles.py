import sys
import types

if "soundfile" not in sys.modules:
    soundfile_stub = types.ModuleType("soundfile")

    class _SoundFileStub:  # pragma: no cover - placeholder to satisfy imports
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("soundfile is not installed in the test environment")

    soundfile_stub.SoundFile = _SoundFileStub  # type: ignore[attr-defined]
    sys.modules["soundfile"] = soundfile_stub

if "static_ffmpeg" not in sys.modules:
    sys.modules["static_ffmpeg"] = types.ModuleType("static_ffmpeg")

if "ebooklib" not in sys.modules:
    ebooklib_stub = types.ModuleType("ebooklib")
    ebooklib_epub_stub = types.ModuleType("ebooklib.epub")
    ebooklib_stub.epub = ebooklib_epub_stub  # type: ignore[attr-defined]
    sys.modules["ebooklib"] = ebooklib_stub
    sys.modules["ebooklib.epub"] = ebooklib_epub_stub

if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")

if "markdown" not in sys.modules:
    markdown_stub = types.ModuleType("markdown")

    class _MarkdownStub:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.toc_tokens = []

        def convert(self, text: str) -> str:
            return text

    markdown_stub.Markdown = _MarkdownStub  # type: ignore[attr-defined]
    sys.modules["markdown"] = markdown_stub

if "bs4" not in sys.modules:
    bs4_stub = types.ModuleType("bs4")

    class _BeautifulSoupStub:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._text = ""

        def find(self, *args: object, **kwargs: object) -> None:
            return None

        def get_text(self) -> str:
            return self._text

        def decompose(self) -> None:  # pragma: no cover - compatibility shim
            return None

    class _NavigableStringStub(str):
        pass

    bs4_stub.BeautifulSoup = _BeautifulSoupStub  # type: ignore[attr-defined]
    bs4_stub.NavigableString = _NavigableStringStub  # type: ignore[attr-defined]
    sys.modules["bs4"] = bs4_stub


from abogen.webui.conversion_runner import (
    _format_spoken_chapter_title,
    _headings_equivalent,
    _normalize_chapter_opening_caps,
    _strip_duplicate_heading_line,
)


def test_format_spoken_chapter_title_adds_prefix() -> None:
    assert _format_spoken_chapter_title("1: A Tale", 1, True) == "Chapter 1. A Tale"


def test_format_spoken_chapter_title_respects_existing_prefix() -> None:
    assert (
        _format_spoken_chapter_title("Chapter 2: Story", 2, True) == "Chapter 2: Story"
    )


def test_format_spoken_chapter_title_handles_empty_title() -> None:
    assert _format_spoken_chapter_title("", 4, True) == "Chapter 4"


def test_format_spoken_chapter_title_trims_delimiters() -> None:
    assert (
        _format_spoken_chapter_title("7 - Into the Wild", 7, True)
        == "Chapter 7. Into the Wild"
    )


def test_headings_equivalent_ignores_case_and_prefix() -> None:
    assert _headings_equivalent("1: The House", "Chapter 1: The House")


def test_strip_duplicate_heading_line_removes_first_match() -> None:
    text, removed = _strip_duplicate_heading_line(
        "Chapter 3: Intro\nBody text", "Chapter 3: Intro"
    )
    assert removed is True
    assert text.strip() == "Body text"


def test_normalize_chapter_opening_caps_basic_title() -> None:
    normalized, changed = _normalize_chapter_opening_caps("ALL CAPS TITLE")
    assert normalized == "All Caps Title"
    assert changed is True


def test_normalize_chapter_opening_caps_respects_acronyms() -> None:
    normalized, changed = _normalize_chapter_opening_caps("NASA MISSION LOG")
    assert normalized == "NASA Mission Log"
    assert changed is True


def test_normalize_chapter_opening_caps_handles_roman_numerals() -> None:
    normalized, changed = _normalize_chapter_opening_caps("IV. THE RETURN")
    assert normalized == "IV. The Return"
    assert changed is True


def test_normalize_chapter_opening_caps_keeps_mixed_case() -> None:
    normalized, changed = _normalize_chapter_opening_caps("Already Mixed Case")
    assert normalized == "Already Mixed Case"
    assert changed is False
