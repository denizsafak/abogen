"""Tests that voice.py imports from domain modules, not from conversion_runner."""
import pathlib


_MODULE_SOURCE_CACHE: dict[str, str] = {}


def _read_source(module_file: str) -> str:
    if module_file not in _MODULE_SOURCE_CACHE:
        _MODULE_SOURCE_CACHE[module_file] = pathlib.Path(module_file).read_text(
            encoding="utf-8"
        )
    return _MODULE_SOURCE_CACHE[module_file]


def test_voice_module_does_not_import_conversion_runner():
    """voice.py must not import from conversion_runner (architecture rule)."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)

    assert "from abogen.webui.conversion_runner import" not in source_text, (
        "voice.py still imports from conversion_runner — must use domain modules"
    )


def test_synthesize_module_does_not_import_conversion_runner():
    """synthesize.py must not import from conversion_runner."""
    import abogen.webui.routes.utils.synthesize as synthesize_mod

    source_text = _read_source(synthesize_mod.__file__)

    assert "from abogen.webui.conversion_runner import" not in source_text


def test_synthesize_module_imports_select_device_from_domain():
    """synthesize.py must import select_device from abogen.domain.device."""
    import abogen.webui.routes.utils.synthesize as synthesize_mod

    source_text = _read_source(synthesize_mod.__file__)
    assert "from abogen.domain.device import" in source_text


def test_voice_module_does_not_define_synthesize_audio_from_normalized():
    """Dead code: synthesize_audio_from_normalized must be removed from voice.py."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)
    assert "def synthesize_audio_from_normalized(" not in source_text


def test_voice_module_does_not_define_get_preview_pipeline():
    """Dead code: get_preview_pipeline must be removed from voice.py."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)
    assert "def get_preview_pipeline(" not in source_text


def test_voice_module_does_not_import_domain_audio_helpers():
    """After removing dead code, voice.py no longer needs audio_helpers imports."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)
    assert "from abogen.domain.audio_helpers import" not in source_text


def test_voice_module_does_not_import_domain_device():
    """After removing dead code, voice.py no longer needs device imports."""
    import abogen.webui.routes.utils.voice as voice_mod

    source_text = _read_source(voice_mod.__file__)
    assert "from abogen.domain.device import" not in source_text
