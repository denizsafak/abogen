import json
from pathlib import Path

import numpy as np
import pytest

from abogen.debug_tts_samples import DEBUG_TTS_SAMPLES, MARKER_PREFIX, MARKER_SUFFIX, iter_expected_codes
from abogen.kokoro_text_normalization import HAS_NUM2WORDS, normalize_for_pipeline
from abogen.normalization_settings import build_apostrophe_config
from abogen.text_extractor import extract_from_path
from abogen.webui.app import create_app


def test_debug_epub_contains_all_codes():
    epub_path = Path("tests/fixtures/abogen_debug_tts_samples.epub")
    assert epub_path.exists()

    extraction = extract_from_path(epub_path)
    combined = extraction.combined_text or "\n\n".join((c.text or "") for c in extraction.chapters)

    for code in iter_expected_codes():
        marker = f"{MARKER_PREFIX}{code}{MARKER_SUFFIX}"
        assert marker in combined


def test_debug_samples_normalize_smoke():
    # Use the same defaults as the web UI.
    from abogen.webui.routes.utils.settings import settings_defaults

    settings = settings_defaults()
    apostrophe = build_apostrophe_config(settings=settings)
    runtime = dict(settings)

    normalized = {
        sample.code: normalize_for_pipeline(sample.text, config=apostrophe, settings=runtime)
        for sample in DEBUG_TTS_SAMPLES
    }

    # Contractions should expand under defaults.
    assert "it is" in normalized["APOS_001"].lower()

    # Titles should expand.
    assert "doctor" in normalized["TITLE_001"].lower()

    # Footnotes should be removed.
    assert "[1]" not in normalized["FOOT_001"]

    # Terminal punctuation should be added.
    assert normalized["PUNC_001"].strip()[-1] in {".", "!", "?"}

    if HAS_NUM2WORDS:
        # Currency and numbers should expand to words when num2words is available.
        assert "dollar" in normalized["CUR_001"].lower()
        assert "thousand" in normalized["NUM_001"].lower()


def test_settings_debug_route_writes_manifest(tmp_path, monkeypatch):
    # Avoid pulling Kokoro models in tests: stub the pipeline.
    from abogen.webui import debug_tts_runner as runner

    class _Seg:
        def __init__(self, audio):
            self.audio = audio

    class DummyPipeline:
        def __call__(self, text, **kwargs):
            # 100ms of audio per call, deterministic.
            audio = np.zeros(int(0.1 * runner.SAMPLE_RATE), dtype="float32")
            audio[::100] = 0.1
            yield _Seg(audio)

    monkeypatch.setattr(runner, "_load_pipeline", lambda language, use_gpu: DummyPipeline())

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "OUTPUT_FOLDER": str(tmp_path),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )

    with app.test_client() as client:
        resp = client.post("/settings/debug/run")
        assert resp.status_code in {302, 303}
        location = resp.headers.get("Location", "")
        assert "/settings/debug/" in location

        # Extract run id from /settings/debug/<run_id>
        run_id = location.rsplit("/settings/debug/", 1)[1].split("?", 1)[0].split("#", 1)[0]
        manifest_path = tmp_path / "debug" / run_id / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        filenames = {item["filename"] for item in manifest.get("artifacts", [])}
        assert "overall.wav" in filenames
        assert any(name.startswith("case_") and name.endswith(".wav") for name in filenames)


def test_debug_samples_have_minimum_per_category():
    prefixes = {
        "APOS": 5,
        "POS": 5,
        "NUM": 5,
        "YEAR": 5,
        "DATE": 5,
        "CUR": 5,
        "TITLE": 5,
        "PUNC": 5,
        "QUOTE": 5,
        "FOOT": 5,
    }

    counts = {prefix: 0 for prefix in prefixes}
    for sample in DEBUG_TTS_SAMPLES:
        prefix = sample.code.split("_", 1)[0]
        if prefix in counts:
            counts[prefix] += 1

    for prefix, minimum in prefixes.items():
        assert counts[prefix] >= minimum


def test_debug_runner_resolves_profile_voice_before_pipeline(tmp_path, monkeypatch):
    from abogen.webui import debug_tts_runner as runner

    # Stub voice setting resolution so we don't depend on the user's profile file.
    monkeypatch.setattr(runner, "_resolve_voice_setting", lambda value: ("af_heart", "AM HQ Alt", None))

    calls = []

    class _Seg:
        def __init__(self, audio):
            self.audio = audio

    class DummyPipeline:
        def __call__(self, text, **kwargs):
            calls.append(kwargs.get("voice"))
            audio = np.zeros(int(0.05 * runner.SAMPLE_RATE), dtype="float32")
            yield _Seg(audio)

    monkeypatch.setattr(runner, "_load_pipeline", lambda language, use_gpu: DummyPipeline())

    settings = {
        "language": "en",
        "default_voice": "profile:AM HQ Alt",
        "use_gpu": False,
        "default_speed": 1.0,
    }

    manifest = runner.run_debug_tts_wavs(output_root=tmp_path, settings=settings)
    assert manifest.get("run_id")
    assert calls
    # Must not pass through the profile:* string.
    assert all(isinstance(v, str) and not v.lower().startswith("profile:") for v in calls)
