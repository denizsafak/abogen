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


from abogen.webui.conversion_runner import _build_outro_text, _build_title_intro_text


def test_title_intro_includes_series_sentence() -> None:
    metadata = {
        "title": "Galactic Chronicles",
        "author": "Jane Doe",
        "series": "Chronicles",
        "series_index": "2",
    }

    intro_text = _build_title_intro_text(metadata, "chronicles.mp3")

    assert intro_text.startswith("Book 2 of the Chronicles.")
    assert "Galactic Chronicles." in intro_text
    assert "By Jane Doe." in intro_text


def test_series_sentence_skips_duplicate_article() -> None:
    metadata = {
        "title": "Iron Council",
        "authors": "China Miéville",
        "series": "The Bas-Lag",
        "series_index": "3",
    }

    intro_text = _build_title_intro_text(metadata, "iron_council.mp3")

    assert "Book 3 of The Bas-Lag." in intro_text
    assert "of the The" not in intro_text


def test_outro_appends_series_information() -> None:
    metadata = {
        "title": "Abaddon's Gate",
        "authors": "James S. A. Corey",
        "series": "The Expanse",
        "series_index": "3",
    }

    outro_text = _build_outro_text(metadata, "abaddon.mp3")

    assert outro_text.startswith("The end of Abaddon's Gate from James S. A. Corey.")
    assert outro_text.endswith("Book 3 of The Expanse.")


def test_series_number_preserves_decimal_positions() -> None:
    metadata = {
        "title": "Interlude",
        "author": "Alex Writer",
        "series": "Chronicles",
        "series_index": "2.5",
    }

    intro_text = _build_title_intro_text(metadata, "interlude.mp3")

    assert "Book 2.5 of the Chronicles." in intro_text