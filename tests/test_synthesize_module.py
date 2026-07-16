"""Tests that preview/synthesis module is correctly named and importable."""
import pathlib


def _read_source(module_file: str) -> str:
    return pathlib.Path(module_file).read_text(encoding="utf-8")


def test_preview_file_renamed_to_synthesize():
    """preview.py must be renamed to synthesize.py."""
    import abogen.webui.routes.utils.synthesize as synthesize_mod

    synthesize_path = pathlib.Path(synthesize_mod.__file__)
    assert synthesize_path.name == "synthesize.py"
    assert synthesize_path.exists()
    assert not synthesize_path.with_name("preview.py").exists()


def test_synthesize_module_has_generate_preview_audio():
    """synthesize.py must export generate_preview_audio."""
    from abogen.webui.routes.utils.synthesize import generate_preview_audio

    assert callable(generate_preview_audio)


def test_synthesize_module_has_synthesize_preview():
    """synthesize.py must export synthesize_preview."""
    from abogen.webui.routes.utils.synthesize import synthesize_preview

    assert callable(synthesize_preview)


def test_synthesize_module_has_get_preview_pipeline():
    """synthesize.py must export get_preview_pipeline."""
    from abogen.webui.routes.utils.synthesize import get_preview_pipeline

    assert callable(get_preview_pipeline)


def test_api_imports_from_synthesize():
    """api.py must import from synthesize, not preview."""
    import abogen.webui.routes.api as api_mod

    source = _read_source(api_mod.__file__)
    assert "from abogen.webui.routes.utils.synthesize import" in source
    assert "from abogen.webui.routes.utils.preview import" not in source


def test_voices_imports_from_synthesize():
    """voices.py must import from synthesize, not preview."""
    import abogen.webui.routes.voices as voices_mod

    source = _read_source(voices_mod.__file__)
    assert "from abogen.webui.routes.utils.synthesize import" in source
    assert "from abogen.webui.routes.utils.preview import" not in source


def test_no_module_imports_preview():
    """No module should import from the old preview path."""
    import glob
    import os

    project_root = pathlib.Path(__file__).parent.parent
    py_files = glob.glob(str(project_root / "abogen" / "**" / "*.py"), recursive=True)

    for py_file in py_files:
        content = pathlib.Path(py_file).read_text(encoding="utf-8")
        assert "from abogen.webui.routes.utils.preview import" not in content, (
            f"{py_file} still imports from preview"
        )
