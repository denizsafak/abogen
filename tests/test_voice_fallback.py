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


from unittest.mock import patch, MagicMock


class TestResolveFallbackVoiceSpec:
    """Tests for the voice fallback resolution helper."""

    def test_uses_base_voice_spec(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="af_heart",
            job_voice="af_bella",
            voice_cache_keys=[],
        )
        assert result == "af_heart"

    def test_falls_back_to_job_voice(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="",
            job_voice="af_bella",
            voice_cache_keys=[],
        )
        assert result == "af_bella"

    def test_skips_custom_mix_uses_job_voice(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="__custom_mix",
            job_voice="af_bella",
            voice_cache_keys=[],
        )
        assert result == "af_bella"

    def test_falls_back_to_voice_cache(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="",
            job_voice="",
            voice_cache_keys=["kokoro:af_heart"],
        )
        assert result == "af_heart"

    def test_skips_custom_mix_in_cache(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="",
            job_voice="",
            voice_cache_keys=["__custom_mix", "kokoro:af_heart"],
        )
        assert result == "af_heart"

    def test_falls_back_to_default_voice(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        with patch("abogen.domain.voice_resolution.get_default_voice", return_value="af_heart"):
            result = resolve_fallback_voice_spec(
                base_spec="",
                job_voice="",
                voice_cache_keys=[],
            )
        assert result == "af_heart"

    def test_empty_base_and_job_with_cache(self) -> None:
        from abogen.domain.voice_resolution import resolve_fallback_voice_spec

        result = resolve_fallback_voice_spec(
            base_spec="",
            job_voice="",
            voice_cache_keys=["kokoro:af_bella", "kokoro:af_heart"],
        )
        assert result == "af_bella"
