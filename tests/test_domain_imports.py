"""Tests that voice.py imports from domain modules, not from conversion_runner."""
import pathlib


def _read_source(module_file: str) -> str:
    return pathlib.Path(module_file).read_text(encoding="utf-8")


def test_voice_module_does_not_import_conversion_runner():
    """voice.py must not import from conversion_runner (architecture rule)."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)

    assert "from abogen.webui.conversion_runner import" not in source_text, (
        "voice.py still imports from conversion_runner — must use domain modules"
    )


def test_voice_module_imports_select_device_from_domain():
    """voice.py must import select_device from abogen.domain.device."""
    import abogen.webui.routes.utils.voice as voice_mod

    with open(voice_mod.__file__, "r", encoding="utf-8") as fh:
        source_text = fh.read()

    assert "from abogen.domain.device import" in source_text


def test_voice_module_imports_to_float32_from_domain():
    """voice.py must import to_float32 from abogen.domain.audio_helpers."""
    import abogen.webui.routes.utils.voice as voice_mod

    with open(voice_mod.__file__, "r", encoding="utf-8") as fh:
        source_text = fh.read()

    assert "from abogen.domain.audio_helpers import" in source_text


def test_voice_module_has_sample_rate():
    """voice.py must define SAMPLE_RATE = 24000."""
    from abogen.webui.routes.utils.voice import SAMPLE_RATE

    assert SAMPLE_RATE == 24000


def test_voice_module_has_split_pattern():
    """voice.py must define SPLIT_PATTERN."""
    from abogen.webui.routes.utils.voice import SPLIT_PATTERN

    assert isinstance(SPLIT_PATTERN, str)
    assert len(SPLIT_PATTERN) > 0


def test_preview_module_does_not_import_conversion_runner():
    """preview.py must not import from conversion_runner."""
    import abogen.webui.routes.utils.preview as preview_mod

    with open(preview_mod.__file__, "r", encoding="utf-8") as fh:
        source_text = fh.read()

    assert "from abogen.webui.conversion_runner import" not in source_text


def test_preview_module_imports_select_device_from_domain():
    """preview.py must import select_device from abogen.domain.device."""
    import abogen.webui.routes.utils.preview as preview_mod

    with open(preview_mod.__file__, "r", encoding="utf-8") as fh:
        source_text = fh.read()

    assert "from abogen.domain.device import" in source_text
